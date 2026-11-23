"""Who owns each Apollo lead: owner-managed, part of a group, investor-backed, charity or public body.

Why: BDMs prefer companies that are not owned by a parent, an umbrella group or an investor and that do not depend on
public money: fewer layers of sign-off and a faster buying decision (BDM feedback, 23 Nov 2026). This flags each lead;
it adds no points.

Sources (all free, no key, Open Government Licence):
  Companies House "People with significant control" (PSC) snapshot, daily, ~33 zip files / 2.6 GB
      (https://download.companieshouse.gov.uk/en_pscdata.html). Every UK company must name who controls it: people,
      other companies ("corporate entity") or bodies such as councils ("legal person"). Following the company owners
      up the chain gives the ultimate owner and, from the same file, how many companies that owner controls.
  Companies House "Free Company Data Product" (already cached by `news_scraper filings`): company type (limited by
      guarantee, community interest company ...), status and name of every company in the chain.
  CQC register (cqc.py's cached file): the provider's charity number and type (local authority, NHS, independent).

Company numbers per lead, strongest first: the filings run's Companies House match, the CQC providers matched by
company number or website (care groups often run homes through several companies), and, for leads with neither, the
"Company No." printed on the lead's own website (home, privacy, terms or contact page), checked against the register.

Ownership (one per lead, the first that applies, across all its companies):
  Public body              a council, NHS body or government department in the chain, or CQC provider type
  Charity / not-for-profit CQC charity number, a guarantee / community interest / society company type, or a
                           charity in the chain
  Investor-backed          a limited partnership or an investment vehicle name (Bidco, Topco, Capital, Equity,
                           Partners LLP, Fund ...) in the chain
  Part of a corporate group the ultimate owner is a company with no individual behind it in the register (overseas,
                           listed, or not identified)
  Owner-managed group      individuals at the top, but their holding company controls more than GROUP_MAX companies
  Owner-managed            individuals at the top, directly or through a small holding company
  Unknown                  no company number, or the register names no one (a statement only)

Writes apollo_emea/out/ownership.csv (one row per lead). Grade_leads adds Apollo's parent, the CQC brand and PE
buyout news as cross-checks.

Usage (from the News Scraper folder):
  ../.venv/Scripts/python.exe apollo_emea/ownership.py [--download] [--no-web]
--download fetches the newest PSC snapshot when Companies House has published a newer one (otherwise the cached one is
used). The first read of a snapshot takes ~10 minutes (two passes); later runs reuse a per-snapshot cache.
"""
import argparse
import csv
import datetime as dt
import glob
import io
import json
import os
import pickle
import re
import sqlite3
import sys
import zipfile
from collections import defaultdict

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "reference_code"))
from company_keys import name_key           # noqa: E402
from news_scraper import http               # noqa: E402
from news_scraper.names import root_domain  # noqa: E402

REG_DIR = os.path.join(ROOT, "data", "registers")
PSC_DIR = os.path.join(REG_DIR, "psc")
PSC_PAGE = "https://download.companieshouse.gov.uk/en_pscdata.html"
CQC_DIR = os.path.join(REG_DIR, "cqc")
WEB_CACHE = os.path.join(HERE, "data", "web_company_numbers.json")
CHARITY_DIR = os.path.join(REG_DIR, "charity")
CHARITY_URL = "https://ccewuksprdoneregsadata1.blob.core.windows.net/data/txt/publicextract.charity.zip"
CQC_NUMBER_BASIS = ("company number", "website")   # CQC matches trusted for company numbers (not name-only matches)
GROUP_MAX = 5            # an owner-managed holding company controlling more companies than this is a "group"
MAX_DEPTH = 8

UK_PLACE = re.compile(r"england|wales|scotland|united kingdom|\bu\.?k\.?\b|\bgbr?\b|britain|northern ireland|companies house|cardiff|"
                      r"edinburgh|belfast|companies act|registrar of companies", re.I)
UK_NUMBER = re.compile(r"^(\d{8}|(SC|NI|OC|SO|NC|IP|RS|FC|LP|SL|NL|CE|CS|SP|SR|NP|NR|R0|GE|ZC|SZ|SA|NA|IC)\d{6})$")
PUBLIC_STRICT = re.compile(r"\b(council|nhs|secretary of state|government|local authority)\b", re.I)   # in a company's name
PUBLIC = re.compile(r"\b(council|local authority|borough|county|metropolitan|combined authority|government|secretary of state|"
                    r"nhs|national health|health board|crown|ministry|department (of|for)|public (body|authority|sector)|"
                    r"statutory|university)\b", re.I)
