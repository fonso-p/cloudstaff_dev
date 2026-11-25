"""Industry trends for the EMEA Lead Grades dashboard (its "Industry trends" page): every UK company, by MyStaff industry group.

Two free Companies House files, both already downloaded by the News Scraper (News Scraper/data/registers/):
  BasicCompanyData-<date>-part*.zip    every live company: status, incorporation date, SIC codes (monthly, `filings` run)
  psc/psc-snapshot-<date>_*of33.zip    who controls every company, incl. owners who have since left (daily, ownership.py)

What it measures, per industry group and for all UK companies, by quarter:
  new companies        incorporations of companies still on the register (dissolved ones have left the file: older
                       quarters undercount)
  controlled by a      share of companies whose register lists a company (not a person) holding a majority of shares or
  company              votes, or the right to appoint or remove most of the board. Rebuilt for past quarters from each
                       owner's notified_on / ceased_on dates
  takeovers            a company over a year old gaining such a company owner. "First company owner" = it had none just
                       before (the consolidation signal); "changed company owner" = it passed from one company to another
                       (sales between groups, and group restructures). A "group buyer" controls 3+ companies in the group
  status now           insolvency (liquidation, administration, CVA, receiver) and proposed strike-off, from the status field
and the most active buyers per group over the last 24 months (company owners only: no personal data).

Growth (net change in the number of companies, last 1 / 3 / 6 / 12 months), two sources:
  estimate (now)            UK totals from Companies House's official monthly statistics ("Incorporated companies in
                            the UK": incorporations, restorations, struck off by route, register size; quarterly
                            release, ~1 month lag, monthly figures since April 2026; cached in registers/ch_stats/).
                            Each industry's part is its share in our file: of companies incorporated in those months
                            (openings), of companies awaiting strike-off (voluntary and compulsory strike-offs), of
                            companies in liquidation (struck off after liquidation), of all companies (the rest)
  our monthly copies        each run keeps a small copy of the Companies House file (registers/ch_snapshots/); comparing
                            two copies counts companies opened and closed (closures can't be seen in a single file).
                            Run monthly with --download, which fetches the newest file first

Industry group: the company's first SIC code, through references/mystaff_industry/uk_sic_to_industry_group.csv (longest
prefix wins). Holding companies, dormant and non-trading companies have no group on purpose.

Writes <DATA_DIR>/industry_trends.json, which grade_leads.py embeds in the dashboard data (run this first). Totals and
company names only. The corporate owners pulled from the 2.6 GB snapshot are cached next to it
(psc/corporate-<date>.csv.gz), so a re-run takes ~1 minute.

Usage (repo root): .venv/Scripts/python.exe "Marketing Intelligence/apollo_lead_grading/industry_trends.py" [--download]
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "references" / "mystaff_industry"))
from mystaff_industry import GROUPS   # noqa: E402

REG = REPO / "News Scraper" / "data" / "registers"
CROSSWALK = REPO / "references" / "mystaff_industry" / "uk_sic_to_industry_group.csv"
DATA_DIR = Path.home() / "Desktop" / "Projects" / "Marketing Intelligence Priority" / "Data"
SNAP_DIR = REG / "ch_snapshots"
STATS_DIR = REG / "ch_stats"
GOVUK_SEARCH = "https://www.gov.uk/api/search.json"
# the official statistics count companies only: leave partnerships, overseas entities and the like out of the shares
DORMANT_COHORT = (24, 36)    # months old: companies that have filed first accounts, for the expected dormant share
HOLDING_NAME = re.compile(r"\b(?:HOLDINGS?|HOLDCO|TOPCO|MIDCO|BIDCO|GROUP|INVESTMENTS?)\b", re.I)
NOT_COMPANY = re.compile(r"Partnership|Overseas|Society|Charitable Incorporated|Further Education|Royal Charter|Other", re.I)
UK = "All UK companies"
FIRST_Q = "2018Q1"           # the register started in April 2016 and existing owners were filed into 2017: earlier
                             # quarters show the filing wave, not takeovers
GROUP_BUYER_MIN = 3          # controls 3+ companies in the group (ever, in this snapshot) = group buyer
TOP_BUYERS = 15
INSOLVENT = re.compile(r"Liquidation|Administration|Voluntary Arrangement|Receiver", re.I)
MAJORITY = re.compile(r"(?:shares|voting-rights|surplus-assets)-(?:50-to-75|75-to-100|more-than-50)|right-to-appoint-and-remove-(?:directors|members|person)")


def load_crosswalk():
    cw = pd.read_csv(CROSSWALK, dtype=str).fillna("")
    bad = set(cw.industry_group) - set(GROUPS) - {""}
    missing = set(GROUPS) - set(cw.industry_group)
    if bad or missing:
        raise SystemExit(f"{CROSSWALK.name} is out of step with mystaff_industry: unknown {bad or '-'}, no codes for {missing or '-'}")
    return cw


def map_sic(sic, cw):
    """5-digit SIC -> (group or '', crosswalk prefix). Longest prefix wins."""
    pre = sorted(cw.itertuples(), key=lambda r: -len(r.sic_prefix))
    cache = {}
    def one(s):
        if s not in cache:
            hit = next((r for r in pre if s.startswith(r.sic_prefix)), None)
            cache[s] = (hit.industry_group, hit.sic_prefix) if hit else ("", "")
        return cache[s]
    out = [one(s) for s in sic]
    return [o[0] for o in out], [o[1] for o in out]


def read_companies(cw):
    parts = sorted(glob.glob(str(REG / "BasicCompanyData-*-part*.zip")))
    if not parts:
        raise SystemExit(f"no Companies House file in {REG}: run the News Scraper `filings` command first")
    as_of = re.search(r"(\d{4}-\d{2}-\d{2})", parts[0]).group(1)
    keep = {"CompanyName", "CompanyNumber", "CompanyStatus", "IncorporationDate", "SICCode.SicText_1", "CompanyCategory", "Accounts.AccountCategory"}
    frames = []
    for p in parts:
        with zipfile.ZipFile(p) as z:
            df = pd.read_csv(z.open(z.namelist()[0]), dtype=str, usecols=lambda c: c.strip() in keep, keep_default_na=False)
        df.columns = [c.strip() for c in df.columns]
        frames.append(df)
    co = pd.concat(frames, ignore_index=True)
    co["company"] = co.CompanyNumber.str.strip()
    co["sic"] = co["SICCode.SicText_1"].str.extract(r"^(\d{5})", expand=False).fillna("")
    co["group"], co["sic_prefix"] = map_sic(co.sic.tolist(), cw)
    co["inc"] = pd.to_datetime(co.IncorporationDate, format="%d/%m/%Y", errors="coerce")
    co["status"] = co.CompanyStatus.str.strip()
    co["name"] = co.CompanyName.str.strip()
    co["accounts"] = co["Accounts.AccountCategory"].str.strip().str.upper()
    return co[["company", "name", "sic", "group", "sic_prefix", "inc", "status", "CompanyCategory", "accounts"]], as_of


def mark_operating(co, ow_raw):
    """Operating company = where the work happens: a company (not a partnership or overseas entity, as in the official
    statistics) with a trading industry, not filing dormant accounts, and not a holding company in practice, i.e. a
    parent (controls another live company) whose name says so (Holdings, Holdco, Topco, Midco, Bidco, Group,
    Investments). Position in the ownership chain alone doesn't decide: trading parents and their subsidiaries both count.
    Holding companies that say so in their SIC code (642xx, 70100) have no industry already."""
    live = set(co.company)
    cur = ow_raw[ow_raw.control.str.contains(MAJORITY) & (ow_raw.ceased_on == "") & ow_raw.company.isin(live)]
    parents = {owner_key(a, b) for a, b in zip(cur.owner_name, cur.owner_number)} & live   # controls a live company now
    co = co.copy()
    co["is_company"] = ~co.CompanyCategory.str.contains(NOT_COMPANY, na=False)
    co["dormant"] = co.accounts.eq("DORMANT")
    co["parent"] = co.company.isin(parents)
    co["holding_name"] = co.parent & co.name.str.contains(HOLDING_NAME, na=False)
    co["op"] = co.is_company & co.group.ne("") & ~co.dormant & ~co.holding_name
    return co


# ---------------------------------------------------------------- monthly copies of the Companies House file
def download_ch(log=print):
    """Fetch the newest monthly Companies House file (same cache and rule as the News Scraper: only the newest kept)."""
    sys.path.insert(0, str(REPO / "News Scraper"))
    from news_scraper import registers
    parts = registers._ch_parts()
    if not parts:
        raise SystemExit("Companies House download page lists no files")
    as_of = re.search(r"(\d{4}-\d{2}-\d{2})", parts[0]).group(1)
    for old in os.listdir(REG):
        if old.startswith("BasicCompanyData") and as_of not in old:
            os.remove(REG / old)
    for name in parts:
        registers._download(registers.CH_BASE + name, name, log)
    return as_of


def save_snapshot(co, as_of):
    """A small copy of each monthly file (number, group, incorporation date, operating flag), kept so closures can be
    counted later. Rewritten while it is the current file, so it carries the latest rules; older copies stay as kept."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAP_DIR / f"companies-{as_of}.csv.gz"
    out = co[["company", "group"]].assign(inc=co.inc.dt.strftime("%Y-%m-%d"), op=co.op.astype(int))
    out.to_csv(path, index=False, compression="gzip")
    print(f"  kept a copy for the monthly comparison: {path.name}")
    return path


