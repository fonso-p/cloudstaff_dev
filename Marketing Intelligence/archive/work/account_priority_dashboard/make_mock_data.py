"""Make the work-side MOCK files (all fictional) that prep.py adds to the reference accounts.csv:

    accounts_extra.csv   400 more accounts (ACC-1401 to ACC-1800), doubling the dataset. Same columns and the same
                         generation rules and workbook formulas as reference materials/scripts/generate_mock_workbook.py,
                         with a different random seed and names that do not repeat the reference ones.
    account_roles.csv    the owner role of every account (Marketing, SDR or BDM): one owner per account.
                         SDR owns New Logo only. Mock rule: New Logo with a Diamond referral -> SDR (85%) or BDM;
                         other New Logo routed to BDM by the workbook -> BDM (80%) or
                         Marketing; New Logo routed to SDR -> SDR (60%) or Marketing; Organic Growth -> BDM (70%) or Marketing.
    seat_growth.csv      seats added in the last 6 months, for every Organic Growth account (blank = unknown).

The reference folder is never changed. Run from the "Marketing Intelligence" folder:
    ../.venv/Scripts/python.exe work/account_priority_dashboard/make_mock_data.py
"""
import datetime as dt
import json
import math
import os
import random

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REF = os.path.join(ROOT, "reference materials", "data")
AS_OF = dt.date(2026, 11, 8)
N_EXTRA, FIRST_ID = 400, 1401

# ---- the generator's lists (copied from generate_mock_workbook.py)
INDUSTRIES = {"Healthcare": 0.8, "Logistics": 0.7, "Legal": 0.5, "Real Estate": 0.4, "Accounting & Finance": 0.7, "E-commerce": 0.9,
              "Construction": 0.6, "Insurance": 0.5, "Marketing Agency": 0.6, "SaaS / Tech": 0.8, "Education": 0.3, "Hospitality": 0.4}
PREF = ["Harbor", "Vantage", "Kestrel", "Northwind", "Bluegum", "Summit", "Ironbark", "Coral", "Meridian", "Redgate", "Silverline", "Wattle",
        "Pinnacle", "Cobalt", "Driftwood", "Granite", "Lumen", "Orchard", "Tasman", "Beacon", "Clearwater", "Fernhill", "Halcyon", "Juniper",
        "Larkspur", "Marlow", "Oakridge", "Quarry", "Riverstone", "Sterling", "Thornbury", "Waratah", "Yarra", "Ember", "Foxglove", "Gullwing"]
SUFF = {"Healthcare": ["Dental Group", "Medical", "Allied Health", "Clinics"], "Logistics": ["Freight", "Logistics", "Transport", "Supply Co"],
        "Legal": ["Legal", "Law Partners", "Lawyers"], "Real Estate": ["Realty", "Property Group", "Estates"],
        "Accounting & Finance": ["Accountants", "Advisory", "Financial", "Tax & Co"], "E-commerce": ["Store", "Goods Online", "Commerce"],
        "Construction": ["Builders", "Construction", "Civil"], "Insurance": ["Insurance", "Underwriting", "Cover"],
        "Marketing Agency": ["Creative", "Media", "Digital"], "SaaS / Tech": ["Software", "Labs", "Systems", "Cloud"],
        "Education": ["Academy", "Learning", "College"], "Hospitality": ["Hotels", "Hospitality", "Venues"]}
REGIONS = ["AU-NSW", "AU-VIC", "AU-QLD", "AU-WA", "AU-SA", "NZ", "US", "UK"]
BANDS = ["1-10", "11-50", "51-200", "201-500", "500+"]

S = {r["key"]: r["value"] for r in json.load(open(os.path.join(REF, "scoring_settings.json"), encoding="utf-8"))}
SETTINGS = json.load(open(os.path.join(REF, "scoring_settings.json"), encoding="utf-8"))
NEWS = {r["label"]: r["value"] for r in SETTINGS if r["kind"] == "news"}
NEWS_CATS = list(NEWS)                                     # Funding round ... None
REC = [r["value"] for r in SETTINGS if r["kind"] == "recency"]


def rnd(x, d=0):
    """Excel ROUND (half away from zero; values here are never negative)."""
    m = 10 ** d
    return math.floor(x * m + 0.5 + 1e-9) / m


