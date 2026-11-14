"""Filings: what the company registers say about each company. Keyless bulk data, refreshed monthly.

    python -m news_scraper filings --companies companies.csv [--registers au,uk] [--db data/news.db]

AU  ASIC Company Dataset (data.gov.au, monthly): legal name, ACN/ABN, status, registration and deregistration dates,
    former names with the date of each change.
    ASIC Business Names Dataset (data.gov.au, monthly): the trading names registered to the company's ABN.
UK  Companies House "Free Company Data Product" (monthly, 7 zip files): status, incorporation date, SIC codes, accounts
    category and date, previous names with dates.
    The Gazette insolvency notices (searched per company): winding-up, administration, liquidator appointments.
US  not covered (SEC EDGAR needs a contact email; see README).

Matching is by exact legal name (after normalising "Pty. Ltd." / "Proprietary Limited" etc.), or by the ACN in names like
"A.C.N. 633 889 433 Pty Ltd". A name without a legal suffix ("Atkar") is tried with "Pty Ltd" / "Ltd" added, and as a
registered business name. Company names are unique in both registers, so an exact match is the company; when a name
matches more than one record (e.g. an old deregistered company with the same name), the registered one wins.

Downloads (~150 MB AU, ~470 MB UK) are cached in data/registers/ and reused until the next monthly file is published.
"""
import csv
import datetime as dt
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

import requests

from . import http
from .match import LEGAL, NUMBERED, core_name, root_domain

TABLES = """
CREATE TABLE IF NOT EXISTS registry_records (
  company_id TEXT NOT NULL, register TEXT NOT NULL, checked_at TEXT NOT NULL, status TEXT, reg_id TEXT, matched_by TEXT, data TEXT,
  PRIMARY KEY (company_id, register, checked_at));
"""
CKAN = "https://data.gov.au/data/api/3/action/package_show"
CH_INDEX = "https://download.companieshouse.gov.uk/en_output.html"
CH_BASE = "https://download.companieshouse.gov.uk/"
GAZETTE = "https://www.thegazette.co.uk/insolvency/notice/data.feed"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "data", "registers")

ASIC_STATUS = {"REGD": "Registered", "EXAD": "External administration", "SOFF": "Strike-off action in progress", "DRGD": "Deregistered",
               "NOAC": "Not active", "DISS": "Dissolved", "CNCL": "Cancelled"}
# filing categories in signal_events.csv, most severe first (company_summary.filing_signal takes the most severe recent one)
FILING_CATEGORIES = ["Insolvency / administration", "Strike-off / deregistered", "Name change", "New trading name", "Newly registered"]


def ensure_tables(store):
    with store.lock, store.db:
        store.db.executescript(TABLES)


# ---------------------------------------------------------------- names
_SUBS = [(r"\bPROPRIETARY\b", "PTY"), (r"\bLIMITED\b", "LTD"), (r"\bCOMPANY\b", "CO"), (r"\bINCORPORATED\b", "INC"),
         (r"\bCORPORATION\b", "CORP"), (r"&", " AND ")]


