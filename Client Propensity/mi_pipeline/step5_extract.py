"""Step 5b: propensity extract for the Account Priority Dashboard (separate from the workbook in step5_output).

propensity_accounts is deliberately narrow: the client keys plus seat and department metrics only. The dashboard
keeps its own descriptive columns (industry, region, ...); both sides use the same taxonomy (mappings.py).
    keys        account_id = "MS-" + shortcode (Organic Growth), shortcode, crm_company_id (MyStaff 'CRM Company ID'
                = HubSpot company Record ID, as text); New Logo prospects use profile_key = industry|country
    seats       current seats, gross seats added and net change over 6 months; fit_seat_milestone* (the client's next
                seat milestone, 5 / 10 / 20, and its chance within 12 months; 20+ seats out of scope)
    departments depts_so_far(_names); fit_dept_* (enters a new department in 12 months); fit_second_dept_* (the same
                chance for one-department clients, banded among them) and likely_next_dept*
    scores      fit_* columns, kept separate from the dashboard's priority_score
Model version and as-of date are in run_info.

Files (config.OUTPUT_DIR, the local data folder outside the repo): <date>_Propensity_Extract.xlsx with every sheet,
plus CSVs of the two feed tables and of score_definitions (what each score means, its window and how good it is).
All four are also copied to config.DASHBOARD_FEED_DIR (the dashboard's local data
folder), so the dashboard reads them from its own folder."""
import shutil
from pathlib import Path

import pandas as pd

import config
from mi_pipeline import mappings
from mi_pipeline.step3_features import seat_measures
from mi_pipeline.step4_propensity import PROFILE_DISPLAY
from mi_pipeline.step5_output import _style

ACCOUNT_COLS = ["account_id", "shortcode", "crm_company_id",
                # seats
                "seats_current", "seats_current_source", "seats_added_6m_gross", "seats_change_6m_net",
                "fit_seat_milestone", "fit_seat_milestone_p", "fit_seat_milestone_band", "fit_seat_milestone_why",
                # departments
                "depts_so_far", "depts_so_far_names",
                "fit_dept_expand_p", "fit_dept_expand_band", "fit_dept_vs_peers", "fit_dept_why",
                "fit_second_dept_p", "fit_second_dept_band",
                "likely_next_dept", "likely_next_dept_by_lift",
                # new clients only
                "fit_growth_p", "fit_growth_band", "fit_growth_why", "<milestones>",
                "fit_coverage"]