def raw_rows(rng, used):
    """The generator's raw inputs, row by row."""
    out = []
    for i in range(N_EXTRA):
        goal = "Organic Growth" if rng.random() < 0.4 else "New Logo"
        ind = rng.choice(list(SUFF))
        while True:
            name = f"{rng.choice(PREF)} {rng.choice(SUFF[ind])}"
            if name not in used:
                used.add(name)
                break
        intent = rng.betavariate(1.05, 1.0)
        newlogo = goal == "New Logo"
        ind_val = ind if rng.random() > 0.16 else None
        band = rng.choice(BANDS) if rng.random() > 0.18 else None
        reg = rng.choice(REGIONS) if rng.random() > 0.10 else None
        if rng.random() < (0.68 if newlogo else 0.28):
            visits = tb = ff = None
        else:
            visits = int(max(0, rng.gauss(intent * 26, 4))) if rng.random() < 0.35 + intent else 0
            tb = "Yes" if (visits > 0 and rng.random() < intent * 0.45) else "No"
            ff = int(rng.random() < intent * 0.28) * rng.randint(1, 3) if visits > 0 else 0
        if rng.random() < (0.55 if newlogo else 0.38):
            news = ndate = jobs = spike = None
        else:
            if rng.random() < 0.15 + intent * 0.8:
                news = rng.choices(NEWS_CATS[:-1], weights=[intent, intent, intent * 0.8, 0.6, 0.5, 0.4, 0.3])[0]
                ndate = AS_OF - dt.timedelta(days=int(rng.uniform(3, 60 + (1 - intent) * 280)))
            else:
                news, ndate = "None", None
            jobs = None if rng.random() < 0.30 else int(max(0, rng.gauss(intent * 26, 5)))
            spike = None if jobs is None else ("Yes" if jobs >= 18 and rng.random() < 0.7 else "No")
        if newlogo:
            r_ = rng.random()
            dia = "Yes" if r_ < 0.02 + intent * 0.25 else ("No" if r_ < 0.45 else None)
            r2 = rng.random()
            bpo = "Yes" if r2 < 0.05 + intent * 0.5 else ("No" if r2 < 0.40 else None)
        else:
            dia = bpo = "N/A"
        out.append(dict(account_id=f"ACC-{FIRST_ID + i}", company_name=name, goal=goal, industry=ind_val, employee_band=band, region=reg,
                        web_visits_30d=visits, team_builder_visit=tb, form_fill_30d=ff, news_signal=news, news_signal_date=ndate,
                        job_postings_30d=jobs, hiring_spike=spike, diamond_referral=dia, prior_bpo_flag=bpo))
    return out


def workbook_columns(a):
    """The workbook's formula columns (Priority List P:AF), with the reference settings."""
    nl = a["goal"] == "New Logo"
    mw, mn = (S["web_max_nl"], S["news_max_nl"]) if nl else (S["web_max_og"], S["news_max_og"])
    trend = INDUSTRIES.get(a["industry"]) if a["industry"] else None
    mod = 1 if trend is None else rnd(S["mod_min"] + trend * (S["mod_max"] - S["mod_min"]), 3)
    web = None if a["web_visits_30d"] is None else rnd((S["tb_share"] if a["team_builder_visit"] == "Yes" else 0)
                                                      + (S["ff_share"] if (a["form_fill_30d"] or 0) > 0 else 0)
                                                      + min(a["web_visits_30d"] / S["vol_cap"], 1) * S["vol_share"], 3)
    if a["news_signal"] is None and a["job_postings_30d"] is None:
        nj = None
    else:
        news = 0
        if a["news_signal"] is not None:
            rf = 1 if a["news_signal_date"] is None else next(f for lo, f in zip([181, 91, 31, 0], REC[::-1]) if (AS_OF - a["news_signal_date"]).days >= lo)
            news = NEWS[a["news_signal"]] * rf
        hire = 1 if a["hiring_spike"] == "Yes" else min((a["job_postings_30d"] or 0) / S["jobs_cap"], 1)
        nj = rnd(S["news_share"] * news + S["jobs_share"] * hire, 3)
    wp = rnd(mw * (S["base_web"] if web is None else web), 1)
    npt = rnd(mn * (S["base_news"] if nj is None else nj), 1)
    dp = (S["dia_max"] if a["diamond_referral"] == "Yes" else 0) if nl else "N/A"
    bp = (S["bpo_max"] if a["prior_bpo_flag"] == "Yes" else 0) if nl else "N/A"
    base = wp + npt + (dp if nl else 0) + (bp if nl else 0)
    score = int(min(100, rnd(base * mod, 0)))
    est = "Website, News" if web is None and nj is None else "Website" if web is None else "News" if nj is None else None
    cov = ((0 if web is None else mw) + (0 if nj is None else mn) + (S["dia_max"] + S["bpo_max"] if nl else 0)) / 100
    hot = None
    if nl and a["diamond_referral"] == "Yes":
        hot = "Diamond referral"
    elif (a["form_fill_30d"] or 0) > 0:
        hot = "Form fill"
    elif not nl and a["team_builder_visit"] == "Yes":
        hot = "Team Builder visit"
    elif a["news_signal"] is not None and a["news_signal_date"] is not None and NEWS.get(a["news_signal"], 0) >= S["hot_strength"] \
            and (AS_OF - a["news_signal_date"]).days <= S["hot_days"]:
        hot = a["news_signal"]
    tier = "Tier 1" if score >= S["tier1"] else "Tier 2" if score >= S["tier2"] else "Tier 3"
    team = "AM" if not nl else "BDM" if (a["diamond_referral"] == "Yes" or hot or score >= S["bdm_min"]) else "SDR"
    return dict(industry_trend=trend, industry_modifier=mod, web_signal=web, news_jobs_signal=nj, web_pts=wp, news_jobs_pts=npt,
                diamond_pts=dp, bpo_pts=bp, base_points=round(base, 1), priority_score=score, estimated_fields=est,
                data_coverage=round(cov, 2), hot_trigger=hot, tier=tier, assigned_team=team, sort_key=score + (1000 if hot else 0))