def monthly_flows():
    """Compare each pair of consecutive copies: companies that left = closed (dissolved, or rarely moved off the
    register); companies that appeared = opened (new, or restored to the register)."""
    snaps = sorted(SNAP_DIR.glob("companies-*.csv.gz"))
    flows, prev, prev_date = [], None, None
    for p in snaps:
        date = re.search(r"(\d{4}-\d{2}-\d{2})", p.name).group(1)
        cur = pd.read_csv(p, dtype=str, keep_default_na=False)
        if prev is not None:
            # operating companies only: closed = operating last month and gone now; opened = operating now and new
            # (a company turning dormant is neither)
            pop = prev[prev.op == "1"] if "op" in prev else prev
            cop = cur[cur.op == "1"] if "op" in cur else cur
            closed = pop[~pop.company.isin(set(cur.company))]
            opened = cop[~cop.company.isin(set(prev.company))]
            prev = pop
            start = prev.group.value_counts()
            o, c = opened.group.value_counts(), closed.group.value_counts()
            row = {"from": prev_date, "to": date, "groups": {UK: [int(len(prev)), int(len(opened)), int(len(closed))]}}
            for g in GROUPS:
                row["groups"][g] = [int(start.get(g, 0)), int(o.get(g, 0)), int(c.get(g, 0))]
            flows.append(row)
        prev, prev_date = cur, date
    return flows, [re.search(r"(\d{4}-\d{2}-\d{2})", p.name).group(1) for p in snaps]


