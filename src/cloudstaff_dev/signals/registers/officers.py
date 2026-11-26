"""Who runs each lead: current officers (directors, secretaries, LLP members) from the Companies House API.

WHY
The ownership register (ownership.py) says who OWNS or controls a company, not who runs it. The officers list says who
the directors are: the people who take decisions and sign. A named owner who is also a director is the best person to
talk to; a director who is not an owner is a hired manager or a family member (README §4.1, 24 Nov 2026).

WHAT IT DOES
For every company number ownership.py found for a lead (<collected>/ownership.csv, column company_numbers: the lead's own
company and other companies matched to it, e.g. CQC providers), one call to
  GET https://api.company-information.service.gov.uk/company/{number}/officers
and writes <collected>/officers.csv: one row per CURRENT officer who is a person (company_id, company_number, name, role,
appointed_on). Corporate officers (a company acting as director or secretary) are left out.

UNOBTRUSIVE BY DESIGN
- One call at a time, INTERVAL (2 s) apart: ~30 calls a minute against Companies House's 600 per 5 minutes (5%).
- Every answer is cached in <work>/officers_cache.json; a company is asked for again only when its copy is older than
  --max-age days (30). A run stopped part-way resumes where it stopped (the cache is saved every 10 companies).
- "429 Too Many Requests" pauses the run for 5 minutes; a server error is retried twice, slowly, then skipped (and
  asked for again on the next run). A rejected key (401) stops the run.

PERSONAL DATA (UK GDPR): only the name, role and appointment / resignation dates are kept. The API also returns month
and year of birth, nationality, occupation and a service address: those are dropped before anything is stored.

KEY: the repo's .env (git-ignored) with COMPANIES_HOUSE_API_KEY (see .env.example); an environment variable of the
same name wins. A free key from https://developer.company-information.service.gov.uk/ (Live, REST).

Usage (any folder, after ownership; <M> = cloudstaff_dev.signals.registers.officers):
  python -m <M> --dry-run     # how many calls, how long; nothing is fetched
  python -m <M> --limit 5     # small test first
  python -m <M>               # all leads (~10 min the first time, then only new / stale)
  python -m <M> --csv-only    # rebuild officers.csv from the cache
  (--list NAME for a list other than apollo_emea)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import pandas as pd
import requests

from cloudstaff_dev.common import paths
from cloudstaff_dev.common.env import ENV_FILE, read_env


def use_list(name):
    """Point the module at one lead list's files (main calls this; the defaults are apollo_emea's)."""
    global OWNERSHIP_CSV, OUT_CSV, CACHE
    L = paths.lead_list(name)
    OWNERSHIP_CSV = str(L["collected"] / "ownership.csv")
    OUT_CSV = str(L["collected"] / "officers.csv")
    CACHE = str(L["work"] / "officers_cache.json")


OWNERSHIP_CSV = OUT_CSV = CACHE = None
use_list("apollo_emea")
API = "https://api.company-information.service.gov.uk/company/{}/officers"
INTERVAL = 2.0          # seconds between calls
PAUSE_429 = 300         # seconds to wait after "too many requests"
PAGE = 100              # officers per call (most companies fit in one)
KEEP = ("name", "officer_role", "appointed_on", "resigned_on")   # everything else the API returns is dropped


def load_key():
    key = os.environ.get("COMPANIES_HOUSE_API_KEY") or read_env(ENV_FILE).get("COMPANIES_HOUSE_API_KEY", "")
    if not key:
        sys.exit(f"COMPANIES_HOUSE_API_KEY missing: put it in {ENV_FILE} (see .env.example) or set it as an environment variable.")
    return key


def person_name(api_name):
    """'SMITH, John Michael' -> 'John Michael Smith' (the register's form is SURNAME, Forenames)."""
    if "," not in api_name:
        return api_name.strip()
    last, first = api_name.split(",", 1)
    return f"{first.strip()} {last.strip().title()}".strip()


def lead_numbers(path=OWNERSHIP_CSV):
    """{company_number: [company_id, ...]} for every number ownership.py found."""
    o = pd.read_csv(path, dtype=str, keep_default_na=False)
    out = {}
    for cid, nums in zip(o["company_id"], o["company_numbers"]):
        for n in filter(None, (x.strip() for x in nums.split(";"))):
            out.setdefault(n, []).append(cid)
    return out


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)
    os.replace(tmp, CACHE)