DICTIONARY = [   # column, meaning, dashboard counterpart
    ("account_id", "MS-<shortcode>: the dashboard's key for MyStaff clients", "account_id"),
    ("shortcode", "MyStaff / StaffCentral client shortcode", "shortcode"),
    ("crm_company_id", "MyStaff 'CRM Company ID' = the HubSpot company Record ID, as text. Blank where MyStaff has none; a few IDs are shared by more than one client. Read the CSV with dtype=str, or blanks turn it into a float (123.0)", "crm_company_id / hubspot_record_id"),
    ("seats_current", "Cloudstaff seats today: the dashboard's cs_staff_current (MyStaff Total Staff) where it lists the client, otherwise the engagement list. See seats_current_source", "cs_staff_current"),
    ("seats_current_source", "Where seats_current comes from: dashboard | engagement list", "–"),
    ("seats_added_6m_gross", "Staff who started in the last 180 days (gross adds, includes replacements)", "seats_added_6m"),
    ("seats_change_6m_net", "Seats today minus seats 180 days ago (net change)", "(net alternative to seats_added_6m)"),
    ("fit_seat_milestone", f"The client's next seat milestone: {', '.join(str(n) for n in config.ORG_SEAT_MILESTONES)} (1-4 seats -> 5, 5-9 -> 10, 10-19 -> 20). Blank = already at {max(config.ORG_SEAT_MILESTONES)}+ seats (out of scope) or no seats", "new"),
    ("fit_seat_milestone_p", f"Chance the client reaches its next seat milestone and holds it {config.MILESTONE_HOLD_DAYS} days, within {config.PS_SEAT_GROWTH_DAYS} days of the as-of date. See score_definitions", "new"),
    ("fit_seat_milestone_band", "Low / Medium / High: thirds of past clients in the same seat range (1-4, 5-9 or 10-19), so bands compare like with like", "new"),
    ("fit_seat_milestone_why", "Top 2 traits pushing fit_seat_milestone_p up the most vs a typical client; blank = no trait stands out", "new (could feed the Why chips)"),
    ("fit_dept_expand_p", f"Department expansion: chance the client enters a department it has never had, within {config.PS_BRANCH_DAYS} days (a department counts from hire no. {config.BRANCH_MIN_HIRES}). See score_definitions", "new"),
    ("fit_dept_expand_band", "Low / Medium / High: thirds of historical client snapshots by fit_dept_expand_p", "new"),
    ("fit_dept_vs_peers", "fit_dept_expand_p / average for active clients of similar size (1.5 = 50% more likely than peers)", "new"),
    ("depts_so_far", "Departments (StaffCentral JP Categories) the client has had staff in so far, from its engagement history (Unknown categories not counted)", "new"),
    ("depts_so_far_names", "Those departments, separated by '; ' (some names contain a comma)", "new"),
    ("fit_second_dept_p", "One-department clients only (depts_so_far = 1): fit_dept_expand_p, i.e. the chance of adding a second department within 12 months", "new"),
    ("fit_second_dept_band", "Low / Medium / High: thirds of past ONE-department client snapshots by that chance, so one-department clients compare like with like (on the all-client bands most of them are Low / Medium, because more departments raise the score)", "new"),
    ("likely_next_dept", "Top 2 departments clients with the same departments added next: share of the options this client doesn't have, and lift (share / that department's usual share; 1.0x = no different from average)", "new"),
    ("likely_next_dept_by_lift", "Top 2 departments by lift (share at least 3%): the departments unusually likely for this client", "new"),
    ("fit_dept_why", "Top 2 traits pushing fit_dept_expand_p (department expansion) up the most vs a typical client; blank = no trait stands out", "new (could feed the Why chips)"),
    ("fit_growth_p", f"New clients only (under {config.PS_GROWTH_DAYS} days, launched with 1-4 staff, not yet at {config.PS_GROWTH_SEATS}): chance of reaching and holding {config.PS_GROWTH_SEATS} seats within {config.PS_GROWTH_DAYS} days of the first hire. See score_definitions", "new"),
    ("fit_growth_band", "Low / Medium / High: thirds of historical new clients by fit_growth_p", "new"),
    ("fit_reach_10_p / fit_reach_20_p", "New clients only (younger than the window, launched below N seats, not yet at N): chance of reaching and holding 10 seats within 2 years / 20 seats within 3 years of the first hire", "new"),
    ("fit_reach_10_band / fit_reach_20_band", "Low / Medium / High: thirds of historical new clients by that score", "new"),
    ("fit_growth_why / fit_reach_10_why", "Profile traits (industry, country, starting department, launch size) pushing that growth score up the most vs a typical new client; blank = no trait stands out", "new"),
    ("fit_coverage", "Why a client has no fit_seat_milestone* / fit_dept_* score: scored | no current seats | no known starting department | internal / non-client | no engagement history", "new"),
]


def _base_rate(check):
    return float((check["rows"] * check["actual_rate"]).sum() / check["rows"].sum())

def _cuts(c):
    return " / ".join(f"{x:.3f}" for x in c)

def _window(days):
    return f"{days} days (about {days / 365:.0f} year{'s' if days >= 730 else ''})"