# ---------------------------------------------------------------- Companies House official statistics (monthly totals)
def stats_files(download):
    """'Incorporated companies in the UK' releases (quarterly, monthly figures since April 2026). Each newer release is
    kept next to the older ones, so the monthly series grows; a later release wins for a month it repeats."""
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    if download or not any(STATS_DIR.glob("*.xlsx")):
        import requests
        ua = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(GOVUK_SEARCH, timeout=60, headers=ua, params={
            "filter_organisations": "companies-house", "filter_content_store_document_type": "official_statistics",
            "count": 20, "order": "-public_timestamp", "fields": "title,link"}).json()["results"]
        rel = next((r for r in res if r["title"].lower().startswith("incorporated companies in the uk")), None)
        if rel:
            att = requests.get("https://www.gov.uk/api/content" + rel["link"], timeout=60, headers=ua).json()["details"]["attachments"]
            url = next((a["url"] for a in att if str(a.get("url", "")).endswith(".xlsx")), None)
            path = STATS_DIR / url.rsplit("/", 1)[-1] if url else None
            if path and not path.exists():
                print(f"  downloading {path.name} …")
                r = requests.get(url, timeout=120, headers=ua)
                r.raise_for_status()
                path.write_bytes(r.content)
    files = sorted(STATS_DIR.glob("*.xlsx"), key=os.path.getmtime)
    if not files:
        raise SystemExit("no Companies House statistics release found: run with --download")
    return files


