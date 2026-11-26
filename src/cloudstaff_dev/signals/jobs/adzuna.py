"""Coverage check: would Adzuna's UK job-board listings fill the hiring gap for the Apollo leads? TRIAL USE ONLY.

WHY THIS IS SEPARATE FROM THE JOBS COLLECTOR
Adzuna's API terms (https://developer.adzuna.com/docs/terms_of_service, read 23 Nov 2026) say:
  - "Any other use, including commercial analysis, resale of data, and sales prospecting or lead generation, requires
    our written agreement."
  - a commercial organisation's use "is permitted subject to a 14 day trial period", which "is strictly for the purpose
    of validating the general coverage and quality of the data in addition to usability testing". The data "may not be
    used in its original format or in aggregation" or "to deliver any ongoing work or research ... without written consent."
So until Cloudstaff has a written licence from Adzuna, this script's results must NOT feed lead grading, the dashboard,
company_summary.csv or signal_events.csv. It writes to its own database (<work>/adzuna.db, which lead grading never
reads) and to a coverage report (<collected>/adzuna_coverage.csv + .json) that answers one question for the licence talk:
how many leads would gain a known hiring count, and are those roles ones Cloudstaff fills?
If the trial ends without a licence, delete <work>/adzuna.db and the adzuna_coverage.* files.

WHAT IT DOES
For each lead: search Adzuna GB for ads from the last 30 days that mention the lead's name (what_phrase), then keep the
ads whose employer (company.display_name) is the lead. Adzuna documents no employer filter, so matching is by name:
  matched    the employer's name key (common/company_keys.py) equals one of the lead's 2+ word name keys: its
             Apollo name, aliases, Companies House name (filings run) or CQC provider names (cqc.py). One-word or
             ambiguous names are searched near the lead's city (where=, 30 km) and count only with that limit.
  possible   the employer's name starts with or contains the lead's name ("Forge Care Homes" for "Forge Care"), or a
             one-word / ambiguous name with no city to limit it: listed for a person to judge, not counted
Ads placed by recruitment agencies carry the agency's name, so "no matched ads" is never read as "not hiring".
Only an ad's id, title, employer, location, date, category and link are kept: no descriptions.

KEYS: the repo's .env (git-ignored) with ADZUNA_APP_ID and ADZUNA_APP_KEY (see .env.example); environment variables
of the same names win. The key is sent in the URL, so error messages are scrubbed before they are printed or stored.

Usage (any folder; run after jobs, export and cqc so the careers-page result is there to compare; --list for another list):
  python -m cloudstaff_dev.signals.jobs.adzuna --limit 10      # small test first: check the matches by hand
  python -m cloudstaff_dev.signals.jobs.adzuna                 # all leads (~1-2 calls each, ~2.5 s apart)
  python -m cloudstaff_dev.signals.jobs.adzuna --report-only   # rebuild the report from what is stored
Leads already checked today are skipped, so a run stopped by the daily call limit resumes where it stopped.
"""
import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
from collections import Counter

import pandas as pd

from cloudstaff_dev.common import paths
from cloudstaff_dev.common.company_keys import core_name, name_key
from cloudstaff_dev.common.env import ENV_FILE, read_env  # noqa: F401  (read_env: tests and older callers)
from cloudstaff_dev.signals import http

API = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
TERMS = "https://developer.adzuna.com/docs/terms_of_service"
MAX_DAYS_OLD = 30
PER_PAGE = 50                     # Adzuna's maximum results_per_page
NEAR_KM = 30                      # one-word / ambiguous names: only ads within this distance of the lead's city

TABLES = """
CREATE TABLE IF NOT EXISTS adzuna_checks (
  company_id TEXT NOT NULL, checked_on TEXT NOT NULL, query TEXT NOT NULL, near TEXT, status TEXT, n_total INTEGER,
  n_returned INTEGER, pages INTEGER, note TEXT, max_days INTEGER,
  PRIMARY KEY (company_id, checked_on, query));
CREATE TABLE IF NOT EXISTS adzuna_ads (
  company_id TEXT NOT NULL, ad_id TEXT NOT NULL, match TEXT, title TEXT, employer TEXT, location TEXT, created TEXT,
  category TEXT, contract_time TEXT, url TEXT, query TEXT, first_seen TEXT, last_seen TEXT,
  PRIMARY KEY (company_id, ad_id));
"""


