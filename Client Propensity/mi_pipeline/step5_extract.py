"""Step 5b: propensity extract for the Account Priority Dashboard (separate from the workbook in step5_output).

propensity_accounts is deliberately narrow: the dashboard's key plus seat and department metrics only. The dashboard
keeps its own descriptive columns (industry, region, CRM ID, ...); both sides use the same taxonomy (mappings.py).
    keys        account_id = "MS-" + shortcode (Organic Growth); New Logo prospects use profile_key = industry|country
    seats       current seats, gross seats added and net change over 6 months; fit_seat_* (more seats in 12 months)
    departments fit_dept_* (enters a new department in 12 months) and likely_next_dept*
    scores      fit_* columns, kept separate from the dashboard's priority_score
Model version and as-of date are in run_info.

Files (config.OUTPUT_DIR, the local data folder outside the repo): <date>_Propensity_Extract.xlsx with every sheet,
plus CSVs of the two feed tables. All three are also copied to config.DASHBOARD_FEED_DIR (the dashboard's local data
folder), so the dashboard reads them from its own folder."""
import shutil
from pathlib import Path

import pandas as pd

import config
from mi_pipeline import mappings
from mi_pipeline.step3_features import seat_measures
from mi_pipeline.step4_propensity import PROFILE_DISPLAY
from mi_pipeline.step5_output import _style

ACCOUNT_COLS = ["account_id", "shortcode",
                # seats
                "seats_current", "seats_added_6m_gross", "seats_change_6m_net",
                "fit_seat_growth_p", "fit_seat_growth_band", "fit_seat_vs_peers", "fit_seat_why",
                # departments
                "fit_dept_expand_p", "fit_dept_expand_band", "fit_dept_vs_peers", "fit_dept_why",
                "likely_next_dept", "likely_next_dept_by_lift",
                # new clients only
                "fit_growth_p", "fit_growth_band", "fit_growth_why", "<milestones>",
                "fit_coverage"]

DICTIONARY = [   # column, meaning, dashboard counterpart
    ("account_id", "MS-<shortcode>: the dashboard's key for MyStaff clients", "account_id"),
    ("shortcode", "MyStaff / StaffCentral client shortcode", "shortcode"),
    ("seats_current", "Cloudstaff seats on the as-of date (engagement list)", "cs_staff_current"),
    ("seats_added_6m_gross", "Staff who started in the last 180 days (gross adds, includes replacements)", "seats_added_6m"),
    ("seats_change_6m_net", "Seats today minus seats 180 days ago (net change)", "(net alternative to seats_added_6m)"),
    ("fit_seat_growth_p", "Chance the client has more seats 12 months from now than today (net growth: backfills don't count)", "new (complements seats_added_6m)"),
    ("fit_seat_growth_band", "Low / Medium / High: thirds of historical client snapshots by fit_seat_growth_p", "new"),
    ("fit_seat_vs_peers", "fit_seat_growth_p / average for active clients of similar size", "new"),
    ("fit_seat_why", "Top 2 traits pushing fit_seat_growth_p (seat growth) up the most vs a typical client; blank = no trait stands out", "new (could feed the Why chips)"),
    ("fit_dept_expand_p", "Department expansion: chance the client enters a department it has never had, in the next 12 months", "new"),
    ("fit_dept_expand_band", "Low / Medium / High: thirds of historical client snapshots by fit_dept_expand_p", "new"),
    ("fit_dept_vs_peers", "fit_dept_expand_p / average for active clients of similar size (1.5 = 50% more likely than peers)", "new"),
    ("likely_next_dept", "Top 2 departments clients with the same departments added next: share of the options this client doesn't have, and lift (share / that department's usual share; 1.0x = no different from average)", "new"),
    ("likely_next_dept_by_lift", "Top 2 departments by lift (share at least 3%): the departments unusually likely for this client", "new"),
    ("fit_dept_why", "Top 2 traits pushing fit_dept_expand_p (department expansion) up the most vs a typical client; blank = no trait stands out", "new (could feed the Why chips)"),
    ("fit_growth_p", "New clients only (under a year, launched with 1-4 staff, not yet at 5): chance of reaching and holding 5 seats within a year of the first hire", "new"),
    ("fit_growth_band", "Low / Medium / High: thirds of historical new clients by fit_growth_p", "new"),
    ("fit_reach_10_p / fit_reach_20_p", "New clients only (younger than the window, launched below N seats, not yet at N): chance of reaching and holding 10 seats within 2 years / 20 seats within 3 years of the first hire", "new"),
    ("fit_reach_10_band / fit_reach_20_band", "Low / Medium / High: thirds of historical new clients by that score", "new"),
    ("fit_growth_why / fit_reach_10_why", "Profile traits (industry, country, starting department, launch size) pushing that growth score up the most vs a typical new client; blank = no trait stands out", "new"),
    ("fit_coverage", "Why a client has no fit_seat_* / fit_dept_* score: scored | no current seats | no known starting department | internal / non-client | no engagement history", "new"),
]