CHARITY = re.compile(r"charit|\bfoundation\b|\bcio\b|community interest|housing association|registered society|"
                     r"community benefit|not[- ]for[- ]profit|non[- ]profit|friendly society", re.I)
INVESTOR = re.compile(r"\b(bidco|topco|midco|private equity|capital (partners|llp|lp|fund|advis[eo]rs|management|investments?)|"
                      r"equity|partners llp|fund|funds|ventures?|l\.?p\.?|limited partnership|general partner|gp (ltd|limited)|"
                      r"investment partners|tactical opportunities|opportunities fund|asset management|investment management)\b", re.I)
INVESTOR_FORM = re.compile(r"limited partnership|\blp\b|investment (trust|company)|fund", re.I)
NOT_FOR_PROFIT_TYPE = re.compile(r"guarantee|community interest|charitable|registered society|industrial and provident|"
                                 r"royal charter|friendly society|scottish charitable", re.I)
STATEMENT_TEXT = {
    "no-individual-or-entity-with-signficant-control": "the company says no person or company controls it",
    "no-individual-or-entity-with-significant-control": "the company says no person or company controls it",
    "psc-exists-but-not-identified": "a controller exists but is not identified",
    "psc-details-not-confirmed": "controller details not confirmed",
    "steps-to-find-psc-not-yet-completed": "the company has not finished identifying its controllers",
}
FOOTER = [re.compile(r"(?:company|registration|registered|reg\.?|co\.?)\s*(?:no\.?|number|num\.?|#)\s*[:.\-]?\s*"
                     r"((?:SC|NI|OC|SO|NC|IP|RS|FC)?\s?\d{6,8})\b", re.I),
          re.compile(r"registered in (?:england|scotland|wales|england (?:and|&) wales|the uk|northern ireland)[^0-9]{0,40}?"
                     r"((?:SC|NI|OC)?\d{6,8})\b", re.I)]
FOOTER_PATHS = ["", "privacy-policy", "privacy", "terms", "terms-and-conditions", "contact", "contact-us", "about", "legal",
                "cookie-policy"]


def ch_number(v):
    v = re.sub(r"[^A-Za-z0-9]", "", str(v or "")).upper()
    if v.isdigit():
        return v.zfill(8) if len(v) <= 8 else ""
    m = re.match(r"^([A-Z]{2})(\d{1,6})$", v)
    return m.group(1) + m.group(2).zfill(6) if m else v


