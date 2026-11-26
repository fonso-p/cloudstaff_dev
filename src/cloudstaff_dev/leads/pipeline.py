"""Grade one lead list end to end (python -m cloudstaff_dev.leads grade <list>)."""

import argparse

import pandas as pd

from cloudstaff_dev.common import paths

from .apollo import extract_apollo, standardise
from .collected import add_collected
from .config import L, use
from .enrich import match_owner_contacts, owners_export
from .events import add_competitor_clients, compound_events
from .export import readout, save
from .grade import grade
from .internal import add_fit, add_trend, match_internal
from .rules import COMPETITOR_MAP, DUPLICATE, HIRING_SCORE, TREND_FILE


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("list", nargs="?", default="apollo_emea", help="lead list: Marketing Intelligence/lead_lists/<name>/list.toml")
    a = ap.parse_args(argv)
    use(a.list)
    as_of = pd.Timestamp.today().normalize()

    raw, files = extract_apollo(L.inputs)
    leads, contacts = standardise(raw)
    leads, internal_src = match_internal(leads, paths.newest(paths.ACCOUNT_PRIORITY_OUT, "priority_company_info_combined*.xlsx"))
    leads, events, parent_events, jobs_by_lead, roles_src = add_collected(leads, L.collected, as_of)
    leads = compound_events(leads, events, as_of)
    leads, competitor_src = add_competitor_clients(leads, COMPETITOR_MAP)   # sets prior_bpo_flag (Competitor client points)
    # fit and trend after the target check, which can correct the industry group (Companies House codes come from the scraper)
    leads, fit_src = add_fit(leads, paths.newest(paths.PROPENSITY_INPUTS, "*_Propensity_Extract_prospect_profiles.csv"))
    leads, trend_src = add_trend(leads, TREND_FILE)
    leads, contacts = match_owner_contacts(leads, contacts)   # named owners who are Apollo contacts
    leads = grade(leads, contacts, events, as_of)

    # checks: ids unique, every lead graded, contacts all belong to a lead
    assert leads["account_id"].is_unique, "duplicate account_id"
    assert leads["grade"].notna().all(), "a lead has no grade"
    assert set(contacts["account_id"]) <= set(leads["account_id"]), "contact without a lead"
    extract = max(pd.to_datetime(raw["Primary Email Last Verified At"], errors="coerce", utc=True).dropna()).strftime("%Y-%m-%d")
    qa = [{"step": "Apollo contacts (rows in the export files)", "rows": int(len(raw))},
          {"step": "Companies (one per Apollo account)", "rows": int(len(leads))},
          {"step": "  of which news checked by News Scraper", "rows": int(leads["news_status"].isin(["found", "checked, nothing found"]).sum())},
          {"step": "  of which found in Companies House", "rows": int((leads["filings_status"] == "found in Companies House").sum())},
          {"step": "  of which ownership known (Companies House PSC, Apollo parent or PE news)",
           "rows": int((~leads["ownership"].isin(["Unknown", "Not checked"])).sum())},
          {"step": "  of which a named owner is an Apollo contact", "rows": int(leads["owner_contacts"].notna().sum())},
          {"step": "  of which a current director (Companies House officers) is an Apollo contact", "rows": int(leads["officer_contacts"].notna().sum())},
          {"step": "Excluded: distressed (administration, liquidation, strike-off)", "rows": int((leads["grade"] == "Excluded: distressed").sum())},
          {"step": "Existing client (sent to the AM, not graded)", "rows": int((leads["grade"] == "Existing client").sum())},
          {"step": "Duplicate (renamed to another lead in the list, not graded)", "rows": int((leads["grade"] == DUPLICATE).sum())},
          {"step": "Graded (Tier 1-3)", "rows": int(leads["grade"].str.startswith("Tier").sum())}]
    info = {"apollo_extract": extract, "internal": internal_src, "fit_profiles": fit_src, "trend": trend_src, "roles": roles_src,
            "competitor_map": competitor_src,
            "hiring_score": HIRING_SCORE, "service_lines": {k: list(v) for k, v in L.service_lines.items()},
            "scoring_profile": "dashboard_v3 (priority_scoring.py)", "qa": qa,
            "readout": readout(leads, events, files, len(contacts))}
    xlsx, js = save(leads, contacts, events, parent_events, jobs_by_lead, info, L.name, as_of)
    owners_csv, n_owners = owners_export(leads, as_of)
    print(f"owners to find in Apollo: {n_owners} people -> {owners_csv}")
    print(leads["grade"].value_counts().to_string())
    print(f"wrote {xlsx}\n      {js}")


if __name__ == "__main__":
    main()