def build_extract(res):
    today, feat, prop = res["today"], res["features"], res["propensity"]
    ms = feat["mystaff"].drop_duplicates("Shortcode").copy()
    active = ms["Active"].astype("string").str.strip().str.lower().eq("yes").fillna(False)
    test = ms["Client"].astype("string").str.contains(config.TEST_ACCOUNT_PATTERN, case=False, regex=True).fillna(False)
    uni = ms[active & ~test].set_index("Shortcode")

    out = pd.DataFrame(index=uni.index)
    out["account_id"] = "MS-" + out.index.astype(str)
    out["shortcode"] = out.index.astype(str)
    out = out.join(seat_measures(out.index, feat["timeline"], feat["src"], today))

    lst = prop["organic_client_list"].set_index("Shortcode")
    out["fit_dept_expand_p"]    = lst["p_new_dept_12m"]
    out["fit_dept_expand_band"] = lst["band"].astype("string")
    out["fit_dept_vs_peers"]    = lst["vs_peers"]
    out["fit_dept_why"]         = lst["why"]
    out["likely_next_dept"]     = lst["likely_next_dept"]
    out["likely_next_dept_by_lift"] = lst["likely_next_dept_by_lift"]
    out["fit_seat_growth_p"]    = lst["p_seat_growth_12m"]
    out["fit_seat_growth_band"] = lst["seat_growth_band"].astype("string")
    out["fit_seat_vs_peers"]    = lst["seat_vs_peers"]
    out["fit_seat_why"]         = lst["seat_why"]

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
        ("auc_fit_seat_growth (existing clients)", round(p["seat_auc"], 3)),
        *[(f"auc {k}", round(a, 3)) for k, (_, a) in p["milestone_checks"].items()],
        ("band_cutoffs_fit_seat_growth", " / ".join(f"{c:.3f}" for c in p["seat_cuts"])),
        ("band_cutoffs_fit_dept_expand", " / ".join(f"{c:.3f}" for c in p["organic_cuts"])),
        ("band_cutoffs_fit_growth", " / ".join(f"{c:.3f}" for c in p["scorer"].growth_cuts)),
        ("band_cutoffs_fit_branch_1y", " / ".join(f"{c:.3f}" for c in p["scorer"].branch_cuts)),
        ("industry_sector_fallback_n", config.INDUSTRY_SECTOR_FALLBACK_N),
        ("prospect_profile_assumptions", "starting department Unknown, launch 1-2 staff"),
    ], columns=["item", "value"])
    dictionary = pd.DataFrame(DICTIONARY, columns=["column", "meaning", "dashboard_counterpart"])
    return {"propensity_accounts": accounts, "prospect_profiles": p["prospect_profiles"], "industry_levels": levels,
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
    for name in ("propensity_accounts", "prospect_profiles"):
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
