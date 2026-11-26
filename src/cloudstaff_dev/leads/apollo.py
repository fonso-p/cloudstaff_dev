"""Step 1: read the Apollo export(s) and standardise them to one lead per account plus a contacts table."""

import glob
import os
import re

import pandas as pd

from cloudstaff_dev.common.company_keys import clean_name, split_renamed
from cloudstaff_dev.common.industry import INDUSTRY_SECTOR

from .config import L
from .helpers import band, domain, industry_group
from .rules import COUNTRY_CODE, GOAL, SENIORITY_ORDER, TECH


# ---------------------------------------------------------------- 1. extract + standardise Apollo
def extract_apollo(folder):
    files = sorted(glob.glob(str(folder / "*.csv")))
    frames = [pd.read_csv(f, dtype=str, encoding="utf-8-sig", encoding_errors="replace").assign(_file=os.path.basename(f)) for f in files]
    return pd.concat(frames, ignore_index=True), files


def standardise(c):
    c = c.copy()
    c["account_id"] = "AP-" + c["Apollo Account Id"]
    leads = []
    firsts = c.groupby("account_id", sort=False).first()
    others = {a: (clean_name(x["Company Name"]), x.get("Website")) for a, x in firsts.iterrows()}
    for acc, g in c.groupby("account_id", sort=False):
        r = g.iloc[0]
        # "Monarch Healthcare Now RDCP Care": same rule as the scraper's prepare.py (reference_code/company_keys.py)
        rn = split_renamed(clean_name(r["Company Name"]), [r.get("Website"), r.get("Company Linkedin Url")] + g["Email"].dropna().tolist(),
                           [v for k, v in others.items() if k != acc]) or {}
        same_as = next((k for k, v in others.items() if k != acc and rn.get("same_as") and v[0] == rn["same_as"]), None)
        shown = (f"{rn['name']} (was {rn['former_name']})" if rn.get("former_name") else rn.get("name")) or clean_name(r["Company Name"])
        lst = str(r.get("Lists", ""))
        list_name, targets = next(((n, t) for k, (n, t) in L.list_target.items() if k in lst.lower()), (lst, set()))
        emp = pd.to_numeric(r.get("# Employees"), errors="coerce")
        grp = industry_group(r.get("Industry"))
        email_doms = g["Email"].dropna().str.split("@").str[-1].str.lower()
        tech = str(r.get("Technologies") or "")
        leads.append({
            "account_id": acc, "company_name": shown, "goal": GOAL,
            "former_name": rn.get("former_name") or None, "name_note": rn.get("basis"), "name_check": bool(rn.get("check")),
            "duplicate_of": same_as, "duplicate_of_name": rn.get("same_as") or None,
            "industry": grp, "employee_band": band(emp), "region": COUNTRY_CODE.get(str(r.get("Company Country", "")).lower(), "Other"),
            "lead_list": list_name, "list_target": ", ".join(sorted(targets)),
            "industry_raw": r.get("Industry"), "industry_sector": INDUSTRY_SECTOR.get(grp) if grp else None,
            "employee_count": None if pd.isna(emp) else int(emp), "city": r.get("Company City"),
            "website_domain": domain(r.get("Website")) or (email_doms.mode().iloc[0] if len(email_doms) else ""),
            "email_domain": email_doms.mode().iloc[0] if len(email_doms) else "",
            "annual_revenue": pd.to_numeric(r.get("Annual Revenue"), errors="coerce"),
            "apollo_latest_funding": r.get("Latest Funding"), "parent_company": r.get("Parent company (Apollo data)"),
            "pitch": "; ".join(k for k, rx in TECH.items() if re.search(rx, tech, re.I)),
            "company_linkedin": r.get("Company Linkedin Url"), "apollo_name": r["Company Name"],
            "_on_target": (grp in targets) if targets else None,   # first view, from Apollo's industry only; target_check() decides
            "sic_us": r.get("SIC Codes"), "naics": r.get("NAICS Codes"),
        })
    contacts = pd.DataFrame({
        "account_id": c["account_id"], "name": (c["First Name"].fillna("") + " " + c["Last Name"].fillna("")).str.strip(),
        "title": c["Title"], "seniority": c["Seniority"], "email": c["Email"], "email_status": c["Email Status"],
        "linkedin": c["Person Linkedin Url"], "country": c["Country"],
    })
    contacts["_rank"] = contacts["seniority"].str.lower().map({s: i for i, s in enumerate(SENIORITY_ORDER)}).fillna(99)
    contacts = contacts.sort_values(["account_id", "_rank", "name"]).drop(columns="_rank")
    return pd.DataFrame(leads), contacts