def _sheet_rows(wb, sheet):
    rows = list(wb[sheet].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and any(str(c).strip() == "Period" for c in r if c is not None))
    hdr = [str(c).strip() if c is not None else "" for c in rows[hi]]
    return [dict(zip(hdr, r)) for r in rows[hi + 1:] if r and r[0] is not None]


def read_stats(files):
    """{'YYYY-MM': {start, inc, restored, other_add, struck, other_rem, end, struck_liq}} for UK companies."""
    import openpyxl
    months, used = {}, []
    for path in files:                                   # oldest first, so a later release overwrites
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        if "Table 1" not in wb.sheetnames or "Table 3" not in wb.sheetnames:
            continue                                     # pre-April 2026 format: quarterly only
        col = lambda rec, start: next(v for k, v in rec.items() if k.lower().startswith(start))
        for rec in _sheet_rows(wb, "Table 1"):
            if rec.get("Geography") == "UK" and rec.get("Corporate body type") == "Company" and hasattr(rec.get("Period"), "strftime"):
                months[rec["Period"].strftime("%Y-%m")] = {
                    "start": int(col(rec, "total register size at start")), "inc": int(col(rec, "incorporations")),
                    "restored": int(col(rec, "restorations")), "other_add": int(col(rec, "other additions")),
                    "struck": int(col(rec, "struck off")), "other_rem": int(col(rec, "other removals")),
                    "end": int(col(rec, "total register size at end")), "struck_liq": 0}
        for rec in _sheet_rows(wb, "Table 3"):
            if rec.get("Geography") == "UK" and str(rec.get("Stage", "")).strip() == "Struck off" and str(rec.get("Route", "")).strip() == "Liquidation":
                m = rec["Period"].strftime("%Y-%m")
                if m in months:
                    months[m]["struck_liq"] = int(rec["Count"])
        used.append(path.name)
    for m, v in months.items():                          # the release says movements add up to the register change
        assert v["start"] + v["inc"] + v["restored"] + v["other_add"] - v["struck"] - v["other_rem"] == v["end"], m
    return dict(sorted(months.items())), used