def score_definitions(res):
    """One row per score: the question it answers, who it applies to, the exact outcome and time window, the
    assumptions, and how good the model is. Windows and rules come from config, so the text always matches the models."""
    p, today = res["propensity"], res["today"]
    dept_rule = ("a department counts as entered at its first hire" if config.BRANCH_MIN_HIRES == 1
                 else f"a department counts as entered at its {config.BRANCH_MIN_HIRES}th hire")
    dept_rule += f" (config.BRANCH_MIN_HIRES = {config.BRANCH_MIN_HIRES}); departments are StaffCentral JP Categories"
    launch = f"launch team = staff hired in the first {config.LAUNCH_DAYS} days"
    org_launch = (f"; a department first staffed within {config.ORG_DEPT_LAUNCH_DAYS} days of the client's first hire is part "
                  "of a staggered launch and never counts as added" if config.ORG_DEPT_LAUNCH_DAYS else "")
    held = f"held for at least {config.MILESTONE_HOLD_DAYS} days"
    if_signed = ("IF WE SIGN THEM: how clients like this have grown after signing, not whether they will sign. "
                 "Prospects are scored on industry and country only (launch of 1-2 staff, starting department unknown), "
                 "so every prospect in the same industry and country gets the same score.")
    new_clients = "New Logo prospects (by industry + country), and Organic Growth clients in their first year"
    rows = [
        dict(goal="Organic Growth", score="fit_dept_expand",
             columns="fit_dept_expand_p, fit_dept_expand_band, fit_dept_vs_peers, fit_dept_why, likely_next_dept, likely_next_dept_by_lift",
             question="Which existing clients are likely to branch into new departments?",
             applies_to="Active clients with at least 1 seat today and a known starting department",
             outcome=f"Enters a department it has never had, within {config.PS_BRANCH_DAYS} days of the as-of date",
             window=_window(config.PS_BRANCH_DAYS), assumptions=dept_rule + org_launch,
             base_rate=_base_rate(p["organic_check"]), auc=p["organic_auc"], band_cutoffs=_cuts(p["organic_cuts"])),
        dict(goal="Organic Growth", score="fit_second_dept",
             columns="fit_second_dept_p, fit_second_dept_band, depts_so_far, depts_so_far_names, fit_dept_why, likely_next_dept, likely_next_dept_by_lift",
             question="Which one-department clients are likely to add a second department?",
             applies_to="Active clients with exactly one department so far (depts_so_far = 1), at least 1 seat today and a known starting department",
             outcome=f"Enters a second department within {config.PS_BRANCH_DAYS} days of the as-of date",
             window=_window(config.PS_BRANCH_DAYS),
             assumptions=dept_rule + org_launch + ". The department-expansion model, banded among one-department clients only, so the "
                         "bands compare like with like; the AUC is measured within one-department clients",
             base_rate=_base_rate(p["one_dept_check"]), auc=p["one_dept_auc"], band_cutoffs=_cuts(p["one_dept_cuts"])),
        dict(goal="New Logo (and first-year clients)", score="fit_growth",
             columns="fit_growth_p, fit_growth_band, fit_growth_why",
             question=f"Which companies are likely to grow to {config.PS_GROWTH_SEATS} seats?",
             applies_to=new_clients + " that launched with 1-4 staff",
             outcome=f"Reaches {config.PS_GROWTH_SEATS}+ seats, {held}, within {config.PS_GROWTH_DAYS} days of the first hire",
             window=_window(config.PS_GROWTH_DAYS), assumptions=if_signed + " " + launch,
             base_rate=_base_rate(p["growth_check"]), auc=p["growth_auc"], auc_prospects=p["prospect_aucs"]["growth"],
             band_cutoffs=_cuts(p["scorer"].growth_cuts)),
    ]
    top = max(config.ORG_SEAT_MILESTONES)
    for n, sm in p["seat_milestones"].items():
        lo, hi = sm["seats_from"], sm["seats_to"]
        rows.insert(len([r for r in rows if r["goal"] == "Organic Growth"]) - 1, dict(
            goal="Organic Growth", score=f"fit_seat_milestone = {n}",
            columns="fit_seat_milestone, fit_seat_milestone_p, fit_seat_milestone_band, fit_seat_milestone_why",
            question=f"Which existing clients with {lo}-{hi} seats are likely to reach {n}+?",
            applies_to=f"Active clients with {lo}-{hi} seats today ({n} is their next seat milestone). Clients with {top}+ seats are out of scope",
            outcome=f"Reaches {n}+ seats and holds them {config.MILESTONE_HOLD_DAYS} days, within {config.PS_SEAT_GROWTH_DAYS} days of the as-of date",
            window=_window(config.PS_SEAT_GROWTH_DAYS),
            assumptions=(f"Seats today from the dashboard (cs_staff_current) where it lists the client, otherwise the engagement list; "
                         f"the history the model learned from is the engagement list. Bands are thirds of past clients with {lo}-{hi} "
                         "seats, so they compare like with like"),
            base_rate=_base_rate(sm["check"]), auc=sm["auc"], band_cutoffs=_cuts(sm["cuts"])))
    for ((n, d), (_, cuts)), (chk, auc) in zip(p["scorer"].milestones.items(), p["milestone_checks"].values()):
        rows.append(dict(goal="New Logo (and young clients)", score=f"fit_reach_{n}",
                         columns=f"fit_reach_{n}_p, fit_reach_{n}_band, fit_reach_{n}_why",
                         question=f"Which companies are likely to grow to {n} seats?",
                         applies_to=f"{new_clients.replace('first year', f'first {d // 365} years')} that launched below {n} seats",
                         outcome=f"Reaches {n}+ seats, {held}, within {d} days of the first hire",
                         window=_window(d), assumptions=if_signed + " " + launch,
                         base_rate=_base_rate(chk), auc=auc, auc_prospects=p["prospect_aucs"].get((n, d)),
                         band_cutoffs=_cuts(cuts)))
    rows.append(dict(goal="New Logo", score="fit_branch_1y",
                     columns="fit_branch_1y_p, fit_branch_1y_band, fit_branch_1y_why, likely_first_new_dept, fit_outlook",
                     question="Which companies are likely to branch into new departments?",
                     applies_to="New Logo prospects (by industry + country)",
                     outcome=f"Adds a department that was not in its launch team within {config.PS_BRANCH_DAYS} days of "
                             "the first hire (a client that leaves earlier counts as no)",
                     window=_window(config.PS_BRANCH_DAYS), assumptions=if_signed + " " + launch + "; " + dept_rule,
                     base_rate=_base_rate(p["branch_check"]), auc=p["branch_auc"], auc_prospects=p["prospect_aucs"]["branch"],
                     band_cutoffs=_cuts(p["scorer"].branch_cuts)))
    t = pd.DataFrame(rows)
    t["how_to_read"] = ("_p = estimated chance (0-1). _band: Low / Medium / High = thirds of past clients by score, so "
                        "High means top third, not a fixed chance; band_cutoffs = the scores between the bands. base_rate = "
                        "how often it happened to past clients. AUC: 0.5 = coin flip, 0.7+ = useful; cross-validated on past "
                        "clients. auc_prospects: the same model scored the way prospects are (industry and country only), "
                        "the better guide for New Logo rows")
    t["auc_prospects"] = t.get("auc_prospects")
    t["base_rate"], t["auc"], t["auc_prospects"] = t["base_rate"].round(3), t["auc"].round(3), t["auc_prospects"].astype(float).round(3)
    t["as_of"], t["model_version"] = str(today.date()), config.MODEL_VERSION
    return t[["goal", "score", "question", "applies_to", "outcome", "window", "assumptions", "base_rate", "auc", "auc_prospects",
              "band_cutoffs", "columns", "how_to_read", "as_of", "model_version"]]


