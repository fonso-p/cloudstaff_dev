"""Step 2: what we know internally: existing clients / HubSpot (priority list), fit (Client Propensity), industry trend."""

import glob
from pathlib import Path

import pandas as pd

from .config import L
from .rules import FIT_SIZE_EDGES, FIT_SIZE_LABELS, TREND_IN_SCORE


# ---------------------------------------------------------------- 2. internal data: clients, HubSpot prospects, fit
def match_internal(leads, path):
    if path is None:
        leads["internal_match"] = None
        return leads, "no priority list found"
    pl = pd.read_excel(path, sheet_name="priority_list", usecols=["account_id", "company_name", "goal", "website_domain", "source"])
    pl = pl[pl["website_domain"].fillna("") != ""]
    by_dom = pl.groupby("website_domain").first()
    def m(r):
        for d in {r["website_domain"], r["email_domain"]} - {""}:
            if d in by_dom.index:
                x = by_dom.loc[d]
                return f"{'Existing client' if x['goal'] == 'Organic Growth' else 'In HubSpot'}: {x['company_name']} ({x.name})"
        return None
    leads["internal_match"] = leads.apply(m, axis=1)
    return leads, f"{path.name}: {len(pl)} accounts with a website ({(pl.goal == 'Organic Growth').sum()} clients)"


def add_fit(leads, path):
    cols = ["fit_growth_p", "fit_growth_band", "fit_reach_10_p", "fit_reach_10_band", "fit_branch_1y_p", "fit_branch_1y_band", "likely_first_new_dept"]
    if path is None:
        for k in cols:
            leads[k] = None
        return leads, "no prospect profiles found"
    pp = pd.read_csv(path)
    # Company size (decision 2026-11-26): the seat-growth scores come from past clients of the same industry AND
    # employee band (Apollo "# Employees" here; Client Propensity's band edges), from the extract's separate
    # prospect_profiles_by_size file (built for these lead grades only; the Account Priority Dashboard keeps using the
    # industry-only prospect_profiles). The 2nd-department score is the same in every band. A lead without a headcount,
    # or an extract without the size file, uses the industry-only profile.
    by_size = Path(str(path).replace("_prospect_profiles.csv", "_prospect_profiles_by_size.csv"))
    if by_size.exists():
        pp = pd.concat([pp, pd.read_csv(by_size)], ignore_index=True)
    pp = pp.set_index("profile_key")
    emp = pd.to_numeric(leads["employee_count"], errors="coerce")
    leads["fit_size_band"] = pd.cut(emp, bins=FIT_SIZE_EDGES, labels=FIT_SIZE_LABELS).astype("string")
    base_key = leads["industry"].fillna("Unknown") + "|" + L.fit_country
    sized = base_key + "|" + leads["fit_size_band"].fillna("")
    leads["fit_profile"] = sized.where(sized.isin(pp.index), base_key)
    leads["fit_size_band"] = leads["fit_size_band"].where(leads["fit_profile"].ne(base_key))
    for k in cols:
        leads[k] = leads["fit_profile"].map(pp[k])
    leads["fit_outlook"] = leads["fit_profile"].map(pp["outlook"]) if "outlook" in pp else None
    # the usual rate of each score (Client Propensity's score definitions): a fit chip needs High AND >= FIT_CHIP_LIFT x usual
    defs = sorted(glob.glob(str(path).replace("_prospect_profiles.csv", "_score_definitions.csv")))
    base = pd.read_csv(defs[-1]).set_index("score")["base_rate"].to_dict() if defs else {}
    for s in ("fit_growth", "fit_reach_10", "fit_branch_1y"):
        leads[f"{s}_usual"] = base.get(s)
    return leads, path.name


def add_trend(leads, path):
    if not path.exists():
        leads["industry_trend"] = None
        return leads, "no industry_trend.csv"
    t = pd.read_csv(path, encoding="utf-8-sig")
    by = {(r.industry_group, r.country): r.industry_trend for r in t.itertuples()}
    def tr(r):
        if not r["industry"]:
            return None, "unknown industry"
        for ctry, why in ((r["region"], f"{r['industry']} × {r['region']}"), ("ALL", f"{r['industry']}, all countries")):
            if (r["industry"], ctry) in by:
                return by[(r["industry"], ctry)], why
        return None, "segment not run"
    leads[["market_trend", "trend_basis"]] = leads.apply(lambda r: pd.Series(tr(r)), axis=1)
    # decision 2026-11-18: not in the score. Tiers rank within each list, where every lead shares the same trend, so the
    # multiplier could only blur scores, never reorder them. Kept as market context (market_trend) on the Fit page.
    leads["industry_trend"] = leads["market_trend"] if TREND_IN_SCORE else None
    return leads, path.name