class StopRun(Exception):
    """Bad keys or the daily limit: no point trying the next lead."""


# ---------------------------------------------------------------- keys
def load_keys(path=ENV_FILE):
    env = read_env(path)
    app_id = os.environ.get("ADZUNA_APP_ID") or env.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY") or env.get("ADZUNA_APP_KEY", "")
    if not (app_id and app_key):
        sys.exit(f"Adzuna keys missing: put ADZUNA_APP_ID and ADZUNA_APP_KEY in {path} (see .env.example) or set them "
                 "as environment variables.")
    return app_id, app_key


def scrub(text, secrets):
    """Remove the keys from a message (Adzuna takes them in the URL, and errors quote the URL)."""
    text = str(text)
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return re.sub(r"(app_(id|key)=)[^&\s]+", r"\1***", text)


# ---------------------------------------------------------------- the leads and their names
HOME_WORDS = {"care", "home", "homes", "nursing", "residential", "centre", "center", "house", "the", "extra", "services"}
SUFFIX_WORDS = ["care", "home", "homes", "nursing", "residential", "centre", "center", "extra", "services"]   # dropped from a home's name
HOME_KM = 10                      # a care home's own name is searched within this distance of its town


def home_searches(lead_keys, homes):
    """CQC locations (active care homes) -> [{q, near, km, home_key}]: one search per home whose name isn't the group's
    ('Delta Care Ltd - Preston' is found by the group search already)."""
    out, seen = [], set()
    for h in homes:
        name = re.split(r"\s+[-–]\s*|\s*-\s+", h["location_name"])[0].strip()
        full = name_key(name)
        if not full or not h.get("city") or any(full == lk or full.startswith(lk + " ") or lk.startswith(full + " ") for lk in lead_keys):
            continue
        # search the base name: "Portland House Nursing Home" -> "Portland House" (ads often drop the suffix)
        words = full.split()
        while len(words) > 1 and words[-1] in SUFFIX_WORDS:
            words.pop()
        k = " ".join(words)
        if k in seen or set(words) <= HOME_WORDS:       # "The Care Home"
            continue
        seen.add(k)
        q = name[: len(name) - len(re.search(r"(\s+(" + "|".join(SUFFIX_WORDS) + r")\b\.?)*\s*$", name, re.I).group(0))] or name
        out.append({"q": core_name(q), "near": h["city"].strip(), "km": HOME_KM, "home_key": k})
    return out


def leads(companies_csv, news_db, cqc_csv, summary_csv, locations_csv=None):
    """One dict per lead: searches to run, name keys to match, city, and the careers-page result to compare with.
    locations_csv (cqc_locations.csv): also search each care home's own name near its town (--homes)."""
    df = pd.read_csv(companies_csv, dtype=str, keep_default_na=False)
    reg = {}
    if os.path.exists(news_db):
        with sqlite3.connect(f"file:{news_db}?mode=ro", uri=True) as c:
            try:
                for cid, data in c.execute("select company_id, data from registry_records "
                                           "where register = 'Companies House' and reg_id != ''"):
                    reg[cid] = json.loads(data or "{}").get("name") or ""
            except sqlite3.OperationalError:          # no filings run yet
                pass
    cqc = pd.read_csv(cqc_csv, dtype=str, keep_default_na=False).set_index("company_id") if os.path.exists(cqc_csv) else pd.DataFrame()
    jobs = (pd.read_csv(summary_csv, dtype=str, keep_default_na=False).set_index("company_id")
            if os.path.exists(summary_csv) else pd.DataFrame())
    homes = {}
    if locations_csv and os.path.exists(locations_csv):
        loc = pd.read_csv(locations_csv, dtype=str, keep_default_na=False)
        loc = loc[loc["dormant"].str.lower().isin(["", "n", "no", "false", "0"])] if "dormant" in loc else loc
        homes = {cid: g.to_dict("records") for cid, g in loc.groupby("company_id")}
    out = []
    for r in df.itertuples():
        names = [r.company_name, *[a for a in r.aliases.split(";") if a.strip()]]
        if reg.get(r.company_id):
            names.append(reg[r.company_id])
        if r.company_id in cqc.index:
            names += [x for x in str(cqc.loc[r.company_id].get("cqc_providers", "")).split("; ") if x]
        keys = {k for k in map(name_key, names) if k}
        lead_key = name_key(r.company_name)
        # what we search for: the Apollo name, plus the registered name when it is a different name; legal suffixes
        # dropped, since ads rarely say "Ltd"
        queries = [core_name(r.company_name)]
        if reg.get(r.company_id) and name_key(reg[r.company_id]) not in (lead_key, "") and " " in name_key(reg[r.company_id]):
            queries.append(core_name(reg[r.company_id]))
        short = " " not in lead_key or r.ambiguous.strip().lower() in ("yes", "y", "true", "1")
        near = r.location.strip() if short and r.location.strip() else None
        searches = [{"q": q, "near": near, "km": NEAR_KM, "home_key": None} for q in queries]
        searches += home_searches(keys, homes.get(r.company_id, []))
        j = jobs.loc[r.company_id] if r.company_id in jobs.index else {}
        out.append({"company_id": r.company_id, "company_name": r.company_name, "city": r.location.strip(),
                    "short": short, "keys": keys, "queries": queries, "searches": searches,
                    "careers_status": (j.get("jobs_status") if len(j) else "") or "not checked",
                    "careers_open_roles": (j.get("open_roles") if len(j) else "") or ""})
    return out