class Stop(Exception):
    pass


def fetch(session, number):
    """All officers of one company -> {"status": "ok" | "not found", "items": [...]}, or None after repeated server errors."""
    items, start, server_errors = [], 0, 0
    while True:
        time.sleep(INTERVAL)
        try:
            r = session.get(API.format(number), params={"items_per_page": PAGE, "start_index": start}, timeout=30)
        except requests.RequestException as e:
            r, err = None, type(e).__name__
        if r is not None and r.status_code == 200:
            d = r.json()
            items += [{k: x.get(k) for k in KEEP} for x in d.get("items", [])]
            start += len(d.get("items", []))
            if not d.get("items") or start >= int(d.get("total_results") or 0):
                return {"status": "ok", "items": items}
            continue
        if r is not None and r.status_code == 404:
            return {"status": "not found", "items": []}
        if r is not None and r.status_code == 401:
            raise Stop("Companies House rejected the key (401): check COMPANIES_HOUSE_API_KEY (a Live REST key).")
        if r is not None and r.status_code == 429:
            print(f"  too many requests: pausing {PAUSE_429 // 60} minutes", flush=True)
            time.sleep(PAUSE_429)
            continue
        server_errors += 1
        if server_errors > 2:
            print(f"  {number}: skipped after errors ({r.status_code if r is not None else err}); asked again next run", flush=True)
            return None
        time.sleep(30 * server_errors)


def write_csv(numbers, cache):
    rows = []
    for n, cids in numbers.items():
        c = cache.get(n)
        if not c:
            continue
        for x in c["items"]:
            role = x.get("officer_role") or ""
            if x.get("resigned_on") or role.startswith("corporate") or not x.get("name"):
                continue
            for cid in cids:
                rows.append({"company_id": cid, "company_number": n, "name": person_name(x["name"]), "role": role.replace("-", " "),
                             "appointed_on": x.get("appointed_on") or ""})
    out = pd.DataFrame(rows, columns=["company_id", "company_number", "name", "role", "appointed_on"]).drop_duplicates()
    out.to_csv(OUT_CSV, index=False, encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default="apollo_emea", help="lead list (common/paths.lead_list)")
    ap.add_argument("--max-age", type=int, default=30, help="days before a company's officers are asked for again")
    ap.add_argument("--limit", type=int, help="ask for at most this many companies (a test run)")
    ap.add_argument("--dry-run", action="store_true", help="count the calls and the time; fetch nothing")
    ap.add_argument("--csv-only", action="store_true", help="rebuild officers.csv from the cache")
    a = ap.parse_args(argv)
    use_list(a.list)

    numbers, cache = lead_numbers(), load_cache()
    today = dt.date.today()
    stale = [n for n in numbers if n not in cache or (today - dt.date.fromisoformat(cache[n]["fetched"])).days > a.max_age]
    todo = stale[:a.limit] if a.limit else stale
    print(f"{len(numbers)} company numbers; {len(numbers) - len(stale)} cached and fresh; {len(todo)} to ask for "
          f"(~{len(todo) * INTERVAL / 60:.0f} min at one call every {INTERVAL:.0f} s)")
    if a.dry_run:
        return
    if not a.csv_only and todo:
        session = requests.Session()
        session.auth = (load_key(), "")                    # Companies House: the key is the user name, no password
        session.headers["User-Agent"] = "lead-research/1.0 (python-requests)"
        done = 0
        try:
            for i, n in enumerate(todo, 1):
                res = fetch(session, n)
                if res is not None:
                    cache[n] = {"fetched": today.isoformat(), **res}
                    done += 1
                if i % 10 == 0:
                    save_cache(cache)
                    print(f"  {i}/{len(todo)}", flush=True)
        except (Stop, KeyboardInterrupt) as e:
            print(str(e) or "stopped", flush=True)
        finally:
            save_cache(cache)
        print(f"fetched {done} of {len(todo)}")
    out = write_csv(numbers, cache)
    print(f"wrote {OUT_CSV}: {len(out)} current officers at {out['company_id'].nunique()} leads "
          f"({(out['role'] == 'director').sum()} directors)")


if __name__ == "__main__":
    main()
