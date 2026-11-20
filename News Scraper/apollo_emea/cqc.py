"""CQC register (England) for the Apollo care leads: size, services, ratings, and dated events.

CQC publishes every registered care location monthly under the Open Government Licence ("HSCA Active Locations" and
"Deactivated Locations", https://www.cqc.org.uk/about-us/transparency/using-cqc-data). No API key is needed. Each row
carries the provider's Companies House number, so a lead found in Companies House joins exactly; the rest join on the
website domain, then on an exact multi-word provider or brand name.

What it writes (apollo_emea/out/):
  cqc_providers.csv  one row per lead: match basis, providers, locations, care homes, beds, home-care locations, service
                     types, user groups, ratings, ratings needing improvement, locations added / closed in the last year
  cqc_locations.csv  every matched location (also saved as a snapshot, so next month's run can spot new managers)
  cqc_events.csv     dated events for lead grading, in the scraper's categories:
                       M&A                    a home that left another provider and re-registered under the lead
                                              (same postcode, within 90 days): a takeover
                       Expansion / new office a home registered under the lead with no such predecessor
                       Leadership change      a location whose registered manager differs from the previous snapshot
                                              (needs two monthly runs; the first run has none)
                     A home that moves between the lead's own legal entities is a re-registration, not an event.

Coverage: England only (Scotland, Wales and Northern Ireland have their own regulators). Dates are registration dates,
which follow a takeover or opening by days to weeks.

Usage (from the News Scraper folder):
  ../.venv/Scripts/python.exe apollo_emea/cqc.py [--download] [--lookback-days 365]
--download fetches this month's files when CQC has published new ones (about 25 MB each; turning the .ods into a
cached .csv takes ~3 minutes per file, once).
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "reference_code"))
from company_keys import name_key           # noqa: E402
from news_scraper import http               # noqa: E402
from news_scraper.names import root_domain  # noqa: E402

CQC_DIR = os.path.join(ROOT, "data", "registers", "cqc")
SNAP_DIR = os.path.join(CQC_DIR, "snapshots")
DATA_PAGE = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
TAKEOVER_DAYS = 90            # a predecessor deregistered within this many days of the new registration = takeover
BAD_RATINGS = {"Requires improvement", "Inadequate"}
RATING_ORDER = ["Outstanding", "Good", "Requires improvement", "Inadequate"]
GENERIC_SITES = {"gov.uk", "nhs.uk", "facebook.com", "linkedin.com", "carehome.co.uk", "google.com"}


# ---------------------------------------------------------------- files
def download():
    page = http.get(DATA_PAGE).text
    os.makedirs(CQC_DIR, exist_ok=True)
    for kind in ("HSCA_Active_Locations", "Deactivated_Locations"):
        links = re.findall(rf'href="([^"]+_{kind}\.ods)"', page)
        if not links:
            print(f"no {kind} link on {DATA_PAGE}: CQC may have changed the page")
            continue
        url = links[0] if links[0].startswith("http") else "https://www.cqc.org.uk" + links[0]
        path = os.path.join(CQC_DIR, os.path.basename(url))
        if not os.path.exists(path):
            print(f"downloading {url}")
            with open(path, "wb") as fh:
                fh.write(http.get(url, timeout=600).content)


def file_date(path):
    m = re.search(r"(\d{1,2})_([A-Za-z]+)_(\d{4})", os.path.basename(path))
    return dt.datetime.strptime(" ".join(m.groups()), "%d %B %Y").date() if m else None


def load(kind):
    """Newest file of a kind as a DataFrame of strings; the .ods is converted to a cached .csv once (slow)."""
    files = sorted(glob.glob(os.path.join(CQC_DIR, f"*_{kind}.ods")) + glob.glob(os.path.join(CQC_DIR, f"*_{kind}.csv")),
                   key=lambda p: file_date(p) or dt.date.min)
    if not files:
        sys.exit(f"no CQC {kind} file in {CQC_DIR}: run with --download")
    newest = files[-1]
    csv_path = os.path.splitext(newest)[0] + ".csv"
    if not os.path.exists(csv_path):
        print(f"converting {os.path.basename(newest)} to csv (about 3 minutes, once)")
        sheets = pd.ExcelFile(newest, engine="odf").sheet_names
        sheet = next(s for s in sheets if kind.lower() in s.lower())
        pd.read_excel(newest, engine="odf", sheet_name=sheet, dtype=str).to_csv(csv_path, index=False)
    return pd.read_csv(csv_path, dtype=str, keep_default_na=False), file_date(newest)


# ---------------------------------------------------------------- matching
def ch_number(v):
    v = re.sub(r"[^A-Za-z0-9]", "", str(v or "")).upper()
    return v.zfill(8) if v.isdigit() else v


def site(v):
    d = root_domain(str(v or "").strip())
    return "" if not d or "." not in d or d in GENERIC_SITES or any(d.endswith("." + g) for g in GENERIC_SITES) else d


def leads_table(companies_csv, db):
    leads = pd.read_csv(companies_csv, dtype=str, keep_default_na=False)
    numbers = {}
    if os.path.exists(db):
        with sqlite3.connect(db) as c:
            numbers = {cid: reg for cid, reg in c.execute(
                "select company_id, reg_id from registry_records where register = 'Companies House' and reg_id != ''")}
    leads["ch"] = leads["company_id"].map(numbers).map(lambda x: ch_number(x) if isinstance(x, str) else "")
    leads["site"] = leads["website"].map(site)
    leads["key"] = leads["company_name"].map(name_key)
    return leads


def match(leads, loc):
    """{company_id: (basis, set of CQC provider ids)}: Companies House number, else website, else exact multi-word name."""
    loc = loc.assign(_ch=loc["Provider Companies House Number"].map(ch_number),
                     _psite=loc["Provider Web Address"].map(site), _lsite=loc["Location Web Address"].map(site),
                     _pkey=loc["Provider Name"].map(name_key), _bkey=loc["Brand Name"].map(name_key))
    by_ch = loc[loc["_ch"] != ""].groupby("_ch")["Provider ID"].agg(set).to_dict()
    by_site = {}
    for col in ("_psite", "_lsite"):
        for s, ids in loc[loc[col] != ""].groupby(col)["Provider ID"].agg(set).items():
            by_site.setdefault(s, set()).update(ids)
    by_key = {}
    for col in ("_pkey", "_bkey"):
        for k, ids in loc[loc[col].str.contains(" ")].groupby(col)["Provider ID"].agg(set).items():
            by_key.setdefault(k, set()).update(ids)
    out = {}
    for r in leads.itertuples():
        if r.ch and r.ch in by_ch:
            out[r.company_id] = ("company number", by_ch[r.ch])
        elif r.site and r.site in by_site:
            out[r.company_id] = ("website", by_site[r.site])
        elif " " in r.key and r.key in by_key:
            out[r.company_id] = ("name", by_key[r.key])
    # leads that are one business under two Apollo accounts (prepare.py renamed "Monarch Healthcare Now RDCP Care" to
    # RDCP Care) pool their providers: the homes may still be registered under the old legal names
    for _, g in leads[leads["company_id"].isin(out)].groupby("key"):
        if len(g) > 1:
            ids = set().union(*(out[c][1] for c in g["company_id"]))
            for c in g["company_id"]:
                out[c] = (out[c][0] + " (pooled with the same-named lead)", ids)
    return out


# ---------------------------------------------------------------- per lead
def flags(df, prefix):
    cols = [c for c in df.columns if c.startswith(prefix)]
    return df[cols].eq("Y").apply(lambda row: "; ".join(c[len(prefix):] for c, v in row.items() if v), axis=1)


def postcode(v):
    return re.sub(r"\s+", "", str(v or "")).upper()


def summarise(cid, basis, mine, deact, as_of, lookback):
    since = pd.Timestamp(as_of) - pd.Timedelta(days=lookback)
    start = pd.to_datetime(mine["Location HSCA start date"], errors="coerce")
    pub = pd.to_datetime(mine["Publication Date"], errors="coerce")
    ratings = mine["Location Latest Overall Rating"].replace("", "Not rated yet")
    rc = ratings.value_counts()
    worst = next((x for x in reversed(RATING_ORDER) if x in rc.index), None)
    homes = mine["Care home?"].eq("Y")
    st = mine["_services"].str.split("; ").explode()
    ub = mine["_users"].str.split("; ").explode()
    closed = deact[pd.to_datetime(deact["Location HSCA End Date"], errors="coerce") >= since]
    return {
        "company_id": cid, "cqc_match": basis,
        "cqc_providers": "; ".join(sorted(mine["Provider Name"].unique())),
        "cqc_provider_ids": "; ".join(sorted(mine["Provider ID"].unique())),
        "cqc_provider_numbers": "; ".join(sorted({ch_number(x) for x in mine["Provider Companies House Number"]} - {""})),
        "cqc_brand": "; ".join(sorted({b for b in mine["Brand Name"] if b and b != "-"})),
        "cqc_provider_since": pd.to_datetime(mine["Provider HSCA start date"], errors="coerce").min(),
        "cqc_locations": len(mine), "cqc_care_homes": int(homes.sum()),
        "cqc_beds": int(pd.to_numeric(mine["Care homes beds"], errors="coerce").fillna(0).sum()),
        "cqc_homecare_locations": int(mine["_services"].str.contains("Domiciliary care service").sum()),
        "cqc_service_types": "; ".join(f"{k} ({v})" for k, v in st[st != ""].value_counts().items()),
        "cqc_user_groups": "; ".join(f"{k} ({v})" for k, v in ub[ub != ""].value_counts().items()),
        "cqc_ratings": "; ".join(f"{k} {v}" for k, v in rc.items()),
        "cqc_worst_rating": worst,
        "cqc_needs_improvement": int(ratings.isin(BAD_RATINGS).sum()),
        "cqc_needs_improvement_180d": int((ratings.isin(BAD_RATINGS) & (pub >= pd.Timestamp(as_of) - pd.Timedelta(days=180))).sum()),
        "cqc_latest_rating_date": pub.max(),
        "cqc_new_locations": int((start >= since).sum()), "cqc_newest_location": start.max(),
        "cqc_closed_locations": len(closed),
        "cqc_local_authorities": "; ".join(sorted(set(mine["Location Local Authority"]) - {""})),
        "cqc_url": "https://www.cqc.org.uk/provider/" + sorted(mine["Provider ID"].unique())[0],
    }


def events(cid, mine, deact_all, own_ids, as_of, lookback):
    """New locations in the lookback: takeover (a predecessor elsewhere closed at the same postcode) or new home."""
    since = pd.Timestamp(as_of) - pd.Timedelta(days=lookback)
    m = mine.assign(_start=pd.to_datetime(mine["Location HSCA start date"], errors="coerce"))
    m = m[m["_start"] >= since]
    if m.empty:
        return []
    d = deact_all[deact_all["_pc"].isin(set(m["_pc"]))]
    rows = []
    for _, r in m.iterrows():
        prev = d[(d["_pc"] == r["_pc"]) & ((d["_end"] - r["_start"]).abs() <= pd.Timedelta(days=TAKEOVER_DAYS))]
        if not prev.empty and prev["Provider ID"].isin(own_ids).all():
            continue                                      # moved between the lead's own legal entities: not news
        other = prev[~prev["Provider ID"].isin(own_ids)]
        beds = pd.to_numeric(r["Care homes beds"], errors="coerce")
        rows.append({"start": r["_start"], "from": other["Provider Name"].iloc[0] if len(other) else "",
                     "name": r["Location Name"], "city": r["Location City"], "beds": 0 if pd.isna(beds) else int(beds),
                     "location_id": r["Location ID"], "home": r["Care home?"] == "Y"})
    out = []
    # one event per registration date and predecessor: a group of homes taken over together is one deal
    for (start, frm), g in pd.DataFrame(rows).groupby(["start", "from"]) if rows else []:
        n, beds = len(g), int(g["beds"].sum())
        places = ", ".join(f"{x.name} ({x.city})" if x.city else x.name for x in g.itertuples())
        what = f"{n} care homes" if g["home"].all() and n > 1 else "a care home" if g["home"].all() else f"{n} locations" if n > 1 else "a location"
        bed_txt = f", {beds} beds" if beds else ""
        if frm:
            cat, head = "M&A", f"Took over {what} from {frm}{bed_txt}: {places}"
            detail = f"took over {what} from {frm}"
        else:
            cat, head = "Expansion / new office", f"Registered {what} with CQC{bed_txt}: {places}"
            detail = f"registered {what}"
        out.append({"company_id": cid, "date": start.date().isoformat(), "category": cat, "headline": head[:300],
                    "detail": detail, "url": "https://www.cqc.org.uk/location/" + g["location_id"].iloc[0],
                    "publisher": "CQC register", "source": "cqc"})
    return out


def manager_changes(cid, mine, prev, as_of):
    if prev is None:
        return []
    p = prev[prev["company_id"] == cid].set_index("location_id")["registered_manager"].to_dict()
    out = []
    for _, r in mine.iterrows():
        old, new, where = p.get(r["Location ID"]), r["Registered manager"], r["Location Name"]
        if old and new and old != new:
            out.append({"company_id": cid, "date": as_of.isoformat(), "category": "Leadership change",
                        "headline": f"New registered manager at {where}: {new} (was {old})",
                        "detail": f"new registered manager at {where}",
                        "url": "https://www.cqc.org.uk/location/" + r["Location ID"], "publisher": "CQC register", "source": "cqc"})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--companies", default=os.path.join(HERE, "data", "companies.csv"))
    ap.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--lookback-days", type=int, default=365)
    ap.add_argument("--download", action="store_true", help="fetch this month's CQC files if they are new")
    a = ap.parse_args(argv)
    if a.download:
        download()

    loc, as_of = load("HSCA_Active_Locations")
    deact, _ = load("Deactivated_Locations")
    loc["_services"], loc["_users"] = flags(loc, "Service type - "), flags(loc, "Service user band - ")
    loc["_pc"] = loc["Location Postal Code"].map(postcode)
    deact["_pc"] = deact["Location Postal Code"].map(postcode)
    deact["_end"] = pd.to_datetime(deact["Location HSCA End Date"], errors="coerce")
    leads = leads_table(a.companies, a.db)
    matched = match(leads, loc)

    snaps = sorted(glob.glob(os.path.join(SNAP_DIR, "*.csv")))
    prev = next((pd.read_csv(s, dtype=str, keep_default_na=False) for s in reversed(snaps)
                 if os.path.basename(s) < f"{as_of.isoformat()}.csv"), None)

    summary, evs, locs = [], [], []
    for cid, (basis, ids) in matched.items():
        mine = loc[loc["Provider ID"].isin(ids)]
        summary.append(summarise(cid, basis, mine, deact[deact["Provider ID"].isin(ids)], as_of, a.lookback_days))
        evs += events(cid, mine, deact, ids, as_of, a.lookback_days) + manager_changes(cid, mine, prev, as_of)
        locs.append(pd.DataFrame({
            "company_id": cid, "location_id": mine["Location ID"], "location_name": mine["Location Name"], "city": mine["Location City"],
            "postcode": mine["Location Postal Code"], "local_authority": mine["Location Local Authority"],
            "registered_on": mine["Location HSCA start date"].str[:10], "care_home": mine["Care home?"], "beds": mine["Care homes beds"],
            "rating": mine["Location Latest Overall Rating"], "rating_published": mine["Publication Date"].str[:10],
            "registered_manager": mine["Registered manager"], "service_types": mine["_services"], "user_groups": mine["_users"],
            "provider": mine["Provider Name"], "provider_id": mine["Provider ID"], "dormant": mine["Dormant (Y/N)"]}))

    os.makedirs(a.out, exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)
    pd.DataFrame(summary).to_csv(os.path.join(a.out, "cqc_providers.csv"), index=False)
    ev_cols = ["company_id", "date", "category", "headline", "detail", "url", "publisher", "source"]
    pd.DataFrame(evs, columns=ev_cols).sort_values(["company_id", "date"]).to_csv(os.path.join(a.out, "cqc_events.csv"), index=False)
    allocs = pd.concat(locs, ignore_index=True) if locs else pd.DataFrame()
    allocs.to_csv(os.path.join(a.out, "cqc_locations.csv"), index=False)
    allocs.to_csv(os.path.join(SNAP_DIR, f"{as_of.isoformat()}.csv"), index=False)
    with open(os.path.join(a.out, "cqc_run.json"), "w") as fh:
        json.dump({"cqc_file_date": as_of.isoformat(), "previous_snapshot": os.path.basename(snaps[-1]) if prev is not None else None,
                   "leads": len(leads), "matched": len(matched), "by": pd.Series([b for b, _ in matched.values()]).value_counts().to_dict(),
                   "events": pd.Series([e["category"] for e in evs]).value_counts().to_dict() if evs else {}}, fh, indent=1)
    by = pd.Series([b for b, _ in matched.values()]).value_counts().to_dict()
    print(f"CQC file of {as_of}: {len(matched)} of {len(leads)} leads matched {by}; {len(allocs)} locations; "
          f"{len(evs)} events {pd.Series([e['category'] for e in evs]).value_counts().to_dict() if evs else ''}"
          + ("" if prev is not None else " (first snapshot: manager changes start with next month's file)"))


if __name__ == "__main__":
    main()