def match(employer, lead, near):
    """'matched', 'possible' or None for one ad's employer name. `near`: the search was limited to the lead's city."""
    k = name_key(employer)
    if not k:
        return None
    multi = {x for x in lead["keys"] if " " in x}
    if k in multi and not lead["short"]:
        return "matched"
    if k in lead["keys"]:
        return "matched" if near else "possible"
    if any(re.search(r"(?<![a-z0-9])" + re.escape(x) + r"(?![a-z0-9])", k) for x in multi if len(x) >= 6):
        return "possible"                     # "forge care homes" for "forge care"
    return None


def match_home(employer, home_key):
    """A care home's own ads (searched near its town): the employer is the home, give or take 'care home' words."""
    k = name_key(employer)
    if not k:
        return None
    if k == home_key:
        return "matched"
    if k.startswith(home_key + " ") and set(k[len(home_key):].split()) <= HOME_WORDS:
        return "matched"                      # "ivybank house care home" for "ivybank house"
    if re.search(r"(?<![a-z0-9])" + re.escape(home_key) + r"(?![a-z0-9])", k):
        return "possible"
    return None


# ---------------------------------------------------------------- Adzuna
def search(phrase, keys, page=1, where=None, interval=2.5, km=NEAR_KM, max_days=MAX_DAYS_OLD):
    params = {"app_id": keys[0], "app_key": keys[1], "what_phrase": phrase,
              "results_per_page": PER_PAGE, "sort_by": "date", "content-type": "application/json"}
    if max_days:                              # 0 = every live ad, however long ago it was posted
        params["max_days_old"] = max_days
    if where:
        params.update(where=where, distance=km)
    try:
        r = http.get(API.format(page=page), params=params, key="adzuna", interval=interval, retries=2)
    except http.FetchError as e:
        msg = scrub(e, keys)
        if re.search(r"HTTP (401|403)", msg):
            raise StopRun(f"Adzuna refused the keys ({msg[:80]}): check ADZUNA_APP_ID / ADZUNA_APP_KEY") from None
        if "HTTP 429" in msg:
            raise StopRun("Adzuna's call limit reached (HTTP 429): run again later; finished leads are kept") from None
        raise RuntimeError(msg) from None
    except Exception as e:                    # network errors also quote the URL
        raise RuntimeError(scrub(f"{type(e).__name__}: {e}", keys)) from None
    return r.json()