def norm(name):
    """'Christensen & Associates Pty. Ltd.' -> 'CHRISTENSEN AND ASSOCIATES PTY LTD'."""
    n = (name or "").upper()
    for a, b in _SUBS:
        n = re.sub(a, b, n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


SPLIT = re.compile(r"\s+(?:t/?as?|trading as|atf|as trustee for)\s+|\s+/\s+|\s+-\s+", re.I)


def name_parts(name):
    """'Buy-Sell-Rent Pty Ltd T/A Scoop Property' -> [whole, 'Buy-Sell-Rent Pty Ltd', 'Scoop Property'];
    'Beverly Hills - Mazzhills Enterprises Pty Ltd / Bexley North - Furappi Pty Ltd' -> each entity."""
    parts = [name] + [p.strip(" ,()") for p in SPLIT.split(name or "") if p and len(p.strip()) >= 3]
    return list(dict.fromkeys(parts))


def name_keys(name, suffixes):
    """Names to look for: the name and each part of a multi-entity name, plus each with a legal suffix if it has none."""
    keys = []
    for part in name_parts(name):
        keys.append(norm(part))
        if not LEGAL.search(part):
            keys += [norm(f"{part} {s}") for s in suffixes]
    return [k for k in dict.fromkeys(keys) if k]


def acn_in(name):
    m = NUMBERED.match(name or "")
    digits = re.sub(r"\D", "", m.group(0)) if m else ""
    return digits if len(digits) == 9 else ""


def country_of(c):
    cc = (c.country or "").upper()
    if cc in ("AU", "UK", "GB", "US", "NZ"):
        return "UK" if cc == "GB" else cc
    d = root_domain(c.domain)
    return "AU" if d.endswith(".au") else "UK" if d.endswith(".uk") else ""


def _d(s, fmt="%d/%m/%Y"):
    try:
        return dt.datetime.strptime(s.strip(), fmt).date().isoformat() if s and s.strip() else ""
    except ValueError:
        return ""


# ---------------------------------------------------------------- downloads
def _download(url, name, log):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    log(f"  downloading {name} …")
    tmp = path + ".part"
    with requests.get(url, stream=True, timeout=120, headers={"User-Agent": http.UA}) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.replace(tmp, path)
    for old in os.listdir(CACHE):                                  # keep only the newest file of each kind
        if old != name and old.split("_")[0] == name.split("_")[0] and old.endswith(".zip") and not old.startswith("BasicCompanyData"):
            os.remove(os.path.join(CACHE, old))
    return path


def _ckan_zip(package):
    d = http.get(CKAN, params={"id": package}, interval=1.0).json()["result"]
    res = [r for r in d["resources"] if (r.get("format") or "").upper() == "ZIP"]
    url = res[0]["url"]
    return url, url.rsplit("/", 1)[-1]


def _rows(path, delimiter="\t"):
    """Rows of the (only) CSV in a zip, as dicts."""
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith((".csv", ".txt")))
        with z.open(member) as f:
            text = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline="")
            reader = csv.reader(text, delimiter=delimiter, quoting=csv.QUOTE_NONE if delimiter == "\t" else csv.QUOTE_MINIMAL)
            header = [h.strip() for h in next(reader)]
            for row in reader:
                yield dict(zip(header, row))


