"""Export the competitor -> client map for other projects: company names only, no candidate data.

Reads the notebook's output workbook (Client Summary + the competitor rows' `Work History Campaign`) and writes
DATA_DIR/competitor_clients.csv, one row per competitor x client:

  client_name, name_key, competitor, rows_confirmed, rows_pending, client_locations, source, status, extracted_on

  source   "extracted"       the notebook's rule-based extraction from the Company text (reviewable, measured)
           "campaign field"  the export's Work History Campaign on competitor rows: often the client's name, unverified
  status   "confirmed"       extracted, with at least one row not waiting for review
           "pending"         extracted but only in rows waiting for review, or from the campaign field

Used by Marketing Intelligence/apollo_lead_grading (Competitor client points) and, later, the Priority Score
notebook's prior_bpo_flag. Run after the notebook:
  ../.venv/Scripts/python.exe export_client_map.py
"""
import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))
from company_keys import name_key   # noqa: E402

DATA_DIR = Path(r"C:\Users\Alfonso(FonsoP)Panli\Desktop\Projects\Competitor Analysis (client scrape)\data")
OUTPUT_FILE = DATA_DIR / "client_extraction_output.xlsx"     # the notebook's output (read only)
MAP_FILE = DATA_DIR / "competitor_clients.csv"
# Competitors' other names and brands (from the notebook's aliases and CLAUDE.md): never a client
COMPETITOR_BRANDS = ["The Outsourced Accountant", "Outsourced Accountant", "Outsource Accountant", "MAG Solutions", "KMC MAG Solutions", "MyCloud People", "ShoreAgent", "ShoreSuite", "ShoreRemote",
                     "KMC MAG", "KMC Savills", "Emapta Versatile Services", "Support Ninja", "Connext Global Solutions",
                     "Support Services Group", "Cloud Accountant Staffing", "Remote Staff"]
# Work History Campaign values that describe the work, not a client ("Healthcare Account", "others"...)
CAMPAIGN_NOISE = re.compile(r"\b(?:account|accounts|campaign|bookkeeping|others?|admin|customer service|support|e-?commerce|"
                            r"taxation|accounting firm|back office|team|project|various|n/?a)\b", re.I)


def main():
    cs = pd.read_excel(OUTPUT_FILE, sheet_name="Client Summary")
    ex = pd.DataFrame({
        "client_name": cs["Client"], "competitor": cs["Competitor"],
        "rows_confirmed": cs["Confirmed Rows"].fillna(0).astype(int), "rows_pending": cs["Rows Pending Review"].fillna(0).astype(int),
        "client_locations": cs["Client Locations"], "source": "extracted"})
    ex["status"] = ex["rows_confirmed"].gt(0).map({True: "confirmed", False: "pending"})

    ar = pd.read_excel(OUTPUT_FILE, sheet_name="All Rows", usecols=["Competitor", "Work History Campaign"]).fillna("")
    ar = ar[(ar["Competitor"] != "") & (ar["Work History Campaign"].str.strip() != "")]
    ar["client_name"] = ar["Work History Campaign"].str.strip().str.replace(r"\s*\(.*\)$", "", regex=True)
    competitor_keys ={name_key(c) for c in ex["competitor"].dropna().unique()}
    ar = ar[~ar["client_name"].str.contains(CAMPAIGN_NOISE) & ~ar["client_name"].map(name_key).isin(competitor_keys)
            & ar["client_name"].map(name_key).str.len().ge(4)]
    camp = (ar.groupby(["Competitor", "client_name"]).size().reset_index(name="rows_pending")
            .rename(columns={"Competitor": "competitor"}).assign(rows_confirmed=0, client_locations=None, source="campaign field", status="pending"))

    out = pd.concat([ex, camp], ignore_index=True)
    out["name_key"] = out["client_name"].map(name_key)
    # a competitor's own name or brand is not its client ("The Outsourced Accountant" is TOA Global)
    own = competitor_keys | {name_key(b) for b in COMPETITOR_BRANDS}
    out = out[(out["name_key"].str.len() >= 4) & ~out["name_key"].isin(own)]
    out["extracted_on"] = dt.datetime.fromtimestamp(OUTPUT_FILE.stat().st_mtime).strftime("%Y-%m-%d")
    cols = ["client_name", "name_key", "competitor", "rows_confirmed", "rows_pending", "client_locations", "source", "status", "extracted_on"]
    out[cols].to_csv(MAP_FILE, index=False, encoding="utf-8")
    print(f"wrote {MAP_FILE}: {len(out):,} competitor-client rows, {out['name_key'].nunique():,} distinct clients · "
          f"{out['status'].value_counts().to_dict()} · {out['source'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
