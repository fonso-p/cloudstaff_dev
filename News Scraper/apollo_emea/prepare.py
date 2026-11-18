"""Turn Apollo contact exports into the news scraper's company list (company mode, jobs, filings).

Apollo exports one row per *contact*; the scraper wants one row per *company*. This script writes
data/companies.csv: company_id, company_name, website, location, country, aliases, context, ambiguous,
employees, lookback_days. And data/parents.csv: the parent companies Apollo names ("Name (domain)"),
company_id `parent-<domain>`, for a news-only run (lead grading shows their events on the lead, marked "Parent").

company_id is `apollo-<Apollo Account Id>`. Marketing Intelligence's lead grading uses the same id
(`AP-<Apollo Account Id>`) to join the scraper's results back to the Apollo lead. Grading, contacts and Apollo's
other fields are read by Marketing Intelligence from the raw export, not from here
(see ../../Marketing Intelligence/apollo_lead_grading/README.md).

Usage (from the News Scraper folder):
  ../.venv/Scripts/python.exe apollo_emea/prepare.py "<folder with apollo-contacts-export*.csv>" [more files or folders]
"""
import argparse
import csv
import glob
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")

COUNTRY_CODES = {"united kingdom": "UK", "ireland": "IE", "australia": "AU", "new zealand": "NZ",
                 "united states": "US", "canada": "CA", "singapore": "SG", "philippines": "PH"}
LEGAL = r"\b(limited|ltd\.?|plc|llp|llc|inc\.?|uk ltd)$"


def root_domain(u):
    if not u:
        return ""
    h = urlparse(u if "//" in u else "http://" + u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def clean_name(name):
    """'MIRACL | The login you love' -> 'MIRACL'; 'White Hat (an EPAM company)' -> 'White Hat';
    'Coxbench Hall Residential Care Home - Derby' -> 'Coxbench Hall Residential Care Home';
    'BLANEFIELD CARE LIMITED' -> 'Blanefield Care Limited' (one-word all-caps names such as CYJAX are kept)."""
    n = re.split(r"\s+\|\s+|\s+\(|\s+[-–]\s+", name.strip())[0].strip()
    if n.isupper() and len(n.split()) > 1:
        n = " ".join(w if len(w) <= 3 and not w.isalpha() else w.capitalize() for w in n.split())
    return n


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
    ap.add_argument("inputs", nargs="+", help="Apollo export CSVs, or folders holding them")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--overrides", default=os.path.join(HERE, "overrides.csv"),
                    help="hand fixes per company_name: aliases, context, ambiguous (for generic names found in a run)")
    ap.add_argument("--lookback-days", type=int, default=180, help="lookback for companies with no Apollo funding label")
    ap.add_argument("--funded-lookback-days", type=int, default=365,
                    help="longer lookback for companies Apollo marks as funded, so the news can date the event")
    a = ap.parse_args(argv)

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

    def apply_overrides(row, overrides):
        for k in ("aliases", "context", "ambiguous"):
            v = (overrides.get(row["company_name"].lower(), {}).get(k) or "").strip()
            if v:
                row[k] = v
        return row

    companies, parents = [], {}
    for acc, rs in by_co.items():
        r0 = rs[0]
        name = clean_name(r0.get("Company Name", ""))
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
        apply_overrides(row, overrides)
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


if __name__ == "__main__":
    main()