# ---------------------------------------------------------------- AU: ASIC
def check_au(companies, log=print):
    """company_id -> record dict (or {'status': 'not found'})."""
    co_url, co_name = _ckan_zip("asic-companies")
    bn_url, bn_name = _ckan_zip("asic-business-names")
    co_path, bn_path = _download(co_url, co_name, log), _download(bn_url, bn_name, log)
    as_of = re.search(r"(\d{6})", co_name).group(1)

    want, want_acn = defaultdict(set), defaultdict(set)
    for c in companies:
        if acn_in(c.name):
            want_acn[acn_in(c.name)].add(c.company_id)
        for k in name_keys(c.name, ["PTY LTD", "LTD"]):
            want[k].add(c.company_id)

    # pass 1: company rows matching a wanted name or ACN
    cand = defaultdict(list)                                       # company_id -> [(acn, current?, status)]
    log("  ASIC companies: matching names …")
    for r in _rows(co_path):
        n, acn = norm(r.get("Company Name")), r.get("ACN", "").strip()
        hit = want.get(n, set()) | want_acn.get(acn, set())
        for cid in hit:
            cand[cid].append((acn, r.get("Current Name Indicator") == "Y", r.get("Status", "")))

    # names not found as a company: try them as registered business names (gives the ABN, and the ACN for a company)
    missing = [c for c in companies if c.company_id not in cand]
    want_bn = defaultdict(set)
    for c in missing:
        for part in name_parts(c.name):
            want_bn[norm(core_name(part))].add(c.company_id)
    picked = {}
    for cid, rows in cand.items():
        best = sorted(rows, key=lambda x: (not x[1], x[2] != "REGD"))   # current name, then registered
        acns = {a for a, cur, st in rows if (cur, st == "REGD") == (best[0][1], best[0][2] == "REGD")}
        picked[cid] = (best[0][0], "legal name" if len(acns) == 1 else f"legal name ({len(acns)} records, first taken)")

    # business names pass: trading names of matched ABNs (filled after the company pass), and names for missing companies
    log("  ASIC business names: matching …")
    bn_for_name = defaultdict(list)
    for r in _rows(bn_path):
        n = norm(r.get("BN_NAME"))
        if n in want_bn:
            for cid in want_bn[n]:
                bn_for_name[cid].append(r)
    abn_of_bn = {}
    for cid, rows in bn_for_name.items():
        rows = sorted(rows, key=lambda r: r.get("BN_STATUS") != "Registered")
        abn = rows[0].get("BN_ABN", "").strip()
        if abn:
            abn_of_bn[cid] = abn
            if len(abn) == 11:
                picked.setdefault(cid, (abn[2:], "registered business name"))

    # pass 2: every row (current and former names) of the picked ACNs
    by_acn = defaultdict(list)
    acns = {a for a, _ in picked.values()}
    log("  ASIC companies: reading history …")
    for r in _rows(co_path):
        if r.get("ACN", "").strip() in acns:
            by_acn[r["ACN"].strip()].append(r)

    out, abns = {}, {}
    for c in companies:
        cid = c.company_id
        acn, how = picked.get(cid, ("", ""))
        rows = by_acn.get(acn, [])
        if not rows:
            if cid in abn_of_bn:                                    # a business name of a sole trader / trust / partnership
                out[cid] = {"register": "ASIC", "status": "business name only", "abn": abn_of_bn[cid], "matched_by": "registered business name",
                            "as_of": as_of, "trading_names": [], "former_names": []}
                abns[abn_of_bn[cid]] = cid
            else:
                out[cid] = {"register": "ASIC", "status": "not found", "as_of": as_of}
            continue
        cur = next((r for r in rows if r.get("Current Name Indicator") == "Y"), rows[0])
        former = [{"name": r["Company Name"].strip(), "changed_on": _d(r.get("Current Name Start Date"))}
                  for r in rows if r is not cur and r.get("Current Name Indicator") != "Y"]
        rec = {"register": "ASIC", "matched_by": how, "as_of": as_of, "name": cur["Company Name"].strip(), "acn": acn,
               "abn": cur.get("ABN", "").strip(), "status_code": cur.get("Status", ""), "status": ASIC_STATUS.get(cur.get("Status", ""), cur.get("Status", "")),
               "type": cur.get("Type", ""), "registered_on": _d(cur.get("Date of Registration")),
               "deregistered_on": _d(cur.get("Date of Deregistration")), "state": cur.get("Previous State of Registration", ""),
               "former_names": sorted(former, key=lambda x: x["changed_on"], reverse=True), "trading_names": []}
        out[cid] = rec
        if rec["abn"]:
            abns[rec["abn"]] = cid

    # trading names registered to the ABN
    log("  ASIC business names: trading names …")
    for r in _rows(bn_path):
        abn = r.get("BN_ABN", "").strip()
        if abn in abns:
            out[abns[abn]]["trading_names"].append({"name": r.get("BN_NAME", "").strip(), "status": r.get("BN_STATUS", ""),
                                                    "registered_on": _d(r.get("BN_REG_DT")), "cancelled_on": _d(r.get("BN_CANCEL_DT"))})
    return out


# ---------------------------------------------------------------- UK: Companies House + Gazette
def _ch_parts():
    html = http.get(CH_INDEX, interval=1.0).text
    names = sorted(set(re.findall(r"BasicCompanyData-\d{4}-\d{2}-\d{2}-part\d+_\d+\.zip", html)))
    return names


