"""Turn Apollo contact exports into the news scraper's company list (company mode, jobs, filings).

Apollo exports one row per *contact*; the scraper wants one row per *company*. This script writes
data/companies.csv: company_id, company_name, website, location, country, aliases, context, ambiguous,
employees, lookback_days. And data/parents.csv: the parent companies Apollo names ("Name (domain)"),
company_id `parent-<domain>`, for a news-only run (lead grading shows their events on the lead, marked "Parent").

company_id is `apollo-<Apollo Account Id>`. Lead grading uses the same id (`AP-<Apollo Account Id>`) to join the
scraper's results back to the Apollo lead. Grading, contacts and Apollo's other fields are read from the raw export,
not from here (see Marketing Intelligence/lead_grading/README.md).

Usage (run by `python -m cloudstaff_dev.leads run <list>`; defaults are the list's folders):
  python -m cloudstaff_dev.leads.prepare [--list apollo_emea] [inputs ...] [--out <work>] [--overrides <rules>/overrides.csv]
"""

import argparse
import csv
import glob
import os
import re
import sys
from collections import Counter, defaultdict

# 'Old Name Now New Name' (checked against the website), Apollo name noise and domains: shared with lead grading
from cloudstaff_dev.common.company_keys import clean_name, root_domain, split_renamed

from .config import LeadList

COUNTRY_CODES = {"united kingdom": "UK", "ireland": "IE", "australia": "AU", "new zealand": "NZ",
                 "united states": "US", "canada": "CA", "singapore": "SG", "philippines": "PH"}
LEGAL = r"\b(limited|ltd\.?|plc|llp|llc|inc\.?|uk ltd)$"


def read_rows(paths):
    files = []
    for p in paths:
        files += sorted(glob.glob(os.path.join(p, "*.csv"))) if os.path.isdir(p) else [p]
    rows = []
    for f in files:
        with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
            rows += list(csv.DictReader(fh))
    return files, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="Apollo export CSVs, or folders holding them (default: the list's inputs folder)")
    ap.add_argument("--list", default="apollo_emea", help="lead list: Marketing Intelligence/lead_lists/<name>/list.toml")
    ap.add_argument("--out", help="default: the list's work folder")
    ap.add_argument("--overrides", help="hand fixes per company_name: aliases, context, ambiguous (for generic names found in "
                                        "a run). Default: Marketing Intelligence/lead_lists/<list>/overrides.csv")
    ap.add_argument("--lookback-days", type=int, default=180, help="lookback for companies with no Apollo funding label")
    ap.add_argument("--funded-lookback-days", type=int, default=365,
                    help="longer lookback for companies Apollo marks as funded, so the news can date the event")
    a = ap.parse_args(argv)
    lst = LeadList(a.list)
    a.inputs = a.inputs or [str(lst.inputs)]
    a.out = a.out or str(lst.work)
    a.overrides = a.overrides or str(lst.prepare_overrides)

    files, rows = read_rows(a.inputs)
    if not rows:
        sys.exit("no rows read")
    overrides = {}
    if os.path.exists(a.overrides):
        with open(a.overrides, encoding="utf-8-sig", newline="") as fh:
            overrides = {r["company_name"].strip().lower(): r for r in csv.DictReader(fh) if r.get("company_name")}

    by_co = defaultdict(list)
    for r in rows:
        by_co[r.get("Apollo Account Id") or root_domain(r.get("Website")) or r.get("Company Name")].append(r)

    def apply_overrides(row, overrides, also=""):
        o = overrides.get(row["company_name"].lower()) or overrides.get(also.lower()) or {}   # new name, or Apollo's own
        for k in ("aliases", "context", "ambiguous"):
            v = (o.get(k) or "").strip()
            if v:
                row[k] = v
        return row

    companies, parents, renamed = [], {}, []
    others = {acc: (clean_name(rs[0].get("Company Name", "")), rs[0].get("Website", "")) for acc, rs in by_co.items()}
    for acc, rs in by_co.items():
        r0 = rs[0]
        apollo_name = name = clean_name(r0.get("Company Name", ""))
        # "Monarch Healthcare Now RDCP Care": search the current name, but only when the website, email or LinkedIn
        # (or another account in the list) backs the split; otherwise the name is left alone and listed for a check
        rn = split_renamed(name, [r0.get("Website"), r0.get("Company Linkedin Url")] + [x.get("Email", "") for x in rs],
                           [v for k, v in others.items() if k != acc])
        if rn:
            name = rn["name"]
            renamed.append(f"  {apollo_name} -> {name}: {rn['basis']}")
        email_name = clean_name(r0.get("Company Name for Emails", ""))
        short = re.sub(LEGAL, "", name, flags=re.I).strip(" ,.")
        aliases = [email_name] if email_name and not short.lower().startswith(email_name.lower()) else []
        email_domains = Counter(x.get("Email", "").split("@")[-1].lower() for x in rs if "@" in x.get("Email", ""))
        country = r0.get("Company Country", "").strip()
        row = {
            "company_id": f"apollo-{acc}", "company_name": name,
            "website": root_domain(r0.get("Website")) or (email_domains.most_common(1)[0][0] if email_domains else ""),
            "location": r0.get("Company City", "").strip(), "country": COUNTRY_CODES.get(country.lower(), country),
            "aliases": ";".join(aliases), "context": "", "ticker": "", "ambiguous": "",
            "employees": r0.get("# Employees", "").strip(),
            "lookback_days": a.funded_lookback_days if r0.get("Latest Funding", "").strip() else a.lookback_days,
        }
        apply_overrides(row, overrides, also=apollo_name)
        companies.append(row)
        # Apollo's parent company, "Name (domain)": its news is searched too and shown on the lead as parent news
        m = re.match(r"\s*(.+?)\s*\(([^()]+)\)\s*$", r0.get("Parent company (Apollo data)", "") or "")
        if m and root_domain(m.group(2)) not in parents:
            prow = {**{k: "" for k in row}, "company_id": f"parent-{root_domain(m.group(2))}", "company_name": clean_name(m.group(1)),
                    "website": root_domain(m.group(2)), "country": row["country"], "lookback_days": a.lookback_days}
            parents[prow["website"]] = apply_overrides(prow, overrides)

    os.makedirs(a.out, exist_ok=True)
    for fname, data in (("companies.csv", companies), ("parents.csv", list(parents.values()))):
        path = os.path.join(a.out, fname)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(companies[0]))
            w.writeheader()
            w.writerows(data)
    print(f"read {len(rows)} contacts from {len(files)} file(s) -> {len(companies)} companies "
          f"({sum(1 for c in companies if c['website'])} with a website), {len(parents)} parent companies -> {a.out}")
    if renamed:
        print("names with 'Now' / 'formerly' (the old name is not searched; add it to overrides.csv aliases if wanted):")
        print("\n".join(renamed))


if __name__ == "__main__":
    main()