def build_extract(res):
    today, feat, prop = res["today"], res["features"], res["propensity"]
    ms = feat["mystaff"].drop_duplicates("Shortcode").copy()
    active = ms["Active"].astype("string").str.strip().str.lower().eq("yes").fillna(False)
    test = ms["Client"].astype("string").str.contains(config.TEST_ACCOUNT_PATTERN, case=False, regex=True).fillna(False)
    uni = ms[active & ~test].set_index("Shortcode")

    out = pd.DataFrame(index=uni.index)
    out["account_id"] = "MS-" + out.index.astype(str)
    out["shortcode"] = out.index.astype(str)
    out["crm_company_id"] = uni["crm_company_id"].astype("string")   # an ID, not a number: text, never 1.23E+10 or 123.0
    out = out.join(seat_measures(out.index, feat["timeline"], feat["src"], today))
    dash = res["formatted"].get("current_seats")
    out["seats_current_source"] = "engagement list"
    if dash is not None:
        d = dash.reindex(out.index.astype(str)).set_axis(out.index)
        out.loc[d.notna(), "seats_current_source"] = "dashboard"
        out["seats_current"] = d.fillna(out["seats_current"]).astype(int)

    lst = prop["organic_client_list"].set_index("Shortcode")
    out["fit_dept_expand_p"]    = lst["p_new_dept_12m"]
    out["fit_dept_expand_band"] = lst["band"].astype("string")
    out["fit_dept_vs_peers"]    = lst["vs_peers"]
    out["fit_dept_why"]         = lst["why"]
    out["depts_so_far"]         = lst["n_depts"].astype("Int64")
    out["depts_so_far_names"]   = lst["current_depts"]
    out["fit_second_dept_p"]    = lst["p_second_dept"]
    out["fit_second_dept_band"] = lst["band_second_dept"].astype("string")
    out["likely_next_dept"]     = lst["likely_next_dept"]
    out["likely_next_dept_by_lift"] = lst["likely_next_dept_by_lift"]
    out["fit_seat_milestone"]      = lst["next_seat_milestone"].astype("Int64")
    out["fit_seat_milestone_p"]    = lst["p_next_seat_milestone"]
    out["fit_seat_milestone_band"] = lst["band_next_seat_milestone"].astype("string")
    out["fit_seat_milestone_why"]  = lst["why_next_seat_milestone"]

    acc = feat["accounts"]
    new = acc[(acc["days_observed"] < config.PS_GROWTH_DAYS) & acc["launch_bucket"].isin(["1-2", "3-4"])
              & acc[f"days_till_{config.PS_GROWTH_SEATS}_headcount"].isna()]
    g = prop["scorer"].score_profiles(new[PROFILE_DISPLAY])
    out["fit_growth_p"]    = g["p_growth"]
    out["fit_growth_band"] = g["growth_band"].astype("string")
    out["fit_growth_why"]  = g["growth_why"]
    ms_cols = []
    for (n, d), (m, cuts) in prop["scorer"].milestones.items():
        elig = acc[(acc["days_observed"] < d) & (acc["launch_size"] < n) & acc["launch_bucket"].notna()
                   & acc[f"days_till_{n}_headcount"].isna()]
        gm = prop["scorer"].score_profiles(elig[PROFILE_DISPLAY])
        out[f"fit_reach_{n}_p"] = gm[f"p_reach_{n}_{d}d"]
        out[f"fit_reach_{n}_band"] = gm[f"band_reach_{n}_{d}d"].astype("string")
        out[f"fit_reach_{n}_why"] = gm[f"why_reach_{n}_{d}d"]
        ms_cols += [f"fit_reach_{n}_p", f"fit_reach_{n}_band", f"fit_reach_{n}_why"]

    in_summary = out.index.isin(feat["summary"]["Shortcode"])
    in_accounts = out.index.isin(acc.index)
    no_start = out.index.isin(acc.index[acc["start_dept"].isna()])
    out["fit_coverage"] = "scored"
    out.loc[~out.index.isin(lst.index), "fit_coverage"] = "no current seats"
    out.loc[no_start, "fit_coverage"] = "no known starting department"
    out.loc[in_summary & ~in_accounts, "fit_coverage"] = "internal / non-client"
    out.loc[~in_summary, "fit_coverage"] = "no engagement history"
    cols = [c for x in ACCOUNT_COLS for c in (ms_cols if x == "<milestones>" else [x])]
    accounts = out.reset_index(drop=True)[cols].sort_values("fit_dept_expand_p", ascending=False, na_position="last").round(3)

    fit_map = feat["industry_fit_map"]
    n_acc = acc["industry"].value_counts()
    levels = pd.DataFrame({"industry": list(mappings.INDUSTRY_SECTOR),
                           "industry_sector": list(mappings.INDUSTRY_SECTOR.values())})
    levels["client_accounts"] = levels["industry"].map(n_acc).fillna(0).astype(int)
    levels["model_level"] = levels["industry"].map(fit_map)
    regions = (uni.groupby("region", dropna=False).size().rename("active_clients").reset_index()
                  .assign(country=lambda d: d["region"].map(mappings.region_to_country)))
    regions["region"] = regions["region"].astype("string").fillna("(blank)")

    p = prop
    run_info = pd.DataFrame([
        ("model_version", config.MODEL_VERSION), ("as_of", str(today.date())),
        *[(f"source_{k}", f"{config.RAW_FILES[k][0]} (extract {config.EXTRACT_SOURCE_DATES.get(k, '?')})") for k in config.RAW_FILES],
        ("train_years", config.PS_TRAIN_YEARS),
        ("auc_fit_dept_expand (existing clients)", round(p["organic_auc"], 3)),
        ("auc_fit_growth (new clients)", round(p["growth_auc"], 3)),
        ("auc_fit_branch_1y (new clients)", round(p["branch_auc"], 3)),
        *[(f"auc_fit_seat_milestone_{n} (existing clients, {sm['seats_from']}-{sm['seats_to']} seats)", round(sm["auc"], 3))
          for n, sm in p["seat_milestones"].items()],
        *[(f"auc {k}", round(a, 3)) for k, (_, a) in p["milestone_checks"].items()],
        *[(f"band_cutoffs_fit_seat_milestone_{n}", " / ".join(f"{c:.3f}" for c in sm["cuts"])) for n, sm in p["seat_milestones"].items()],
        ("band_cutoffs_fit_dept_expand", " / ".join(f"{c:.3f}" for c in p["organic_cuts"])),
        ("auc_fit_second_dept (one-department clients)", round(p["one_dept_auc"], 3)),
        ("band_cutoffs_fit_second_dept", " / ".join(f"{c:.3f}" for c in p["one_dept_cuts"])),
        ("band_cutoffs_fit_growth", " / ".join(f"{c:.3f}" for c in p["scorer"].growth_cuts)),
        ("band_cutoffs_fit_branch_1y", " / ".join(f"{c:.3f}" for c in p["scorer"].branch_cuts)),
        ("industry_sector_fallback_n", config.INDUSTRY_SECTOR_FALLBACK_N),
        ("prospect_profile_assumptions", "starting department Unknown, launch 1-2 staff"),
        ("branch_min_hires", config.BRANCH_MIN_HIRES),
        ("seat_milestones", ", ".join(str(n) for n in config.ORG_SEAT_MILESTONES)),
        ("current_seats_source", f"{config.CURRENT_SEATS_SOURCE}: {res['formatted'].get('current_seats_file') or 'engagement list'}"),
        *[(f"auc_prospect_style {k if isinstance(k, str) else f'reach_{k[0]}'}", round(v, 3)) for k, v in p["prospect_aucs"].items()],
        ("seat_milestone_window_days", config.PS_SEAT_GROWTH_DAYS),
        ("dept_window_days", config.PS_BRANCH_DAYS),
    ], columns=["item", "value"])
    dictionary = pd.DataFrame(DICTIONARY, columns=["column", "meaning", "dashboard_counterpart"])
    return {"propensity_accounts": accounts, "prospect_profiles": p["prospect_profiles"],
            "score_definitions": score_definitions(res), "industry_levels": levels,
            "region_to_country": regions, "column_dictionary": dictionary, "run_info": run_info}


def write_extract(res, folder=None):
    sheets = build_extract(res)
    folder = folder or config.OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{res['today'].date()}_Propensity_Extract"
    xlsx = folder / f"{stem}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            _style(xw.sheets[name], df)
    files = [xlsx]
    for name in ("propensity_accounts", "prospect_profiles", "score_definitions"):
        files.append(folder / f"{stem}_{name}.csv")
        sheets[name].to_csv(files[-1], index=False, encoding="utf-8-sig")
    copy_to_dashboard(files)
    return xlsx, sheets


def copy_to_dashboard(files, feed=None):
    """Copies the extract files into the dashboard's local data folder (config.DASHBOARD_FEED_DIR), if set."""
    feed = feed or config.DASHBOARD_FEED_DIR
    if feed is None or not Path(feed).is_dir():
        return []
    feed = Path(feed)
    copied = [Path(shutil.copy2(f, feed / f.name)) for f in files if f.parent.resolve() != feed.resolve()]
    if copied:
        print(f"[5b extract] copied {len(copied)} files to the dashboard data folder: {feed}")
    return copied
