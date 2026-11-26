"""Public-sector contract awards won by the Apollo leads, from Find a Tender (UK).

Since the Procurement Act (24 Feb 2025) Find a Tender carries the award notices of new UK public procurements, above and
below the old thresholds. Its OCDS API is free, needs no key and is published under the Open Government Licence
(https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages). It cannot filter by supplier, so every award
notice in the lookback is fetched (about 40 a day), kept in a compact monthly cache, and matched here.

Matching a supplier to a lead, strongest first:
  1. Companies House number: the lead's own (from the filings run) or one of its CQC providers' (cqc.py; care groups
     contract through subsidiaries such as "Belmont Healthcare (Lincs) Ltd")
  2. exact name key (common/company_keys.py) of 2+ words: the lead's name, its registered legal name, its CQC
     provider names. One-word names are never matched on name alone.

Writes <collected>/contract_awards.csv: one row per award, in the scraper's event shape (category "Contract /
partnership win"), with buyer, value, CPV category and the notice link. Contracts Finder (older, below-threshold
notices) is not read: it did not answer from this network (20 Nov 2026).

Usage (any folder; run by `python -m cloudstaff_dev.leads run <list>`, after cqc):
  python -m cloudstaff_dev.signals.registers.contracts [--list apollo_emea] [--lookback-days 365]
First run ~15-20 minutes (one page of 100 notices every 4 seconds: the API rate-limits faster use); later runs fetch
only the current month. Finished months are cached, so an interrupted run resumes where it stopped.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import time

import pandas as pd
import requests

from cloudstaff_dev.common import paths
from cloudstaff_dev.common.company_keys import ch_number, name_key
from cloudstaff_dev.signals import http

API = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
CACHE = str(paths.REGISTERS / "fts")
NOTICE = "https://www.find-tender.service.gov.uk/Notice/"


def compact(rel):
    """One award release -> the fields we keep (buyer, title, CPV, value, dates, suppliers)."""
    t = rel.get("tender") or {}
    parties = rel.get("parties") or []
    sup = [{"name": (p.get("identifier") or {}).get("legalName") or p.get("name") or "",
            "ch": ch_number((p.get("identifier") or {}).get("id")) if (p.get("identifier") or {}).get("scheme") == "GB-COH" else "",
            "town": (p.get("address") or {}).get("locality") or ""}
           for p in parties if "supplier" in (p.get("roles") or [])]
    buyer = next((p.get("name") for p in parties if "buyer" in (p.get("roles") or [])), "") or (rel.get("buyer") or {}).get("name", "")
    vals = [a.get("value") for a in rel.get("awards") or [] if a.get("value")] + \
           [c.get("value") for c in rel.get("contracts") or [] if c.get("value")] + ([t["value"]] if t.get("value") else [])
    val = next((v for v in vals if v.get("amount")), {})
    signed = next((c.get("dateSigned") for c in rel.get("contracts") or [] if c.get("dateSigned")), None)
    award_date = next((a.get("date") for a in rel.get("awards") or [] if a.get("date")), None)
    cls = t.get("classification") or {}
    return {"notice": rel.get("id"), "ocid": rel.get("ocid"), "published": rel.get("date"), "signed": signed or award_date,
            "buyer": buyer, "title": t.get("title") or "", "cpv": cls.get("id") or "", "cpv_desc": cls.get("description") or "",
            "value": val.get("amount"), "currency": val.get("currency") or "", "suppliers": sup}


PAGE_INTERVAL = 4.0     # seconds between pages: Find a Tender rate-limits (429, "try again in 2 minutes") at ~1 a second
_last = [0.0]


def _page(url, params):
    """One API page, paced, waiting out a 429 for as long as the server asks (up to 10 times)."""
    for _ in range(10):
        wait = PAGE_INTERVAL - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(url, params=params, timeout=90, headers={"User-Agent": http.UA})
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            _last[0] = time.monotonic()
            print(f"    {time.strftime('%H:%M:%S')} {type(e).__name__}: retrying in 30 s", flush=True)
            time.sleep(30)
            continue
        _last[0] = time.monotonic()
        if r.status_code == 429:
            pause = float(r.headers.get("Retry-After") or 120) + 5
            print(f"    {time.strftime('%H:%M:%S')} rate limited: waiting {pause:.0f} s", flush=True)
            time.sleep(pause)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Find a Tender kept rate-limiting; run again later (finished months are cached)")


def fetch_window(first, last, label):
    """Award notices updated from `first` to `last` (dates, inclusive). Returns (notices, looped): looped = the API's
    next-page cursor came back to notices already read (seen for Feb 2026), so the window is incomplete."""
    url, params, out = API, {"stages": "award", "limit": 100, "updatedFrom": f"{first}T00:00:00",
                             "updatedTo": f"{last + dt.timedelta(days=1)}T00:00:00"}, []
    seen = set()
    while url:
        d = _page(url, params)
        rels = d.get("releases") or []
        new = [r for r in rels if r.get("id") not in seen]
        if rels and not new:                         # the cursor came back to notices already read: stop, don't loop
            return out, True
        seen.update(r.get("id") for r in new)
        out += [compact(r) for r in new]
        print(f"    {time.strftime('%H:%M:%S')} {label}: {len(out)} unique notices", flush=True)
        url, params = (d.get("links") or {}).get("next"), None
    return out, False


def fetch_month(first, last):
    out, looped = fetch_window(first, last, f"{first:%Y-%m}")
    if not looped:
        return out
    # a looping cursor: fetch the month a day at a time instead (a day is usually one page, so nothing to loop)
    print(f"    {first:%Y-%m}: the API's paging looped; fetching day by day", flush=True)
    out, day = [], first
    while day <= last:
        got, looped = fetch_window(day, day, f"{day}")
        if looped:
            print(f"    {day}: paging looped even for one day; kept the {len(got)} notices read", flush=True)
        out += got
        day += dt.timedelta(days=1)
    return list({r["notice"]: r for r in out}.values())


def awards(lookback, today):
    """Award notices updated in the lookback, month by month; finished months come from the cache."""
    os.makedirs(CACHE, exist_ok=True)
    start = (today - dt.timedelta(days=lookback)).replace(day=1)
    rows, m = [], start
    while m <= today:
        nxt = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        last = min(nxt - dt.timedelta(days=1), today)
        path = os.path.join(CACHE, f"awards_{m:%Y-%m}.jsonl")
        # a cached month is final only if it was saved 2+ days after the month ended: a file saved mid-month (a run on
        # 25 Oct) is fetched again on the next run, so notices from the rest of that month are not missed
        complete = os.path.exists(path) and \
            dt.date.fromtimestamp(os.path.getmtime(path)) >= nxt + dt.timedelta(days=2)
        if complete:
            with open(path, encoding="utf-8") as fh:
                got = [json.loads(x) for x in fh]
        else:
            got = fetch_month(m, last)
            print(f"  {m:%Y-%m}: {len(got)} award notices fetched")
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(json.dumps(x) + "\n" for x in got)
        rows += got
        m = nxt
    # a notice updated more than once appears more than once: keep the newest version
    return list({r["notice"]: r for r in sorted(rows, key=lambda r: r["published"] or "")}.values())


def lead_keys(companies_csv, db, cqc_csv):
    """{company_id: (set of Companies House numbers, set of 2+ word name keys)}."""
    leads = pd.read_csv(companies_csv, dtype=str, keep_default_na=False)
    reg = {}
    if os.path.exists(db):
        with sqlite3.connect(db) as c:
            for cid, num, data in c.execute("select company_id, reg_id, data from registry_records "
                                            "where register = 'Companies House' and reg_id != ''"):
                reg[cid] = (num, (json.loads(data or "{}").get("name") or ""))
    cqc = pd.read_csv(cqc_csv, dtype=str, keep_default_na=False).set_index("company_id") if os.path.exists(cqc_csv) else pd.DataFrame()
    out = {}
    for r in leads.itertuples():
        nums, names = set(), {r.company_name, *[a for a in r.aliases.split(";") if a]}
        if r.company_id in reg:
            nums.add(ch_number(reg[r.company_id][0]))
            names.add(reg[r.company_id][1])
        if r.company_id in cqc.index:
            c = cqc.loc[r.company_id]
            nums |= {ch_number(x) for x in str(c.get("cqc_provider_numbers", "")).split("; ") if x}
            names |= {x for x in str(c.get("cqc_providers", "")).split("; ") if x}
        keys = {k for k in map(name_key, names) if " " in k}
        out[r.company_id] = (nums - {""}, keys)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    paths.add_list_args(ap)
    ap.add_argument("--lookback-days", type=int, default=365)
    a = paths.resolve_list_args(ap.parse_args(argv))
    today = dt.date.today()
    notices = awards(a.lookback_days, today)
    keys = lead_keys(a.companies, a.db, os.path.join(a.out, "cqc_providers.csv"))
    by_num, by_key = {}, {}
    for cid, (nums, ks) in keys.items():
        for n in nums:
            by_num.setdefault(n, set()).add(cid)
        for k in ks:
            by_key.setdefault(k, set()).add(cid)

    rows = []
    for n in notices:
        for s in n["suppliers"]:
            hit, basis = by_num.get(ch_number(s["ch"])) if s["ch"] else None, "company number"   # cached months: older format
            if not hit:
                hit, basis = by_key.get(name_key(s["name"])), "name"
            for cid in hit or ():
                date = (n["signed"] or n["published"] or "")[:10]
                if date > today.isoformat():                     # a future start date: date it by the notice instead
                    date = (n["published"] or "")[:10]
                v = n["value"]
                money = "" if v in (None, "") else f"{'£' if n['currency'] in ('GBP', '') else n['currency'] + ' '}{float(v):,.0f}"
                rows.append({"company_id": cid, "date": date, "category": "Contract / partnership win",
                             "headline": f"Won \"{n['title'][:140]}\" from {n['buyer']}" + (f" ({money})" if money else ""),
                             "detail": f"public contract from {n['buyer']}" + (f", {money}" if money else ""),
                             "url": NOTICE + n["notice"], "publisher": "Find a Tender", "source": "fts",
                             "buyer": n["buyer"], "value": v, "currency": n["currency"], "cpv": n["cpv"], "cpv_desc": n["cpv_desc"],
                             "supplier_name": s["name"], "match": basis})
    cols = ["company_id", "date", "category", "headline", "detail", "url", "publisher", "source", "buyer", "value", "currency",
            "cpv", "cpv_desc", "supplier_name", "match"]
    out = pd.DataFrame(rows, columns=cols).drop_duplicates(["company_id", "url"])
    out = out[out["date"] >= (today - dt.timedelta(days=a.lookback_days)).isoformat()].sort_values(["company_id", "date"])
    os.makedirs(a.out, exist_ok=True)
    out.to_csv(os.path.join(a.out, "contract_awards.csv"), index=False)
    print(f"{len(notices)} award notices in {a.lookback_days} days; {len(out)} awards to {out['company_id'].nunique()} leads "
          f"({out['match'].value_counts().to_dict() if len(out) else {}})")


if __name__ == "__main__":
    main()