def check_uk(companies, log=print):
    parts = _ch_parts()
    if not parts:
        raise RuntimeError("Companies House download page lists no files")
    as_of = re.search(r"(\d{4}-\d{2}-\d{2})", parts[0]).group(1)
    for old in os.listdir(CACHE) if os.path.isdir(CACHE) else []:   # drop last month's parts
        if old.startswith("BasicCompanyData") and as_of not in old:
            os.remove(os.path.join(CACHE, old))
    want = defaultdict(set)
    for c in companies:
        for k in name_keys(c.name, ["LTD", "PLC"]):
            want[k].add(c.company_id)
    cand = defaultdict(list)
    for p in parts:
        path = _download(CH_BASE + p, p, log)
        log(f"  Companies House {p}: matching …")
        for r in _rows(path, delimiter=","):
            names = [r.get("CompanyName", "")] + [r.get(f"PreviousName_{i}.CompanyName", "") for i in range(1, 11)]
            hits = set()
            for i, n in enumerate(names):
                if n and norm(n) in want:
                    hits |= {(cid, i == 0) for cid in want[norm(n)]}
            for cid, current in hits:
                cand[cid].append((current, r))
    out = {}
    for c in companies:
        rows = sorted(cand.get(c.company_id, []), key=lambda x: (not x[0], x[1].get("CompanyStatus") != "Active"))
        if not rows:
            out[c.company_id] = {"register": "Companies House", "status": "not found", "as_of": as_of}
            continue
        current, r = rows[0]
        prev = [{"name": r.get(f"PreviousName_{i}.CompanyName", "").strip(), "changed_on": _d(r.get(f"PreviousName_{i}.CONDATE"))}
                for i in range(1, 11) if r.get(f"PreviousName_{i}.CompanyName", "").strip()]
        out[c.company_id] = {
            "register": "Companies House", "matched_by": "legal name" if current else "previous name", "as_of": as_of,
            "name": r.get("CompanyName", "").strip(), "company_number": r.get("CompanyNumber", "").strip(),
            "status": r.get("CompanyStatus", "").strip(), "type": r.get("CompanyCategory", "").strip(),
            "registered_on": _d(r.get("IncorporationDate")), "dissolved_on": _d(r.get("DissolutionDate")),
            "town": r.get("RegAddress.PostTown", "").strip(), "postcode": r.get("RegAddress.PostCode", "").strip(),
            "sic": [r.get(f"SICCode.SicText_{i}", "").strip() for i in range(1, 5) if r.get(f"SICCode.SicText_{i}", "").strip()],
            "accounts_category": r.get("Accounts.AccountCategory", "").strip(), "accounts_made_up_to": _d(r.get("Accounts.LastMadeUpDate")),
            "former_names": prev, "trading_names": [], "candidates": len({x[1].get('CompanyNumber') for x in rows}),
        }
    # Gazette insolvency notices for each matched company
    for cid, rec in out.items():
        if rec.get("status") == "not found":
            continue
        try:
            rec["gazette"] = gazette_notices(rec["name"], rec["company_number"])
        except (http.FetchError, ET.ParseError) as e:
            rec["gazette_error"] = str(e)[:150]
    return out


ATOM = "{http://www.w3.org/2005/Atom}"