# ---------------------------------------------------------------- PSC snapshot files
def psc_files(download):
    have = sorted(glob.glob(os.path.join(PSC_DIR, "psc-snapshot-*.zip")))
    if download:
        html = http.get(PSC_PAGE, interval=1.0).text
        names = sorted(set(re.findall(r"psc-snapshot-\d{4}-\d{2}-\d{2}_\d+of\d+\.zip", html)))
        os.makedirs(PSC_DIR, exist_ok=True)
        for n in names:
            path = os.path.join(PSC_DIR, n)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                continue
            print(f"  downloading {n} …", flush=True)
            with requests.get(PSC_PAGE.rsplit("/", 1)[0] + "/" + n, stream=True, timeout=300, headers={"User-Agent": http.UA}) as r:
                r.raise_for_status()
                with open(path + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(path + ".part", path)
        date = re.search(r"\d{4}-\d{2}-\d{2}", names[0]).group(0)
        for old in have:                                   # keep only the newest snapshot
            if date not in old:
                os.remove(old)
        have = sorted(glob.glob(os.path.join(PSC_DIR, f"psc-snapshot-{date}_*.zip")))
    if not have:
        sys.exit(f"no PSC snapshot in {PSC_DIR}: run with --download")
    dates = {re.search(r"\d{4}-\d{2}-\d{2}", p).group(0) for p in have}
    date = max(dates)
    files = [p for p in have if date in p]
    total = int(re.search(r"of(\d+)\.zip", files[0]).group(1))
    if len(files) != total:
        sys.exit(f"PSC snapshot {date} is incomplete ({len(files)} of {total} files): run with --download")
    return date, files


def psc_lines(files):
    for i, p in enumerate(files, 1):
        print(f"  reading {os.path.basename(p)} ({i}/{len(files)})", flush=True)
        with zipfile.ZipFile(p) as z:
            with z.open(z.namelist()[0]) as f:
                for line in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
                    yield line


def _num(line):
    return line[19:line.find('"', 19)]


def owner_of(d):
    """One active corporate / legal-person PSC record -> a compact owner dict."""
    ident = d.get("identification") or {}
    reg = ch_number(ident.get("registration_number"))
    place = " ".join(str(ident.get(k) or "") for k in ("country_registered", "place_registered", "legal_authority"))
    foreign = bool(ident.get("country_registered")) and not UK_PLACE.search(str(ident.get("country_registered")))
    uk = bool(UK_NUMBER.match(reg)) and not foreign and (bool(UK_PLACE.search(place)) or not place.strip())
    kind = "legal person" if d.get("kind", "").startswith("legal-person") else "company"
    return ((d.get("name") or "").strip(), kind, uk, reg if uk else "", (ident.get("legal_form") or "").strip(),
            str(ident.get("country_registered") or ident.get("place_registered") or "").strip())


OWNER_FIELDS = ("name", "kind", "uk", "reg", "form", "place")   # owners are kept as tuples: pass 1 holds the whole register


def od(t):
    return dict(zip(OWNER_FIELDS, t))


def is_foreign(o):
    return bool(o["place"]) and not UK_PLACE.search(o["place"])


def resolve_by_name(lead_nums, owners, cache):
    """Company owners filed without a usable number but not as foreign ("Anvil Group Limited", country England, no
    number): find the number by exact registered name in the basic company data, and patch the graph. Repeated per
    level of the chain. {name key: number} cached per snapshot."""
    found = {}
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            found = json.load(f)
    tried = set(found)
    for _ in range(MAX_DEPTH):
        todo = set()
        for n in lead_nums:
            for p in chain_of(n, owners):
                for o in p:
                    if o["kind"] == "company" and not o["uk"] and not is_foreign(o) and name_key(o["name"]) not in tried:
                        todo.add(name_key(o["name"]))
        if not todo:
            break
        print(f"Owners without a company number: looking up {len(todo)} names", flush=True)
        found.update(numbers_by_name(todo))
        tried |= todo
        for k in todo:
            found.setdefault(k, None)
        for n, ups in owners.items():                      # patch every owner tuple whose name is now resolved
            if any(not t[2] and found.get(name_key(t[0])) for t in ups):
                owners[n] = [(t[0], t[1], True, found[name_key(t[0])], t[4], t[5]) if not t[2] and t[1] == "company"
                             and found.get(name_key(t[0])) and not is_foreign(od(t)) else t for t in ups]
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(found, f)
    for n, ups in owners.items():                          # a second run starts from the unpatched pickle: patch again
        if any(not t[2] and found.get(name_key(t[0])) for t in ups):
            owners[n] = [(t[0], t[1], True, found[name_key(t[0])], t[4], t[5]) if not t[2] and t[1] == "company"
                         and found.get(name_key(t[0])) and not is_foreign(od(t)) else t for t in ups]
    return owners


def numbers_by_name(keys):
    """{name key: company number} for exact registered names (active companies first)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(REG_DIR, "BasicCompanyData-*.zip"))):
        with zipfile.ZipFile(p) as z:
            with z.open(z.namelist()[0]) as f:
                rd = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline=""))
                h = [x.strip() for x in next(rd)]
                i_name, i_num, i_stat = h.index("CompanyName"), h.index("CompanyNumber"), h.index("CompanyStatus")
                for row in rd:
                    if len(row) > i_stat:
                        k = name_key(row[i_name])
                        if k in keys and (k not in out or row[i_stat].strip() == "Active"):
                            out[k] = row[i_num].strip()
    return out


def owner_key(o):
    o = o if isinstance(o, dict) else od(o)
    return ("uk", o["reg"]) if o["uk"] else ("nm", name_key(o["name"]))


def build_graph(files, cache):
    """Pass 1 over the snapshot: every active company owner. {company: [owners]} and {owner key: [companies]}."""
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)
    print("PSC pass 1: company-to-company ownership (whole register)", flush=True)
    owners, children = defaultdict(list), defaultdict(list)
    for line in psc_lines(files):
        if ('"kind":"corporate-entity-person' not in line and '"kind":"legal-person-person' not in line) or '"ceased_on"' in line:
            continue
        d = json.loads(line)
        o = owner_of(d["data"])
        owners[d["company_number"]].append(o)
        children[owner_key(o)].append(d["company_number"])
    g = (dict(owners), dict(children))
    with open(cache, "wb") as f:
        pickle.dump(g, f, protocol=pickle.HIGHEST_PROTOCOL)
    return g


def read_records(files, wanted, cache):
    """Pass 2: every active PSC record (people, companies, statements) of the wanted companies. Cached per snapshot."""
    have = {}
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            have = json.load(f)
    missing = set(wanted) - set(have)
    if missing:
        print(f"PSC pass 2: records of {len(missing)} companies", flush=True)
        got = {n: [] for n in missing}
        for line in psc_lines(files):
            n = _num(line)
            if n in got and '"ceased_on"' not in line and '"ceased":true' not in line:
                got[n].append(json.loads(line)["data"])
        have.update(got)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(have, f)
    return {n: have.get(n, []) for n in wanted}


# ---------------------------------------------------------------- basic company data (cached by the filings run)
def company_data(numbers):
    """{number: {name, status, type, accounts}} from the cached Free Company Data Product."""
    parts = sorted(glob.glob(os.path.join(REG_DIR, "BasicCompanyData-*.zip")))
    if not parts:
        print("  no Companies House basic data cached: run `news_scraper filings` first; company types will be blank")
        return {}
    want, out = set(numbers), {}
    print(f"Companies House basic data: {len(want)} companies", flush=True)
    for p in parts:
        with zipfile.ZipFile(p) as z:
            with z.open(z.namelist()[0]) as f:
                rd = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline=""))
                h = [x.strip() for x in next(rd)]
                i_num, i_name, i_stat, i_type, i_acc = (h.index(k) for k in ("CompanyNumber", "CompanyName", "CompanyStatus",
                                                                              "CompanyCategory", "Accounts.AccountCategory"))
                for row in rd:
                    if len(row) > i_acc and row[i_num].strip() in want:
                        out[row[i_num].strip()] = {"name": row[i_name].strip(), "status": row[i_stat].strip(),
                                                   "type": row[i_type].strip(), "accounts": row[i_acc].strip()}
    return out


# ---------------------------------------------------------------- company numbers per lead
def registry_numbers(db):
    out = {}
    if os.path.exists(db):
        with sqlite3.connect(db) as c:
            for cid, num in c.execute("select company_id, reg_id from registry_records where register = 'Companies House' "
                                      "and reg_id != '' order by checked_at"):
                out[cid] = ch_number(num)
    return out


def cqc_info(cqc_csv):
    """{company_id: (basis, [company numbers], [provider ids])} and {provider id: (charity no, type/sector, ownership type)}."""
    leads, prov = {}, {}
    if not os.path.exists(cqc_csv):
        return leads, prov
    c = pd.read_csv(cqc_csv, dtype=str, keep_default_na=False)
    for r in c.itertuples():
        nums = [ch_number(x) for x in r.cqc_provider_numbers.split("; ") if x]
        leads[r.company_id] = (r.cqc_match, [n for n in nums if n], [x for x in r.cqc_provider_ids.split("; ") if x])
    files = sorted(glob.glob(os.path.join(CQC_DIR, "*_HSCA_Active_Locations.csv")), key=os.path.getmtime)
    if files:
        loc = pd.read_csv(files[-1], dtype=str, keep_default_na=False,
                          usecols=["Provider ID", "Provider Charity Number", "Provider Type/Sector", "Provider Ownership Type"])
        for r in loc.drop_duplicates("Provider ID").itertuples(index=False):
            prov[r[0]] = (r[1].strip(), r[2].strip(), r[3].strip())
    return leads, prov


def charity_register(download):
    """Charity Commission register of charities (England & Wales), daily full extract (free, no key, ~45 MB zip), main
    charities only (not linked subsidiaries). {by_company: {company no: rec}, by_regno: {...}, by_web: {domain: rec}}."""
    path = os.path.join(CHARITY_DIR, "publicextract.charity.zip")
    if download or not os.path.exists(path):
        os.makedirs(CHARITY_DIR, exist_ok=True)
        print("  downloading the Charity Commission register …", flush=True)
        with requests.get(CHARITY_URL, stream=True, timeout=300, headers={"User-Agent": http.UA}) as r:
            r.raise_for_status()
            with open(path + ".part", "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(path + ".part", path)
    out = {"by_company": {}, "by_regno": {}, "by_web": {}}
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as f:
            rd = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline=""), delimiter="\t",
                            quoting=csv.QUOTE_NONE)
            h = next(rd)
            ix = {k: h.index(k) for k in ("registered_charity_number", "linked_charity_number", "charity_name",
                                          "charity_registration_status", "latest_income", "charity_contact_web",
                                          "charity_company_registration_number")}
            for row in rd:
                if len(row) <= max(ix.values()) or row[ix["linked_charity_number"]] != "0":
                    continue
                rec = {"regno": row[ix["registered_charity_number"]], "name": row[ix["charity_name"]].strip(),
                       "status": row[ix["charity_registration_status"]], "income": row[ix["latest_income"]]}
                better = lambda d, k: k not in d or (rec["status"] == "Registered" and d[k]["status"] != "Registered")
                co = ch_number(row[ix["charity_company_registration_number"]])
                if co and co != "00000000" and better(out["by_company"], co):
                    out["by_company"][co] = rec
                if better(out["by_regno"], rec["regno"]):
                    out["by_regno"][rec["regno"]] = rec
                try:                                       # the register's web field is free text ("[www.x.org]", emails)
                    web = root_domain(row[ix["charity_contact_web"]].strip()) if row[ix["charity_contact_web"]].strip() else ""
                except ValueError:
                    web = ""
                if web and "." in web and better(out["by_web"], web):
                    out["by_web"][web] = rec
    print(f"Charity Commission register: {len(out['by_regno'])} charities", flush=True)
    return out


def _text(html):
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def website_numbers(leads, skip):
    """{company_id: (number, page)}: 'Company No. 01234567' printed on the lead's own website. Cached; misses too."""
    cache = {}
    if os.path.exists(WEB_CACHE):
        with open(WEB_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    todo = [r for r in leads.itertuples() if r.company_id not in skip and r.website and r.company_id not in cache]
    if todo:
        print(f"Website footers: {len(todo)} sites", flush=True)
    for r in todo:
        found = None
        for path in FOOTER_PATHS:
            url = f"https://{r.website.strip('/')}/{path}"
            try:
                t = _text(http.get(url, interval=1.0, retries=1, timeout=15).text)
            except Exception:                              # noqa: BLE001 - a missing page is normal
                continue
            ms = [m for rx in FOOTER for m in rx.finditer(t)
                  if not re.search(r"charit|vat", t[max(0, m.start() - 25):m.start()], re.I)]   # not a charity / VAT number
            if ms:
                found = [ch_number(ms[0].group(1)), url]
                break
        cache[r.company_id] = found
        with open(WEB_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1)
    return {k: tuple(v) for k, v in cache.items() if v}


# ---------------------------------------------------------------- classify
def chain_of(number, owners, depth=0, seen=None):
    """Paths from a company up to its top owners: list of lists of owner dicts (empty list = no company owner)."""
    seen = (seen or set()) | {number}
    ups = [od(t) for t in owners.get(number, [])]
    if not ups or depth >= MAX_DEPTH:
        return [[]]
    paths = []
    for o in ups:
        if o["uk"] and o["reg"] not in seen:
            for p in chain_of(o["reg"], owners, depth + 1, seen):
                paths.append([o] + p)
        else:
            paths.append([o])
    return paths


def descendants(o, children, cap=2000):
    """Companies an owner controls, directly or below. Seeds with its number and its name (filings without a number)."""
    todo, seen = [("uk", o["reg"])] * bool(o["uk"]) + [("nm", name_key(o["name"]))], set()
    while todo and len(seen) < cap:
        k = todo.pop()
        for c in children.get(k, []):
            if c not in seen:
                seen.add(c)
                todo.append(("uk", c))
    return seen


def individuals(recs):
    return [r for r in recs if r.get("kind", "").startswith("individual")]


def statements(recs):
    return [STATEMENT_TEXT.get(r.get("statement"), r.get("statement", "").replace("-", " "))
            for r in recs if r.get("kind", "").endswith("statement")]


def assess(number, owners, children, recs, basic):
    """Ownership of one company: class, evidence, chain text, top owner, group size."""
    paths = chain_of(number, owners)
    nodes = [o for p in paths for o in p]
    tops = []                                              # (top owner dict or None, its individuals, its statements)
    for p in paths:
        top_num = p[-1]["reg"] if p and p[-1]["uk"] else (number if not p else None)
        top = p[-1] if p else None
        r = recs.get(top_num, []) if top_num else []
        tops.append((top, individuals(r), statements(r), top_num))
    own_recs = recs.get(number, [])
    indiv_here = individuals(own_recs)
    types = [basic.get(n, {}).get("type", "") for n in [number] + [o["reg"] for o in nodes if o["uk"]]]
    texts = [f"{o['name']} {o['form']}" for o in nodes]
    group = max([len(descendants(t, children)) for t, *_ in tops if t] + [1])
    chain_txt = " | ".join(" ← ".join([o["name"] + ("" if o["uk"] else f" ({o['place'] or 'overseas'})") for o in p]
                                        + ([f"{len(t[1])} individual(s)"] if t[1] else [])) for p, t in zip(paths, tops) if p)
    # the same chain as data, for links: each step's company number (UK) or country (overseas); the people at the top
    # are a count, linked to the ownership page of the company they control
    steps = [[{"name": o["name"], "number": o["reg"] if o["uk"] else "", "place": "" if o["uk"] else (o["place"] or ("legal body" if o["kind"] == "legal person" else "no number filed"))}
              for o in p] + ([{"name": f"{len(t[1])} individual(s)", "number": t[3] or "", "people": True}] if t[1] else [])
             for p, t in zip(paths, tops) if p]
    top_names = "; ".join(sorted({t["name"] for t, *_ in tops if t}))
    ev = []
    if any(PUBLIC_STRICT.search(o["name"]) for o in nodes) or \
            any(o["kind"] == "legal person" and PUBLIC.search(o["form"] + " " + o["name"]) for o in nodes):
        cls = "Public body"; ev.append(f"public body in the chain ({top_names})")
    elif any(NOT_FOR_PROFIT_TYPE.search(t) for t in types if t):
        cls = "Charity / not-for-profit"
        ev.append(next(f"company type: {t}" for t in types if t and NOT_FOR_PROFIT_TYPE.search(t)))
    elif any(INVESTOR.search(o["name"]) or INVESTOR_FORM.search(o["form"]) for o in nodes):   # before charity names:
        inv = next(o for o in nodes if INVESTOR.search(o["name"]) or INVESTOR_FORM.search(o["form"]))   # "Foundation Investment Partners"
        cls = "Investor-backed"; ev.append(f"investment vehicle in the chain: {inv['name']}" + (f" ({inv['form']})" if inv["form"] else ""))
    elif any(CHARITY.search(x) for x in texts):
        cls = "Charity / not-for-profit"; ev.append(f"charity in the chain ({top_names})")
    elif nodes and group <= GROUP_MAX and all(t is not None and t["uk"] and not ind and not re.search(r"\bplc\b", t["name"], re.I)
                                             for t, ind, *_ in tops if t is not None and not ind) \
            and not any(ind for _, ind, *_ in tops) and any(t is not None for t, *_ in tops):
        # a small UK holding company naming no one: nobody holds 25%+ (a family with several shareholders, or many
        # investors). Not evidence of a corporate group either way
        cls = "Unknown"
        ev.append(f"held through {top_names}, which names no 25%+ owner (several shareholders, family or investors)")
    elif nodes and any(t is not None and not ind for t, ind, *_ in tops):
        cls = "Part of a corporate group"
        why = []
        for t, ind, st, tn in tops:
            if t is not None and not ind:
                why.append(f"{t['name']}: " + (f"overseas company ({t['place']})" if is_foreign(t)
                                               else "UK company, number not filed and not found by name" if not t["uk"]
                                               else st[0] if st else "no individual named"))
        ev.append("top owner " + "; ".join(sorted(set(why))))
    elif nodes:
        n_ind = sum(len(ind) for _, ind, *_ in tops)
        cls = "Owner-managed group" if group > GROUP_MAX else "Owner-managed"
        ev.append(f"{n_ind} individual(s) own it through {top_names}" + (f", which controls {group} companies" if group > 1 else ""))
    elif indiv_here:
        cls = "Owner-managed"; ev.append(f"{len(indiv_here)} individual(s) control it directly")
    elif statements(own_recs):
        cls = "Unknown"; ev.append("register: " + statements(own_recs)[0])
    else:
        cls = "Unknown"; ev.append("no controller filed in the register")
    people = sorted({r.get("name", "") for _, ind, *_ in tops for r in ind} | {r.get("name", "") for r in indiv_here} - {""})
    return {"class": cls, "evidence": "; ".join(ev), "chain": chain_txt, "steps": steps, "top_owner": top_names, "group_companies": group,
            "owners_named": "; ".join(people), "depth": max(len(p) for p in paths)}


RANK = ["Public body", "Charity / not-for-profit", "Investor-backed", "Part of a corporate group", "Owner-managed group",
        "Owner-managed", "Unknown"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--companies", default=os.path.join(HERE, "data", "companies.csv"))
    ap.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    ap.add_argument("--cqc", default=os.path.join(HERE, "out", "cqc_providers.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--no-web", action="store_true", help="skip reading company numbers from websites")
    a = ap.parse_args(argv)

    leads = pd.read_csv(a.companies, dtype=str, keep_default_na=False)
    reg = registry_numbers(a.db)
    cqc_leads, cqc_prov = cqc_info(a.cqc)
    nums = {}                                              # company_id -> [(number, source)]
    for cid in leads["company_id"]:
        got = []
        if reg.get(cid):
            got.append((reg[cid], "Companies House name match"))
        basis, cnums, _ = cqc_leads.get(cid, ("", [], []))
        if basis.startswith(CQC_NUMBER_BASIS):
            got += [(n, "CQC provider") for n in cnums if n not in {g[0] for g in got}]
        nums[cid] = got
    web = {} if a.no_web else website_numbers(leads, {c for c, g in nums.items() if g})

    date, files = psc_files(a.download)
    owners, children = build_graph(files, os.path.join(PSC_DIR, f"graph-{date}.pkl"))
    web_ok = {}
    basic_web = company_data({n for n, _ in web.values()})
    for cid, (n, url) in web.items():
        lead = leads.set_index("company_id").loc[cid]
        words = {w for w in name_key(lead["company_name"]).split() + re.split(r"[.\-]", lead["website"].lower())[:1] if len(w) > 3}
        reg_name = name_key(basic_web.get(n, {}).get("name", ""))
        if reg_name and any(w in reg_name.replace(" ", "") for w in words):
            # a number not in the register, or registered to an unrelated name, is a misread
            nums[cid].append((n, f"website ({url})"))
            web_ok[cid] = basic_web[n]["name"]
    lead_nums = {n for g in nums.values() for n, _ in g}
    owners = resolve_by_name(lead_nums, owners, os.path.join(PSC_DIR, f"names-{date}.json"))
    chain_nums = set()
    for n in lead_nums:
        for p in chain_of(n, owners):
            chain_nums |= {o["reg"] for o in p if o["uk"]}
    recs = read_records(files, sorted(lead_nums | chain_nums), os.path.join(PSC_DIR, f"records-{date}.json"))
    basic = {**basic_web, **company_data((lead_nums | chain_nums) - set(basic_web))}

    cc_reg = charity_register(a.download)
    rows = []
    for r in leads.itertuples():
        got = nums[r.company_id]
        _, _, pids = cqc_leads.get(r.company_id, ("", [], []))
        charity = "; ".join(sorted({cqc_prov[p][0] for p in pids if p in cqc_prov and cqc_prov[p][0]}))
        sector = "; ".join(sorted({cqc_prov[p][1] for p in pids if p in cqc_prov and cqc_prov[p][1]}))
        res = [(n, src, assess(n, owners, children, recs, basic)) for n, src in got]
        if res:
            n, src, best = min(res, key=lambda x: RANK.index(x[2]["class"]) if x[2]["class"] != "Unknown" else 99)
        else:
            n, src, best = "", "", {"class": "Unknown", "evidence": "no company number found", "chain": "", "steps": [], "top_owner": "",
                                    "group_companies": None, "owners_named": "", "depth": 0}
        cls, ev = best["class"], [best["evidence"]]
        if sector and re.search(r"local authority|nhs", sector, re.I):
            cls, ev = "Public body", [f"CQC provider type: {sector}"] + ev
        elif charity and RANK.index(cls) > RANK.index("Charity / not-for-profit"):
            cls, ev = "Charity / not-for-profit", [f"CQC charity number {charity}"] + ev
        # Charity Commission (England & Wales): the lead's companies, its owners up the chain, its CQC charity number,
        # then its website. A registered charity confirms the flag and gives a charity number and page
        chain_regs = [s["number"] for p in best["steps"] for s in p if s.get("number") and not s.get("people")]
        cc, cc_how = None, ""
        for num, how in [(x, "company number") for x, _ in got] + [(x, "owner company number") for x in chain_regs]:
            if num in cc_reg["by_company"]:
                cc, cc_how = cc_reg["by_company"][num], how; break
        if cc is None:
            for regno in [x.strip() for x in charity.split(";") if x.strip()]:
                if regno in cc_reg["by_regno"]:
                    cc, cc_how = cc_reg["by_regno"][regno], "CQC charity number"; break
        if cc is None and r.website and root_domain(r.website) in cc_reg["by_web"]:
            cc, cc_how = cc_reg["by_web"][root_domain(r.website)], "website"
        charity_note = ""
        if cc is not None and cc["status"] == "Registered" and cc_how == "website" and cls not in ("Unknown", "Charity / not-for-profit"):
            # a shared website is weaker than the ownership register (Ablecare Homes Ltd, owned by individuals, shares
            # its site with a small "Ablecare Homes Trust"): keep the register's answer, flag it for a person
            charity_note = f"its website is also listed by registered charity {cc['regno']} ({cc['name']}): check which runs the homes"
        elif cc is not None and cc["status"] == "Registered":
            note = f"registered charity {cc['regno']} ({cc['name']}, matched by {cc_how}, Charity Commission)"
            if RANK.index(cls) > RANK.index("Charity / not-for-profit"):
                cls, ev = "Charity / not-for-profit", [note] + ev
            elif cls == "Charity / not-for-profit":
                ev = [note] + ev
        elif cls == "Charity / not-for-profit" and cc_reg["by_company"]:
            ev.append("not on the Charity Commission register for England & Wales (a not-for-profit company, or a "
                      "Scottish / Northern Irish charity)")
        if len(got) > 1:
            ev.append(f"{len(got)} companies checked")
        rows.append({
            "charity_number": cc["regno"] if cc else "", "charity_name": cc["name"] if cc else "",
            "charity_status": cc["status"] if cc else "", "charity_income": cc["income"] if cc else "",
            "charity_match": cc_how if cc else "", "charity_note": charity_note,
            "company_id": r.company_id, "ownership": cls, "ownership_evidence": "; ".join(ev),
            "ownership_number": n, "ownership_number_source": src.split(" (")[0] if src else "",
            "ownership_number_name": basic.get(n, {}).get("name", ""), "company_numbers": "; ".join(x for x, _ in got),
            "company_type": basic.get(n, {}).get("type", ""), "owner_chain": best["chain"],
            "owner_chain_steps": json.dumps(best["steps"], ensure_ascii=False) if best["steps"] else "", "top_owner": best["top_owner"],
            "group_companies": best["group_companies"], "owners_named": best["owners_named"], "chain_depth": best["depth"],
            "cqc_charity_number": charity, "cqc_provider_sector": sector, "website_number_page": web.get(r.company_id, ("", ""))[1]
            if r.company_id in web_ok else "", "psc_snapshot": date,
        })
    out = pd.DataFrame(rows)
    os.makedirs(a.out, exist_ok=True)
    out.to_csv(os.path.join(a.out, "ownership.csv"), index=False)
    print(f"\nownership.csv: {len(out)} leads (PSC snapshot {date})")
    print(out["ownership"].value_counts().to_string())
    print("company number from:", out["ownership_number_source"].replace("", "none").value_counts().to_dict())


if __name__ == "__main__":
    main()