def estimate_growth(co, months, windows=(1, 3, 6, 12)):
    """Net growth per industry over the last k months of the official series. UK totals are official; each industry's
    part is its share: of new companies incorporated in those months (openings), of companies awaiting strike-off
    (voluntary and compulsory strike-offs) and of companies in liquidation (struck off after liquidation), and of all
    companies (restorations, conversions, the starting size)."""
    # co = companies only (as in the statistics), with the `op` flag. Each industry's shares count its OPERATING companies
    # against ALL companies, so its part is a slice of the official total; "UK" = all operating companies, "UK_ALL" =
    # every company (equals the official register change: the check below)
    ms = list(months)
    # new companies haven't filed accounts yet, so none can show as dormant: scale each industry's new companies by
    # the share of 24-36 month old companies (first accounts filed) that are NOT dormant
    as_of = co.inc.max()
    cohort = co[co.is_company & co.group.ne("") & ~co.holding_name
                & (co.inc > as_of - pd.DateOffset(months=DORMANT_COHORT[1])) & (co.inc <= as_of - pd.DateOffset(months=DORMANT_COHORT[0]))]
    dormant_rate = cohort.groupby("group").dormant.mean().to_dict()
    op = co[co.op]
    stock = op.group.value_counts()
    n_all = len(co)
    is_pipe, is_liq = co.status.str.contains("Strike off", case=False), co.status.str.contains("Liquidation", case=False)
    pipe, liq = op[is_pipe[co.op]].group.value_counts(), op[is_liq[co.op]].group.value_counts()
    n_pipe, n_liq = max(int(is_pipe.sum()), 1), max(int(is_liq.sum()), 1)
    out = {}
    for k in windows:
        if k > len(ms):
            continue
        sel = ms[-k:]
        t = {f: sum(months[m][f] for m in sel) for f in ("inc", "restored", "other_add", "struck", "other_rem", "struck_liq")}
        start_uk = months[sel[0]]["start"]
        lo = pd.Timestamp(sel[0] + "-01")
        hi = pd.Timestamp(sel[-1] + "-01") + pd.offsets.MonthEnd(0)
        in_win = (co.inc >= lo) & (co.inc <= hi)
        new = op[in_win[co.op]].group.value_counts()
        new = pd.Series({g: n * (1 - dormant_rate.get(g, 0)) for g, n in new.items()}, dtype=float)
        n_new = max(int(in_win.sum()), 1)
        rows, parts = {}, {}
        for g in ["UK_ALL", UK] + GROUPS:
            if g == "UK_ALL":
                sh = (1.0, 1.0, 1.0, 1.0)
            elif g == UK:
                sh = (stock.sum() / n_all, new.sum() / n_new, pipe.sum() / n_pipe, liq.sum() / n_liq)
            else:
                sh = (stock.get(g, 0) / n_all, new.get(g, 0) / n_new, pipe.get(g, 0) / n_pipe, liq.get(g, 0) / n_liq)
            sh_stock, sh_new, sh_pipe, sh_liq = sh
            opened = t["inc"] * sh_new + (t["restored"] + t["other_add"]) * sh_stock
            closed = (t["struck"] - t["struck_liq"]) * sh_pipe + t["struck_liq"] * sh_liq + t["other_rem"] * sh_stock
            start = start_uk * sh_stock
            parts[g] = (opened, closed)
            rows[g] = {"start": round(start), "opened": round(opened), "closed": round(closed), "net": round(opened - closed),
                       "rate": (opened - closed) / start if start else None,
                       "open_rate": opened / start if start else None, "close_rate": closed / start if start else None}
        # checks: all companies = the official register change; the industries add up to all operating companies
        assert round(parts["UK_ALL"][0] - parts["UK_ALL"][1]) == months[sel[-1]]["end"] - start_uk
        assert abs(sum(parts[g][0] - parts[g][1] for g in GROUPS) - (parts[UK][0] - parts[UK][1])) < 1
        all_co = rows.pop("UK_ALL")
        out[str(k)] = {"from": sel[0], "to": sel[-1], "months": k, "by_group": rows, "all_companies": all_co,
                       "dormant_rate": {g: round(v, 4) for g, v in dormant_rate.items()}, "dormant_cohort": list(DORMANT_COHORT),
                       "uk_official": {**t, "start": start_uk, "end": months[sel[-1]]["end"]}}
    return out


def corporate_owners():
    """Every corporate owner record in the PSC snapshot (current and ceased), cached per snapshot date."""
    parts = sorted(glob.glob(str(REG / "psc" / "psc-snapshot-*_*of*.zip")))
    if not parts:
        raise SystemExit(f"no PSC snapshot in {REG / 'psc'}: run News Scraper/apollo_emea/ownership.py --download first")
    snap = re.search(r"psc-snapshot-(\d{4}-\d{2}-\d{2})", parts[0]).group(1)
    cache = REG / "psc" / f"corporate-{snap}.csv.gz"
    if cache.exists():
        return pd.read_csv(cache, dtype=str, keep_default_na=False), snap
    for old in glob.glob(str(REG / "psc" / "corporate-*.csv.gz")):
        os.remove(old)
    rows, key = [], b'"kind":"corporate-entity-person-with-significant-control"'
    for i, p in enumerate(parts, 1):
        with zipfile.ZipFile(p) as z:
            for name in z.namelist():
                with z.open(name) as f:
                    for line in f:
                        if key not in line:
                            continue
                        r = json.loads(line)
                        d = r["data"]
                        ident = d.get("identification") or {}
                        rows.append((r["company_number"], d.get("name", ""), ident.get("registration_number", ""),
                                     d.get("notified_on", ""), d.get("ceased_on", ""), ";".join(d.get("natures_of_control", []))))
        print(f"  {os.path.basename(p)} ({i}/{len(parts)}): {len(rows):,} corporate owner records", flush=True)
    ow = pd.DataFrame(rows, columns=["company", "owner_name", "owner_number", "notified_on", "ceased_on", "control"])
    ow.to_csv(cache, index=False)
    return ow, snap