def gazette_notices(name, number):
    """Insolvency notices in The Gazette naming this company (matched on company number, else exact name)."""
    r = http.get(GAZETTE, params={"text": f'"{name}"', "results-page-size": 20}, interval=1.5, retries=1)
    root = ET.fromstring(r.content)
    out = []
    for e in root.iter(f"{ATOM}entry"):
        title = (e.findtext(f"{ATOM}title") or "").strip()
        content = ET.tostring(e, encoding="unicode", method="text")
        if not ((number and number in content) or norm(name) in norm(f"{title} {content}")):
            continue
        cat = e.find(f"{ATOM}category")
        link = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel") in (None, "alternate")), "")
        out.append({"title": title, "notice_type": cat.get("term") if cat is not None else "",
                    "published": (e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated") or "")[:10], "url": link})
    return out


# ---------------------------------------------------------------- run
def run_filings(companies, db_path, registers=("au", "uk"), log=print):
    from .store import Store
    store = Store(db_path)
    ensure_tables(store)
    for c in companies:
        store.upsert_company(c)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    groups = {"au": [c for c in companies if country_of(c) == "AU"], "uk": [c for c in companies if country_of(c) == "UK"]}
    skipped = [c for c in companies if country_of(c) not in ("AU", "UK")]
    log(f"Filings: {len(groups['au'])} AU, {len(groups['uk'])} UK companies; {len(skipped)} other or unknown country (not covered)")
    for reg in registers:
        cs = groups.get(reg, [])
        if not cs:
            continue
        log(f"{reg.upper()} registers:")
        res = (check_au if reg == "au" else check_uk)(cs, log)
        with store.lock, store.db:
            for cid, rec in res.items():
                store.db.execute("INSERT OR REPLACE INTO registry_records VALUES(?,?,?,?,?,?,?)",
                                 (cid, rec["register"], now, rec.get("status", ""), rec.get("acn") or rec.get("company_number") or rec.get("abn") or "",
                                  rec.get("matched_by", ""), json.dumps(rec, ensure_ascii=False)))
        found = sum(r.get("status") != "not found" for r in res.values())
        log(f"  {found}/{len(cs)} matched")


# ---------------------------------------------------------------- export
_INSOLVENT = re.compile(r"liquidat|administrat|receiver|voluntary arrangement|insolven|winding|external administration", re.I)
_STRUCK = re.compile(r"dissolved|deregistered|strike-?off|struck off|not active|cancelled", re.I)


def filing_rows(store, company_id, today, lookback_days=180):
    """(summary fields, events) from the latest register record(s) of a company."""
    ensure_tables(store)
    rows = store.db.execute("""SELECT register, checked_at, data FROM registry_records r WHERE company_id=? AND checked_at=
        (SELECT MAX(checked_at) FROM registry_records WHERE company_id=r.company_id AND register=r.register)""", (company_id,)).fetchall()
    if not rows:
        return {"filings_status": "not checked"}, []
    fields, events = {}, []
    since = (today - dt.timedelta(days=lookback_days)).isoformat()

    def ev(cat, date, title, url, reg):
        events.append({"signal_type": "filing", "category": cat, "published_at": date, "title": title, "publisher": reg, "url": url,
                       "source": "filings", "evidence": "company register"})

    for reg, checked, data in rows:
        rec = json.loads(data)
        if rec.get("status") == "not found":
            fields.setdefault("filings_status", f"not found in {reg}")
            continue
        fields["filings_status"] = f"found in {reg}"
        fields["registered_name"] = rec.get("name", "")
        fields["registration_id"] = rec.get("acn") or rec.get("company_number") or ""
        fields["abn"] = rec.get("abn", "")
        fields["registered_status"] = rec.get("status", "")
        fields["registered_on"] = rec.get("registered_on", "")
        live = [t["name"] for t in rec.get("trading_names", []) if t.get("status") == "Registered"]
        fields["trading_names"] = "; ".join(live[:8])
        if rec.get("accounts_category"):
            fields["uk_accounts"] = f"{rec['accounts_category']} (made up to {rec.get('accounts_made_up_to', '')})"
        if rec.get("sic"):
            fields["uk_sic"] = "; ".join(rec["sic"][:2])
        as_of = rec.get("as_of", checked[:10])
        as_of = f"{as_of[:4]}-{as_of[4:6]}-01" if re.fullmatch(r"\d{6}", as_of) else as_of
        url = (f"https://find-and-update.company-information.service.gov.uk/company/{rec['company_number']}" if rec.get("company_number")
               else f"https://abr.business.gov.au/ABN/View?abn={rec['abn']}" if rec.get("abn") else "")
        status = rec.get("status", "")
        if _INSOLVENT.search(status):
            ev("Insolvency / administration", as_of, f"{rec.get('name')}: {status} (register status as of {as_of})", url, reg)
        elif _STRUCK.search(status) or "proposal to strike off" in status.lower():
            # always flagged, however long ago: the company no longer exists (or is about to be struck off)
            date = rec.get("deregistered_on") or rec.get("dissolved_on") or as_of
            ev("Strike-off / deregistered", date, f"{rec.get('name')}: {status}" + (f" on {date}" if date != as_of else ""), url, reg)
        for f in rec.get("former_names", []):
            if f.get("changed_on") and f["changed_on"] >= since:
                ev("Name change", f["changed_on"], f"Name changed from {f['name']} to {rec.get('name')}", url, reg)
        new_names = defaultdict(list)
        for t in rec.get("trading_names", []):
            if t.get("registered_on") and t["registered_on"] >= since and t.get("status") == "Registered":
                new_names[t["registered_on"]].append(t["name"])
        for day, names in sorted(new_names.items()):
            ev("New trading name", day, f"Business name{'s' if len(names) > 1 else ''} registered: {'; '.join(names)}", url, reg)
        if rec.get("registered_on") and rec["registered_on"] >= since:
            ev("Newly registered", rec["registered_on"], f"{rec.get('name')} registered", url, reg)
        for n in rec.get("gazette", []):
            if n.get("published") and n["published"] >= since:
                ev("Insolvency / administration", n["published"], f"Gazette: {n['title']}", n.get("url", ""), "The Gazette")
    if events:
        sev = {c: i for i, c in enumerate(FILING_CATEGORIES)}
        top = sorted(events, key=lambda e: (sev.get(e["category"], 99), e["published_at"]), reverse=False)[0]
        fields["filing_signal"], fields["filing_signal_date"] = top["category"], top["published_at"]
    else:
        fields["filing_signal"] = "None" if fields.get("filings_status", "").startswith("found") else ""
    return fields, events


def identity_names(store, company_id):
    """Registered and trading names, to use as identity evidence when matching news."""
    ensure_tables(store)
    out = []
    for (data,) in store.db.execute("SELECT data FROM registry_records WHERE company_id=? ORDER BY checked_at DESC LIMIT 2", (company_id,)):
        rec = json.loads(data)
        out += [rec.get("name", "")] + [t["name"] for t in rec.get("trading_names", []) if t.get("status") == "Registered"]
    return [n for n in dict.fromkeys(n.strip() for n in out) if n]