def main():
    ref = pd.read_csv(os.path.join(REF, "accounts.csv"), dtype={"employee_band": str})
    rows = [{**a, **workbook_columns(a)} for a in raw_rows(random.Random(2026), set(ref.company_name))]
    extra = pd.DataFrame(rows)[list(ref.columns)]
    extra["news_signal_date"] = extra.news_signal_date.map(lambda d: d.isoformat() if d else None)
    for c in ["web_visits_30d", "form_fill_30d", "job_postings_30d"]:
        extra[c] = extra[c].astype("Int64")
    extra.to_csv(os.path.join(HERE, "accounts_extra.csv"), index=False)

    both = pd.concat([ref, pd.read_csv(os.path.join(HERE, "accounts_extra.csv"), dtype={"employee_band": str})], ignore_index=True)
    rng = random.Random(11)
    def owner(a):
        u = rng.random()
        if a.goal == "Organic Growth":
            return "BDM" if u < 0.7 else "Marketing"
        if a.diamond_referral == "Yes":                    # most Diamond referrals go to SDR
            return "SDR" if u < 0.85 else "BDM"
        if a.assigned_team == "BDM":
            return "BDM" if u < 0.8 else "Marketing"
        return "SDR" if u < 0.6 else "Marketing"
    pd.DataFrame({"account_id": both.account_id, "role": [owner(a) for a in both.itertuples()]}).to_csv(os.path.join(HERE, "account_roles.csv"), index=False)

    rng = random.Random(7)                                 # same sequence as before for the first 161 Organic Growth accounts
    seats = []
    for acc in both[both.goal == "Organic Growth"].account_id:
        u = rng.random()
        n = None if u < 0.15 else 0 if u < 0.45 else rng.randint(1, 5) if u < 0.77 else rng.randint(6, 10) if u < 0.91 else rng.randint(11, 30)
        seats.append({"account_id": acc, "seats_added_6m": n})
    pd.DataFrame(seats).astype({"seats_added_6m": "Int64"}).to_csv(os.path.join(HERE, "seat_growth.csv"), index=False)
    roles = pd.read_csv(os.path.join(HERE, "account_roles.csv")).merge(both[["account_id", "goal"]])
    print(f"accounts_extra.csv: {len(extra)} accounts ({(extra.goal == 'New Logo').sum()} New Logo, {(extra.goal == 'Organic Growth').sum()} Organic Growth)")
    print("account_roles.csv:", roles.groupby(["role", "goal"]).size().to_dict())
    print(f"seat_growth.csv: {len(seats)} Organic Growth accounts, {sum(s['seats_added_6m'] is None for s in seats)} unknown")


if __name__ == "__main__":
    main()