def check_lead(lead, keys, store, today, max_pages, interval, skip=frozenset(), homes=False, max_days=MAX_DAYS_OLD):
    """Runs the lead's searches (name searches; with homes=True also its care homes' names), skipping (company_id, query)
    pairs already done today."""
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    calls = 0
    for s in lead["searches"]:
        q, near = s["q"], s["near"]
        if (s["home_key"] and not homes) or (lead["company_id"], q) in skip:
            continue
        status, note, total, returned, pages, ads = "ok", "", 0, 0, 0, {}
        try:
            for page in range(1, max_pages + 1):
                d = search(q, keys, page, near, interval, s["km"], max_days)
                calls += 1
                pages = page
                res = d.get("results") or []
                total = d.get("count") or 0
                returned += len(res)
                hits = 0
                for a in res:
                    emp = (a.get("company") or {}).get("display_name", "")
                    m = match_home(emp, s["home_key"]) if s["home_key"] else match(emp, lead, bool(near))
                    if m:
                        hits += 1
                        ads[str(a.get("id"))] = (m, a)
                # next page only when this one had the lead's ads and there are more
                if not hits or page * PER_PAGE >= total:
                    break
        except StopRun:
            raise
        except Exception as e:
            status, note = "failed", str(e)[:200]
        with store:
            store.execute("INSERT OR REPLACE INTO adzuna_checks VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (lead["company_id"], today, q, near or "", status, total, returned, pages, note, max_days))
            for ad_id, (m, a) in ads.items():
                store.execute("""INSERT INTO adzuna_ads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(company_id, ad_id) DO UPDATE SET
                    match=CASE WHEN adzuna_ads.match='matched' THEN 'matched' ELSE excluded.match END, title=excluded.title,
                    employer=excluded.employer, location=excluded.location, last_seen=excluded.last_seen""",
                              (lead["company_id"], ad_id, m, a.get("title") or "", (a.get("company") or {}).get("display_name", ""),
                               (a.get("location") or {}).get("display_name", ""), (a.get("created") or "")[:10],
                               (a.get("category") or {}).get("label", ""), a.get("contract_time") or "",
                               a.get("redirect_url") or "", q, now, now))
    return calls


# ---------------------------------------------------------------- report
def classify_titles(titles, use_roles):
    """title -> verdict (we fill / possible / no match / on-site), with roles.py when a Staff Central report is found."""
    titles = sorted(set(titles))
    if not titles:
        return {}
    from cloudstaff_dev.common import roles
    report = paths.staff_report() if use_roles else None
    if report:
        m = roles.RoleMatcher(report).match(titles)
        return dict(zip(m["title"], m["verdict"]))
    return {t: "on-site" if re.search(roles.ONSITE, roles.clean_title(t)) else "not classified" for t in titles}


def report(store, lead_list, out_dir, today, use_roles):
    checks = pd.read_sql("SELECT * FROM adzuna_checks", store)
    ads_all = pd.read_sql("SELECT * FROM adzuna_ads", store)        # every ad seen live (any posting date, once run with --max-days-old 0)
    verdict = classify_titles(ads_all.loc[ads_all["match"] == "matched", "title"], use_roles)
    ads_all["role"] = ads_all["title"].map(verdict).fillna("")
    ads = ads_all[ads_all["created"] >= (dt.date.fromisoformat(today) - dt.timedelta(days=MAX_DAYS_OLD)).isoformat()]
    latest = checks.sort_values("checked_on").groupby(["company_id", "query"]).tail(1)
    rows = []
    for ld in lead_list:
        c = latest[latest["company_id"] == ld["company_id"]]
        a = ads[ads["company_id"] == ld["company_id"]]
        m, p = a[a["match"] == "matched"], a[a["match"] == "possible"]
        status = "not checked" if c.empty else "failed" if (c["status"] == "failed").all() else "ok"
        roles_ = Counter(m["role"])
        by_name = c[c["query"].isin(ld["queries"])]
        aa = ads_all[(ads_all["company_id"] == ld["company_id"]) & (ads_all["match"] == "matched")]
        rows.append({
            "company_id": ld["company_id"], "company_name": ld["company_name"], "city": ld["city"],
            "careers_jobs_status": ld["careers_status"], "careers_open_roles": ld["careers_open_roles"],
            "careers_known": ld["careers_status"] == "ok",
            "adzuna_status": status, "adzuna_checked_on": c["checked_on"].max() if len(c) else "",
            "searched_for": "; ".join(by_name["query"]), "near_city": "; ".join(sorted(set(by_name["near"]) - {""})),
            "homes_searched": len(c) - len(by_name),
            "ads_mentioning_name": int(by_name["n_total"].sum()) if len(by_name) else "",
            "name_search_max_days": ("any" if (by_name["max_days"].fillna(MAX_DAYS_OLD) == 0).any() else int(by_name["max_days"].fillna(MAX_DAYS_OLD).max()))
                                    if len(by_name) else "",
            "ads_matched_any_age": len(aa), "matched_we_fill_any_age": int((aa["role"] == "we fill").sum()),
            "ads_matched_30d": len(m), "ads_possible_30d": len(p),
            "ads_matched_via_home_names": int((~m["query"].isin(ld["queries"])).sum()),
            "matched_we_fill": roles_.get("we fill", 0), "matched_possible_role": roles_.get("possible", 0),
            "matched_onsite": roles_.get("on-site", 0),
            "matched_titles": "; ".join(sorted(set(m["title"]))[:12]),
            "possible_employers": "; ".join(sorted(set(p["employer"]))[:6]),
            "note": "; ".join(n for n in c["note"] if n)[:200] if len(c) else ""})
    df = pd.DataFrame(rows)
    checked = df[df["adzuna_status"] == "ok"]
    gap = checked[~checked["careers_known"]]
    summary = {
        "TERMS": f"Trial coverage check only: not for grading, the dashboard or any lead list without a written licence ({TERMS})",
        "report_date": today, "leads": len(df), "checked_ok": len(checked),
        "failed": int((df["adzuna_status"] == "failed").sum()), "not_checked": int((df["adzuna_status"] == "not checked").sum()),
        "leads_with_matched_ads_any_age": int((checked["ads_matched_any_age"] > 0).sum()),
        "leads_with_matched_ads": int((checked["ads_matched_30d"] > 0).sum()),
        "careers_page_unknown": len(gap),
        "careers_page_unknown_gaining_ads": int((gap["ads_matched_30d"] > 0).sum()),
        "careers_page_known_with_ads_too": int((checked[checked["careers_known"]]["ads_matched_30d"] > 0).sum()),
        "leads_with_home_names_searched": int((checked["homes_searched"] > 0).sum()),
        "leads_with_ads_only_via_home_names": int(((checked["ads_matched_30d"] > 0)
                                                   & (checked["ads_matched_via_home_names"] == checked["ads_matched_30d"])).sum()),
        "matched_ads": int(checked["ads_matched_30d"].sum()),
        "matched_ads_via_home_names": int(checked["ads_matched_via_home_names"].sum()),
        "matched_ads_roles_we_fill": int(checked["matched_we_fill"].sum()),
        "matched_ads_possible_roles": int(checked["matched_possible_role"].sum()),
        "matched_ads_onsite": int(checked["matched_onsite"].sum()),
        "leads_with_a_role_we_fill": int((checked["matched_we_fill"] > 0).sum()),
        "possible_matches_to_check": int(checked["ads_possible_30d"].sum()),
        "role_classification": "roles.py with the Staff Central JP catalogue" if any(v in ("we fill", "possible", "no match") for v in verdict.values())
                               else "on-site rule only (no Staff Central report found)",
    }
    os.makedirs(out_dir, exist_ok=True)
    df.sort_values(["ads_matched_30d", "ads_possible_30d"], ascending=False).to_csv(
        os.path.join(out_dir, "adzuna_coverage.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(out_dir, "adzuna_coverage.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


# ---------------------------------------------------------------- run
def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default="apollo_emea", help="lead list whose folders are the defaults (paths.lead_list)")
    ap.add_argument("--companies", help="default: <work>/companies.csv")
    ap.add_argument("--news-db", help="read only: Companies House names (default: <work>/news.db)")
    ap.add_argument("--db", help="Adzuna's own store, never news.db (default: <work>/adzuna.db)")
    ap.add_argument("--out", help="default: the list's collected folder")
    ap.add_argument("--limit", type=int, help="only the first N leads (test the matching first)")
    ap.add_argument("--max-pages", type=int, default=3, help="pages of 50 ads per search (default 3)")
    ap.add_argument("--interval", type=float, default=2.5, help="seconds between calls (default 2.5)")
    ap.add_argument("--refresh", action="store_true", help="search again leads already checked today")
    ap.add_argument("--max-days-old", type=int, default=MAX_DAYS_OLD,
                    help=f"only ads posted in the last N days (default {MAX_DAYS_OLD}); 0 = every live ad, however old")
    ap.add_argument("--homes", action="store_true",
                    help=f"also search each care lead's CQC home names near their towns ({HOME_KM} km; small groups may advertise per home)")
    ap.add_argument("--report-only", action="store_true", help="no calls: rebuild the report from the store")
    ap.add_argument("--no-roles", action="store_true", help="skip roles.py (on-site rule only)")
    a = ap.parse_args(argv)
    L = paths.lead_list(a.list)
    a.companies = a.companies or str(L["work"] / "companies.csv")
    a.news_db = a.news_db or str(L["work"] / "news.db")
    a.db = a.db or str(L["work"] / "adzuna.db")
    a.out = a.out or str(L["collected"])
    if os.path.abspath(a.db) == os.path.abspath(a.news_db):
        ap.error("--db must not be the scraper's news.db: Adzuna data stays out of what grading reads")

    print(f"Adzuna coverage check: TRIAL USE ONLY. Results must not feed grading or the dashboard without a written licence\n"
          f"  ({TERMS})")
    today = dt.date.today().isoformat()
    lead_list = leads(a.companies, a.news_db, os.path.join(a.out, "cqc_providers.csv"), os.path.join(a.out, "company_summary.csv"),
                      os.path.join(a.out, "cqc_locations.csv"))
    os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
    store = sqlite3.connect(a.db)
    store.executescript(TABLES)
    if "max_days" not in {r[1] for r in store.execute("PRAGMA table_info(adzuna_checks)")}:
        store.execute("ALTER TABLE adzuna_checks ADD COLUMN max_days INTEGER")     # older rows: NULL = the 30-day default

    if not a.report_only:
        keys = load_keys()
        done = set() if a.refresh else set(store.execute(
            "SELECT company_id, query FROM adzuna_checks WHERE checked_on=? AND status='ok' AND COALESCE(max_days, ?)=?",
            (today, MAX_DAYS_OLD, a.max_days_old)))
        wanted = lambda ld: [s for s in ld["searches"] if (a.homes or not s["home_key"]) and (ld["company_id"], s["q"]) not in done]
        todo = [ld for ld in lead_list[: a.limit] if wanted(ld)]
        print(f"{len(todo)} leads, {sum(len(wanted(ld)) for ld in todo)} searches to run "
              f"({len(lead_list[: a.limit]) - len(todo)} leads already done today)")
        calls, stopped = 0, None
        for i, ld in enumerate(todo, 1):
            try:
                calls += check_lead(ld, keys, store, today, a.max_pages, a.interval, done, a.homes, a.max_days_old)
            except StopRun as e:
                stopped = str(e)
                break
            if i % 20 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} leads · {calls} calls")
        print(f"{calls} API calls" + (f" · STOPPED: {stopped}" if stopped else ""))

    s = report(store, lead_list[: a.limit] if a.limit else lead_list, a.out, today, not a.no_roles)
    store.close()
    print(f"\nLeads searched: {s['checked_ok']} of {s['leads']} ({s['failed']} failed, {s['not_checked']} not yet)\n"
          f"Leads with live ads matched to them, any posting date: {s['leads_with_matched_ads_any_age']}\n"
          f"Leads with ads matched to them (last {MAX_DAYS_OLD} days): {s['leads_with_matched_ads']}\n"
          f"  careers page unknown today: {s['careers_page_unknown']}, of which gain matched ads: {s['careers_page_unknown_gaining_ads']}\n"
          f"  careers page already read and Adzuna has ads too: {s['careers_page_known_with_ads_too']}\n"
          f"  leads with care-home names searched: {s['leads_with_home_names_searched']}, "
          f"found only through a home name: {s['leads_with_ads_only_via_home_names']}\n"
          f"Matched ads: {s['matched_ads']} ({s['matched_ads_via_home_names']} via home names) · roles we fill {s['matched_ads_roles_we_fill']} · possible {s['matched_ads_possible_roles']} · "
          f"on-site {s['matched_ads_onsite']} ({s['role_classification']})\n"
          f"Leads with at least one role we fill: {s['leads_with_a_role_we_fill']}\n"
          f"Possible matches to check by hand: {s['possible_matches_to_check']} (column possible_employers)\n"
          f"Wrote {os.path.join(a.out, 'adzuna_coverage.csv')} and adzuna_coverage.json")


if __name__ == "__main__":
    main()