def owner_key(name, number):
    n = re.sub(r"\s+", "", str(number or "")).upper()
    if re.fullmatch(r"\d{1,8}", n):
        return n.zfill(8)
    if re.fullmatch(r"(SC|NI|OC|SO|NC|LP|SL|R0)\d{4,6}", n):
        return n
    return "NAME:" + re.sub(r"[^A-Z0-9]", "", str(name).upper().replace("LIMITED", "LTD"))


def build(out_path, download=False):
    cw = load_crosswalk()
    print("reading company owners (PSC) …", flush=True)
    ow, psc_date = corporate_owners()
    print(f"  {len(ow):,} corporate owner records, snapshot of {psc_date}")
    print("reading Companies House …", flush=True)
    co, ch_date = read_companies(cw)
    co = mark_operating(co, ow)
    save_snapshot(co, ch_date)                      # before a download replaces this month's file
    if download:
        new_date = download_ch()
        if new_date != ch_date:
            co, ch_date = read_companies(cw)
            co = mark_operating(co, ow)
            save_snapshot(co, ch_date)
    print(f"  {len(co):,} live companies, file of {ch_date}; {int(co.op.sum()):,} operating companies")
    flows, snap_dates = monthly_flows()
    print(f"  monthly copies kept: {', '.join(snap_dates)} ({len(flows)} comparison(s))")
    print("reading Companies House statistics …", flush=True)
    months, stats_used = read_stats(stats_files(download))
    cos = co[co.is_company]
    growth = estimate_growth(cos, months)
    print(f"  {', '.join(stats_used)}: months {min(months)} to {max(months)}; windows {', '.join(growth)} month(s)")

    # controlling company owners of companies on the register
    ow = ow[ow.control.str.contains(MAJORITY)].copy()
    ow["n"] = pd.to_datetime(ow.notified_on, errors="coerce")
    ow["c"] = pd.to_datetime(ow.ceased_on, errors="coerce")
    ow = ow.dropna(subset=["n"])
    ow = ow.merge(co[["company", "group", "inc"]], on="company", how="inner")
    ow["owner"] = [owner_key(a, b) for a, b in zip(ow.owner_name, ow.owner_number)]
    ow = ow[ow.owner != ow.company]   # a company listed as its own owner (rare filing error)

    last_q = (pd.Timestamp(min(ch_date, psc_date)).to_period("Q") - 1)   # last complete quarter in both files
    quarters = pd.period_range(FIRST_Q, last_q, freq="Q")
    q_end = [q.end_time.normalize() for q in quarters]

    # takeovers: one event per company and date; first company owner vs changed owner; group buyer or not
    ev = ow[(ow.n - ow.inc).dt.days > 365].sort_values("n").drop_duplicates(["company", "n"])
    prior = ow[["company", "n", "c"]].rename(columns={"n": "pn", "c": "pc"})
    m = ev[["company", "n"]].merge(prior, on="company")
    had = m[(m.pn < m.n) & (m.pc.isna() | (m.pc >= m.n))].drop_duplicates(["company", "n"])[["company", "n"]]
    ev = ev.merge(had.assign(changed=True), on=["company", "n"], how="left")
    ev["changed"] = ev.changed.fillna(False).astype(bool)
    size_in_group = ow.groupby(["group", "owner"]).company.nunique().rename("owner_size").reset_index()
    ev = ev.merge(size_in_group, on=["group", "owner"], how="left")
    ev["group_buyer"] = ev.owner_size >= GROUP_BUYER_MIN
    ev["q"] = ev.n.dt.to_period("Q")

    def series(c_sub, o_sub, e_sub):
        # counts, new companies and status: operating companies only. Ownership (alive / controlled / takeovers):
        # every company with an industry, since a takeover is often recorded on a holding company's register entry
        c_op = c_sub[c_sub.op]
        inc_q = c_op.inc.dt.to_period("Q").value_counts()
        alive = [int((c_sub.inc <= d).sum()) for d in q_end]
        ctrl = [int(o_sub[(o_sub.n <= d) & (o_sub.c.isna() | (o_sub.c > d))].company.nunique()) for d in q_end]
        e = e_sub[e_sub.q.isin(quarters)]
        cnt = lambda sel: [int(x) for x in e[sel].q.value_counts().reindex(quarters, fill_value=0)]
        st = c_op.status
        return {"companies": int(len(c_op)), "companies_all": int(len(c_sub)),
                "insolvent": int(st.str.contains(INSOLVENT).sum()),
                "strike_off": int(st.str.contains("Strike off", case=False).sum()),
                "new": [int(inc_q.get(q, 0)) for q in quarters],
                "alive": alive, "controlled": ctrl,
                "tk_first_gb": cnt(~e.changed & e.group_buyer), "tk_first_other": cnt(~e.changed & ~e.group_buyer),
                "tk_changed": cnt(e.changed)}

    print("building series …", flush=True)
    by_group = {UK: series(co, ow, ev)}
    for g in GROUPS:
        by_group[g] = series(co[co.group == g], ow[ow.group == g], ev[ev.group == g])

    # most active buyers, last 24 months (8 complete quarters), per group
    recent = ev[ev.q.isin(quarters[-8:])]
    names = (ow.sort_values("n").groupby("owner").owner_name.last())
    now_ctrl = ow[ow.c.isna()]
    ctrl_group = now_ctrl.groupby(["group", "owner"]).company.nunique()
    ctrl_all = now_ctrl.groupby("owner").company.nunique()
    buyers = {}
    for g in GROUPS:
        r = recent[recent.group == g].groupby("owner").agg(takeovers=("company", "nunique"), first=("changed", lambda s: int((~s).sum())),
                                                            last=("n", "max")).sort_values(["takeovers", "last"], ascending=False).head(TOP_BUYERS)
        buyers[g] = [{"owner": names.get(k, k), "number": "" if k.startswith("NAME:") else k, "takeovers": int(x.takeovers),
                      "first_owner": int(x.first), "latest": x.last.strftime("%Y-%m-%d"),
                      "controls_in_group": int(ctrl_group.get((g, k), 0)), "controls_all": int(ctrl_all.get(k, 0))}
                     for k, x in r.iterrows()]

    # crosswalk as shown on the page, with company counts
    counts = co.groupby("sic_prefix").size()
    xw = [{"group": r.industry_group or "(no group)", "sic": r.sic_prefix, "what": r.note, "companies": int(counts.get(r.sic_prefix, 0))}
          for r in cw.itertuples()]
    no_sic = int((co.sic == "").sum())
    unmatched = int(((co.sic != "") & (co.sic_prefix == "")).sum())

    # checks: groups add up to the mapped companies; shares are shares
    mapped = int((co.group != "").sum())
    assert sum(by_group[g]["companies"] for g in GROUPS) == int(co.op.sum()) == by_group[UK]["companies"]
    assert sum(by_group[g]["companies_all"] for g in GROUPS) == mapped
    for g, s in by_group.items():
        assert all(c <= a for c, a in zip(s["controlled"], s["alive"])), g

    qa = [{"step": "Live companies in the Companies House file", "rows": int(len(co))},
          {"step": "  with an industry group (first SIC code)", "rows": mapped},
          {"step": "  no group: holding, dormant, non-trading, agriculture, households", "rows": int(len(co) - mapped - no_sic - unmatched)},
          {"step": "  no SIC code given", "rows": no_sic},
          {"step": "  SIC code not in the crosswalk", "rows": unmatched},
          {"step": "Operating companies (counts, new companies, status and growth on this page)", "rows": int(co.op.sum())},
          {"step": "  left out: partnerships, overseas entities, CIOs and similar (not companies)", "rows": int((~co.is_company & co.group.ne("")).sum())},
          {"step": "  left out: dormant accounts", "rows": int((co.is_company & co.group.ne("") & co.dormant).sum())},
          {"step": "  left out: holding company in practice (a parent named Holdings, Group, Topco…)", "rows": int((co.is_company & co.group.ne("") & ~co.dormant & co.holding_name).sum())},
          {"step": "  of the operating companies: subsidiaries (kept: often where the work is)", "rows": int((co.op & co.company.isin(set(ow.company[ow.c.isna()]))).sum())},
          {"step": "  of the operating companies: trading parents (kept)", "rows": int((co.op & co.parent).sum())},
          {"step": "Company-owner records in the PSC snapshot (current and ceased)", "rows": int(len(pd.read_csv(REG / 'psc' / f'corporate-{psc_date}.csv.gz', usecols=[0])))},
          {"step": "  controlling (majority or board right), on a live company", "rows": int(len(ow))},
          {"step": f"Takeovers {quarters[0]}–{quarters[-1]} (company over a year old gains a company owner)", "rows": int(ev.q.isin(quarters).sum())},
          {"step": "Companies used for the growth shares (companies only, as in the official statistics)", "rows": int(len(cos))},
          {"step": "  awaiting strike-off (share of voluntary and compulsory strike-offs)", "rows": int(cos.status.str.contains("Strike off", case=False).sum())},
          {"step": "  in liquidation (share of strike-offs after liquidation)", "rows": int(cos.status.str.contains("Liquidation", case=False).sum())},
          {"step": f"Official UK register, start of {min(months)} (Companies House statistics)", "rows": months[min(months)]["start"]},
          {"step": f"Official UK register, end of {max(months)}", "rows": months[max(months)]["end"]},
          {"step": f"Monthly Companies House copies kept ({', '.join(snap_dates)})", "rows": len(snap_dates)}]
    data = {"meta": {"ch_date": ch_date, "psc_date": psc_date, "first_q": str(quarters[0]), "last_q": str(quarters[-1]),
                     "generated": dt.datetime.now().isoformat(timespec="seconds"), "group_buyer_min": GROUP_BUYER_MIN, "uk": UK},
            "quarters": [str(q) for q in quarters], "groups": GROUPS, "by_group": by_group, "buyers": buyers,
            "growth": growth, "stats_months": months, "stats_files": stats_used,
            "flows": flows, "snapshots": snap_dates, "crosswalk": xw, "qa": qa}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(data, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, allow_nan=False)
    print(f"wrote {out_path}")
    # refresh the page's data without re-grading: grade_leads.py embeds the same file on its next run
    for lead_json in glob.glob(str(out_path.parent / "lead_grades_*.json")):
        d = json.load(open(lead_json, encoding="utf-8"))
        d["trends"] = data
        json.dump(d, open(lead_json, "w", encoding="utf-8"), ensure_ascii=False, allow_nan=False, default=str)
        print(f"  updated {lead_json}")
    ws = list(growth)
    print(f"  {'':32s} {'companies':>9s}  {'controlled':>10s}  {'takeovers 4q':>12s}  " + "  ".join(f"growth {w}m" for w in ws))
    for g in [UK] + GROUPS:
        s = by_group[g]
        print(f"  {g:32s} {s['companies']:>9,}  {s['controlled'][-1] / max(s['alive'][-1], 1):10.1%}  "
              f"{sum(s['tk_first_gb'][-4:]) + sum(s['tk_first_other'][-4:]) + sum(s['tk_changed'][-4:]):>12,}  "
              + "  ".join(f"{growth[w]['by_group'][g]['rate']:+9.2%}" for w in ws))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DATA_DIR / "industry_trends.json"))
    ap.add_argument("--download", action="store_true",
                    help="fetch the newest Companies House monthly file and statistics release first (run monthly, after the 1st)")
    a = ap.parse_args(argv)
    build(Path(a.out), a.download)


if __name__ == "__main__":
    main()
