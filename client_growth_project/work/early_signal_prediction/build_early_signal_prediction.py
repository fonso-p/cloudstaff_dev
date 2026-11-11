"""Build the Early Signals of Account Growth workbook (Cloudstaff-branded, QA-gated).

Reads   data/Organic rate/SC Engagement List (Raw Data tab, as received) and the results saved by the notebook
        notebooks/early_signal_prediction.ipynb in data/early_signal_prediction/ (features, backtest metrics, drivers, watch list).
Writes  outputs/excel/<YYYY-MM-DD>_Early_Signals_of_Account_Growth.xlsx

Counts and rates (targets, cohorts, single signals, test-year populations) are live formulas on Raw Data and are checked against
pandas. Model metrics, bootstrap ranges, odds ratios, SHAP values and scores cannot be Excel formulas: they are computed in Python
by the notebook and stored as values; each such table says so in its note (same approach as the High-Growth Account Profile).
Run from the project root:  CS_QA_DIR=qa python work/early_signal_prediction/build_early_signal_prediction.py
"""
import datetime as dt
import json
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "cs-data-analytics", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cs_xl import CSWorkbook, const, num             # noqa: E402
from profile_data import load_source, row_issues     # noqa: E402
import stats_helpers as st                           # noqa: E402
import esp_data as E                                 # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else f"outputs/excel/{dt.date.today():%Y-%m-%d}_Early_Signals_of_Account_Growth.xlsx"
RES = "data/early_signal_prediction"
X = f"DATE({E.EXTRACT.year},{E.EXTRACT.month},{E.EXTRACT.day})"
YEARS_A, YEARS_B = [2022, 2023, 2024, 2025], [2022, 2023, 2024]
MODELS = ["Baseline: base rate", "Single signal: staff at day 90", "Logistic regression", "Elastic net logistic", "Random forest", "LightGBM", "XGBoost",
          "Auto-selected + calibrated"]


def cx(text):
    """Mark method constants in narrative text with const(); live {{...}} tokens untouched."""
    parts = re.split(r"(\{\{.+?\}\}|\[\[.+?\]\])", text)
    return "".join(x if x.startswith(("{{", "[[")) else re.sub(r"\d+(\.\d+)?%?", lambda m: const(m.group()), x) for x in parts)


def lc(text):
    """Lower-case only the first letter (keeps RTG, AMER and similar names intact)."""
    return text[:1].lower() + text[1:]


def R(name):
    return pd.read_csv(f"{RES}/{name}.csv", keep_default_na=False, na_values=[""])


# ---------------------------------------------------------------- 1 load raw + notebook results
df, meta = load_source(E.STAFF_SRC)
issues = row_issues(df, required=["CSID", "Shortcode", "Engagement Date"], dates=["Engagement Date", "Disengagement Date"],
                    custom=[("Disengagement Date before Engagement Date",
                             lambda r: isinstance(r["Disengagement Date"], dt.datetime) and isinstance(r["Engagement Date"], dt.datetime)
                             and r["Disengagement Date"] < r["Engagement Date"])])
s, stv, prof = E.stints(df)
f = R("features").set_index("shortcode")
pooledA, pooledB, yearA, yearB = R("pooledA"), R("pooledB"), R("yearA"), R("yearB")
diffA, diffB, sens, drivers, imp, calA, watch, chosenA = R("diffA"), R("diffB"), R("sens"), R("drivers"), R("imp"), R("calA"), R("watch"), R("chosenA")
calYear, beatsA, ruleA = R("calYear"), R("beatsA"), R("ruleA")
meta_r = json.load(open(f"{RES}/meta.json"))
assert set(f.index) == set(prof["shortcode"]), "features out of date: re-run the notebook"
include = ["Y" if x else "N" for x in s["include"]]

# one client row per in-scope client (first included row in file order); client-level values sit on that row only
first_pos = s[s["include"]].groupby("sc")["pos"].min()
client_row = [None] * len(df)
for p in first_pos.values:
    client_row[int(p)] = "Y"
sc_of = s["sc"].values


def on_cr(col, conv=None):
    out = []
    for i in range(len(df)):
        if client_row[i] != "Y":
            out.append(None)
            continue
        v = f.at[sc_of[i], col]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out.append(None)
        else:
            out.append(conv(v) if conv else (int(v) if isinstance(v, (np.integer,)) else v))
    return out


fn_counts = f[f["elig_A"]]["initial_function"].value_counts()
FN_KEEP = set(fn_counts[fn_counts >= 30].index)
f["initial_function_group"] = f["initial_function"].where(f["initial_function"].isin(FN_KEEP), "Other (under 30 clients)")
watch_p = watch.set_index("shortcode")["p_5_in_12m"]
f["score_A"] = watch_p.reindex(f.index)
start_by_sc = pd.to_datetime(f["start_date"])

CR = '{Client Row}="Y"'
INC = 'raw_Include,"Y"'


def seats_f(cp):
    """Staff on the books on day cp: valid stints with Engagement Date <= cp <= Disengagement Date, or still open."""
    return (f'COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Valid_Stint,"Y",raw_Engagement_Date,"<="&{cp},raw_Disengagement_Date,">="&{cp},{INC})'
            f'+COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Engagement_Date,"<="&{cp},raw_Disengagement_Date,"",{INC})')


def early(extra):
    return f'COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Valid_Stint,"Y"{extra},{INC})'


derived = {
    "Client Start": {"values": [s["start"].iat[i].to_pydatetime() if s["include"].iat[i] else None for i in range(len(df))], "format": "yyyy-mm-dd",
                     "rule": "Client's first valid Engagement Date (approved client growth prep, commit 1bbef51); filled on in-scope rows"},
    "Day From Start": {"formula": '=IF({Include}="Y",{Engagement Date}-{Client Start},"")', "format": "0"},
    "Valid Stint": {"formula": '=IF(OR({Disengagement Date}="",{Disengagement Date}>={Engagement Date}),"Y","N")'},
    "Client Row": {"values": client_row, "rule": "Y on one row per in-scope client (first in file order); client-level columns are filled on this row only"},
    "Start Year": {"formula": f'=IF({CR},YEAR({{Client Start}}),"")', "format": "0"},
    "Start Quarter": {"formula": f'=IF({CR},"Q"&ROUNDUP(MONTH({{Client Start}})/3,0),"")'},
    "Client Age (days)": {"formula": f'=IF({CR},{X}-{{Client Start}},"")', "format": "0"},
    "Region": {"values": on_cr("region"), "rule": "MyStaff (2) Region, EMEA folded into AMER, OPTI divisions as OPTI (approved client growth prep)"},
    "Initial Function": {"values": on_cr("initial_function"), "rule": "Most common known function among stints starting in the first 30 days (role titles from the billed report)"},
    "Initial Function Group": {"values": on_cr("initial_function_group"), "rule": "Initial Function if 30+ target-A clients have it, else 'Other (under 30 clients)'"},
    "Staff Day 90": {"formula": f'=IF({CR},{seats_f("({Client Start}+90)")},"")', "format": "0"},
    "Staff Day 365": {"formula": f'=IF({CR},{seats_f("({Client Start}+365)")},"")', "format": "0"},
    "Staff Day 730": {"formula": f'=IF({CR},{seats_f("({Client Start}+730)")},"")', "format": "0"},
    "Starts by Day 90": {"formula": f'=IF({CR},{early(",raw_Day_From_Start,\"<90\"")},"")', "format": "0"},
    "Adds Days 31-90": {"formula": f'=IF({CR},{early(",raw_Day_From_Start,\">=30\",raw_Day_From_Start,\"<90\"")},"")', "format": "0"},
    "Second Start by Day 90": {"formula": f'=IF({CR},IF({{Starts by Day 90}}>=2,1,0),"")', "format": "0"},
    "Leavers by Day 90": {"formula": f'=IF({CR},{early(",raw_Disengagement_Date,\"<\"&({Client Start}+90)")},"")', "format": "0"},
    "Functions by Day 90": {"values": on_cr("functions_d90"), "format": "0", "rule": "Distinct known functions among stints starting in the first 90 days"},
    "Peak Staff by Day 90": {"values": on_cr("peak_d90"), "format": "0", "rule": "Most staff on the books on any day from day 0 to day 90 (event sweep)"},
    "Days to 5": {"values": on_cr("days_to_5"), "format": "0", "rule": "Days from first start to the first day with 5 staff at the same time (approved client growth prep)"},
    "Days to 10": {"values": on_cr("days_to_10"), "format": "0", "rule": "Days from first start to the first day with 10 staff at the same time"},
    "Eligible A": {"formula": f'=IF({CR},IF(AND({{Client Age (days)}}>=365,OR({{Days to 5}}="",{{Days to 5}}>90)),1,0),"")', "format": "0"},
    "Reached 5 in 12m": {"formula": f'=IF({CR},IF(AND({{Days to 5}}<>"",{{Days to 5}}<=365),1,0),"")', "format": "0"},
    "Eligible B": {"formula": f'=IF({CR},IF(AND({{Client Age (days)}}>=730,OR({{Days to 10}}="",{{Days to 10}}>90)),1,0),"")', "format": "0"},
    "Reached 10 in 24m": {"formula": f'=IF({CR},IF(AND({{Days to 10}}<>"",{{Days to 10}}<=730),1,0),"")', "format": "0"},
    "Eligible C": {"formula": f'=IF({CR},IF(AND({{Client Age (days)}}>=730,{{Days to 5}}<>"",{{Days to 5}}<=365),1,0),"")', "format": "0"},
    "Kept Expanding": {"formula": f'=IF({CR},IF({{Staff Day 730}}>{{Staff Day 365}},1,0),"")', "format": "0"},
    "Watch List": {"formula": f'=IF({CR},IF(AND({{Client Age (days)}}>=90,{{Client Age (days)}}<365),1,0),"")', "format": "0"},
    "Chance of 5 in 12m (model)": {"values": on_cr("score_A"), "format": "0.0%",
                                   "rule": "Watch-list clients only: final auto-selected, calibrated model for target A (notebook step 12)"},
}

wb = CSWorkbook("Early Signals of Account Growth", prepared_by="Jo Bert (Jobs) Olinares", requested_by="Jo Bert (Jobs) Olinares",
                period=f"Client starts Jan 2020 to Sep 2026; data to {E.EXTRACT:%d %b %Y}")
wb.add_raw_data(df, meta, issues=issues, include=include, required=["CSID", "Shortcode", "Engagement Date"], derived=derived)
COL = wb.col
CRW, YR, QTR, REG, FNG = COL("Client Row"), COL("Start Year"), COL("Start Quarter"), COL("Region"), COL("Initial Function Group")
S90, ADD, SEC, LEA, FUN = COL("Staff Day 90"), COL("Adds Days 31-90"), COL("Second Start by Day 90"), COL("Leavers by Day 90"), COL("Functions by Day 90")
EL = {"A": COL("Eligible A"), "B": COL("Eligible B"), "C": COL("Eligible C")}
YY = {"A": COL("Reached 5 in 12m"), "B": COL("Reached 10 in 24m"), "C": COL("Kept Expanding")}
WL = COL("Watch List")


def wlo(k, n):
    return "=MAX(0," + st.WILSON_LO.format(k=k, n=n)[1:] + ")"


def whi(k, n):
    return "=MIN(1," + st.WILSON_HI.format(k=k, n=n)[1:] + ")"


def wil(k, n):
    lo, hi = st.wilson_ci(k, n)
    return max(0.0, lo), min(1.0, hi)


# ---------------------------------------------------------------- 2 targets and cohorts (formulas)
sh = wb.add_tab("Targets and Cohorts", explanation=cx(
    "Who each target covers and how often it happened, by the year the client started. Target A: 5 staff at the same time within 12 months, "
    "for clients aged 12+ months that had not reached 5 by day 90. Target B: 10 within 24 months, for clients aged 24+ months not at 10 by day 90. "
    "Target C: still growing from month 12 to month 24, for clients that reached 5 in their first year. Clients too young are left out."))
TT = {}
for t, lab in [("A", "Target A: reached 5 within 12 months"), ("B", "Target B: reached 10 within 24 months"), ("C", "Target C: kept expanding after reaching 5")]:
    e = f[f[f"elig_{t}"]]
    years = sorted(e["start_year"].unique())
    body, exp = [], []
    for y in years:
        g = e[e["start_year"] == y]
        k, n = int(g[f"y_{t}"].sum()), len(g)
        crit = f'{CRW},"Y",{EL[t]},1,{YR},A{{r}},{INC}'
        body.append([int(y), f"=COUNTIFS({crit})", f"=COUNTIFS({crit},{YY[t]},1)", "=IFERROR(C{r}/B{r},0)", wlo("C{r}", "B{r}"), whi("C{r}", "B{r}")])
        exp.append([None, n, k, k / n, *wil(k, n)])
    K, Nn = int(e[f"y_{t}"].sum()), len(e)
    TT[t] = sh.add_table(f"tgt_{t}", lab, ["Start year", "Eligible clients", "Reached the target", "Rate", "95% range (low)", "95% range (high)"], body,
                         formats=["0", "#,##0", "#,##0", "0.0%", "0.0%", "0.0%"], expected=exp,
                         total={"label": "All cohorts", "cells": {"Eligible clients": "=SUM({c:Eligible clients}{first}:{c:Eligible clients}{last})",
                                                                   "Reached the target": "=SUM({c:Reached the target}{first}:{c:Reached the target}{last})",
                                                                   "Rate": "=IFERROR(C{r}/B{r},0)"}},
                         expected_total=[None, Nn, K, K / Nn, None, None],
                         note="Source: Raw Data client rows (Client Row = Y, Include = Y). 95% range = Wilson score interval.",
                         n_col="Eligible clients", min_n=30,
                         reconcile={"Eligible clients": f'=COUNTIFS({CRW},"Y",{EL[t]},1,{INC})', "Reached the target": f'=COUNTIFS({CRW},"Y",{EL[t]},1,{YY[t]},1,{INC})'})
    if t == "A":
        sh.add_chart(TT[t], kind="col", cats="Start year", values=["Rate"], title="Target A rate by start year", y_format="0%")

# ---------------------------------------------------------------- 3 single early signals for target A (formulas)
eA = f[f["elig_A"]]
LEVELS = []                     # (label, excel extra criteria, pandas mask, signal)
for v in range(4):
    LEVELS.append((f"Staff at day 90: {v}", f',{S90},{v}', eA["seats_d90"] == v, "Staff at day 90"))
LEVELS.append(("Staff at day 90: 4", f',{S90},">=4"', eA["seats_d90"] >= 4, "Staff at day 90"))
for lab, col, crit_y, crit_n, m in [("Staff added in days 31-90", ADD, '">0"', "0", eA["adds_d31_90"] > 0),
                                    ("Second start within 90 days", SEC, "1", "0", eA["second_start_by_d90"] == 1),
                                    ("Any leaver by day 90", LEA, '">0"', "0", eA["leavers_d90"] > 0),
                                    ("2+ functions by day 90", FUN, '">=2"', '"<2"', eA["functions_d90"] >= 2)]:
    LEVELS.append((f"{lab}: No", f",{col},{crit_n}", ~m, lab))
    LEVELS.append((f"{lab}: Yes", f",{col},{crit_y}", m, lab))
for r in E.REGIONS:
    LEVELS.append((f"Region: {r}", f',{REG},"{r}"', eA["region"] == r, "Region"))
for g in sorted(f.loc[f["elig_A"], "initial_function_group"].unique(), key=lambda x: (x.startswith("Other"), x)):
    LEVELS.append((f"Initial function: {g}", f',{FNG},"{g}"', eA["initial_function_group"] == g, "Initial function"))
for q in ["Q1", "Q2", "Q3", "Q4"]:
    LEVELS.append((f"Start quarter: {q}", f',{QTR},"{q}"', eA["start_quarter"] == q, "Start quarter"))
pvals = {}
for sig in dict.fromkeys(x[3] for x in LEVELS):
    tab = [[int(eA.loc[m, "y_A"].sum()), int((~eA.loc[m, "y_A"].astype(bool)).sum())] for _, _, m, sg in LEVELS if sg == sig]
    pvals[sig] = st.chi_square(tab)["p_value"]
body, exp = [], []
for lab, xc, m, sig in LEVELS:
    crit = f'{CRW},"Y",{EL["A"]},1{xc},{INC}'
    k, n = int(eA.loc[m, "y_A"].sum()), int(m.sum())
    body.append([lab, f"=COUNTIFS({crit})", f"=COUNTIFS({crit},{YY['A']},1)", "=IFERROR(C{r}/B{r},0)", wlo("C{r}", "B{r}"), whi("C{r}", "B{r}"), pvals[sig]])
    exp.append([None, n, k, k / n if n else 0, *wil(k, n), pvals[sig]])
sh = wb.add_tab("Early Signals", explanation=cx(
    "The plain view before any model: of the target-A clients, the share that reached 5 within 12 months for each early signal on its own. "
    "Each signal has a chi-square test across its levels; p < 0.05 means the rates differ by more than chance. Signals are related to each "
    "other (for example more staff and more functions), so the Drivers tab shows each one with the others held fixed."))
T_SIG = sh.add_table("signals", "Reached 5 within 12 months, by early signal (target A clients)",
                     ["Early signal", "Clients", "Reached 5 in 12 months", "Rate", "95% range (low)", "95% range (high)", "p-value (signal)"], body,
                     formats=[None, "#,##0", "#,##0", "0.0%", "0.0%", "0.0%", "0.0000"], expected=exp, static_cols=["p-value (signal)"],
                     note="Counts and rates are formulas on Raw Data client rows (Eligible A = 1). p-value = chi-square test of independence across the signal's levels, "
                          "computed in Python (stats_helpers.chi_square) at build time. Groups under 30 clients are flagged; do not rank them.",
                     n_col="Clients", min_n=30)

# ---------------------------------------------------------------- 4 model comparison (Python values)
COMP_COLS = ["Model", "Test-year clients", "Positives", "ROC AUC", "ROC AUC 95% low", "ROC AUC 95% high", "PR AUC", "PR AUC 95% low", "PR AUC 95% high",
             "Accuracy", "Balanced accuracy", "Precision", "Recall", "F1", "Specificity", "Brier score", "Top 20% capture"]
KEYS = ["roc_auc", "roc_auc_lo", "roc_auc_hi", "pr_auc", "pr_auc_lo", "pr_auc_hi", "accuracy", "balanced_accuracy", "precision", "recall", "f1",
        "specificity", "brier", "capture_top20_per_year"]


def comp_table(sh_, key, title, pooled, t, years):
    crit = f'{CRW},"Y",{EL[t]},1,{YR},">={min(years)}",{YR},"<={max(years)}",{INC}'
    e = f[f[f"elig_{t}"] & f["start_year"].isin(years)]
    body, exp = [], []
    pp = pooled.set_index("model")
    for mdl in MODELS:
        vals = [None if pd.isna(pp.at[mdl, k]) else float(pp.at[mdl, k]) for k in KEYS]
        body.append([mdl, f"=COUNTIFS({crit})", f"=COUNTIFS({crit},{YY[t]},1)"] + vals)
        exp.append([None, len(e), int(e[f"y_{t}"].sum())] + vals)
    return sh_.add_table(key, title, COMP_COLS, body, formats=[None, "#,##0", "#,##0"] + ["0.000"] * 6 + ["0.0%"] * 6 + ["0.000", "0.0%"],
                         expected=exp, static_cols=COMP_COLS[3:], n_col="Positives", min_n=30,
                         note="Clients and positives are formulas on Raw Data (test years only). Every other column is computed in Python by the notebook "
                              "(scikit-learn, LightGBM, XGBoost) from out-of-time predictions: each test year is scored by a model trained and tuned only on "
                              "earlier start years. 95% ranges: bootstrap, 2,000 resamples. Precision, recall, F1, accuracy and specificity use the "
                              "threshold chosen on the training years. Top 20% capture = share of the year's future 5-seat accounts found in the top 20% of "
                              "that year's scores, with clients tied at the cut-off sharing the remaining places (staff at day 90 has many ties). Brier score is blank for the single signal "
                              "(a staff count is not a probability). The base-rate baseline flags nobody, so its accuracy is the 'always no' accuracy. Two cautions: the outcomes "
                              "of the latest training cohort only became known during the test year, so the backtest is slightly kinder than a real-time run; and the "
                              "auto-selected model is calibrated across the training years (one fit per training year after the first, then averaged), so its 2022 model rests on 2020 and 2021 only.")


sh = wb.add_tab("Model Comparison", explanation=cx(
    "Six models and two simple baselines, tested out of time: for each test year (2022 to 2025 for A, 2022 to 2024 for B) the models learn "
    "only from clients that started earlier, then score that year's new clients. ROC AUC: 0.5 is a coin toss and 1.0 is perfect ranking. "
    "PR AUC is the better guide when few clients reach the target: compare it with the base rate (the no-skill model). The single signal uses "
    "only staff on the books at day 90."))
T_CA = comp_table(sh, "comp_A", "Target A (5 within 12 months): models compared out of time, test years 2022-2025 pooled", pooledA, "A", YEARS_A)
sh.add_chart(T_CA, kind="bar", cats="Model", values=["ROC AUC", "PR AUC"], title="Target A: ROC AUC and PR AUC by model (out of time)")
T_CB = comp_table(sh, "comp_B", "Target B (10 within 24 months): models compared out of time, test years 2022-2024 pooled", pooledB, "B", YEARS_B)
T_DIFF = {}
for tgt, dd_ in [("A", diffA), ("B", diffB)]:
    for vs in ["Single signal: staff at day 90", "Logistic regression"]:
        if tgt == "B" and vs == "Logistic regression":
            continue
        dsub = dd_[dd_["versus"] == vs]
        body = [[r.model, float(r.auc_diff), float(r.lo), float(r.hi), "Better" if r.lo > 0 else ("Worse" if r.hi < 0 else "No clear difference")] for r in dsub.itertuples()]
        T_DIFF[(tgt, vs)] = sh.add_table(f"diff{tgt}_{'ss' if vs.startswith('Single') else 'lr'}",
                                          f"Target {tgt}: ROC AUC difference from {'staff at day 90 alone' if vs.startswith('Single') else 'logistic regression'} (paired bootstrap)",
                                          ["Model", "AUC difference", "95% low", "95% high", "Reading"], body, formats=[None, "0.000", "0.000", "0.000", None],
                                          expected=[[None, b[1], b[2], b[3], None] for b in body], static_cols=["AUC difference", "95% low", "95% high"],
                                          note="Computed in Python: 2,000 paired bootstrap resamples of the pooled out-of-time predictions. 'Better' or 'Worse' only when the 95% range excludes zero.")

# ---------------------------------------------------------------- 5 backtest by year
sh = wb.add_tab("Backtest by Year", explanation=cx(
    "The same out-of-time test, one start-year cohort at a time, to show whether the models hold up as conditions change. Each column is a "
    "test year scored by models trained only on earlier years. Stable values across years mean the early signals carry over; a drop in one "
    "year means that cohort behaved differently."))
body, exp = [], []
for y in YEARS_A:
    e = f[f["elig_A"] & (f["start_year"] == y)]
    crit = f'{CRW},"Y",{EL["A"]},1,{YR},A{{r}},{INC}'
    body.append([y, f"=COUNTIFS({crit})", f"=COUNTIFS({crit},{YY['A']},1)", "=IFERROR(C{r}/B{r},0)"])
    exp.append([None, len(e), int(e["y_A"].sum()), e["y_A"].mean()])
T_YP = sh.add_table("year_pop", "Target A test years: clients scored and positives", ["Test year", "Clients scored", "Reached 5 in 12 months", "Base rate"], body,
                    formats=["0", "#,##0", "#,##0", "0.0%"], expected=exp, note="Formulas on Raw Data: target-A clients by start year.", n_col="Reached 5 in 12 months", min_n=30)
bt = beatsA.set_index("model").iloc[:, 0]
body = [[m, int(bt.get(m, 0))] for m in MODELS if not m.startswith(("Baseline", "Single"))]
T_BEAT = sh.add_table("beats", "Target A: test years in which each model ranks better than staff at day 90 alone (of 4)", ["Model", "Test years ahead"], body,
                      formats=[None, "0"], expected=[[None, b[1]] for b in body], static_cols=["Test years ahead"],
                      note="Computed in Python from the per-year ROC AUC table below. Being ahead in a year can be by a tiny margin; see the paired comparison on Model Comparison.")
sh.add_text(cx(f"Small numbers: each test year has between {num('MIN(' + T_YP.range('Reached 5 in 12 months') + ')')} and "
               f"{num('MAX(' + T_YP.range('Reached 5 in 12 months') + ')')} clients that reached 5, so differences between single years are noisy; "
               "read the pooled results on Model Comparison first. Target B has even fewer per year."))
body, exp = [], []
for y in YEARS_B:
    e = f[f["elig_B"] & (f["start_year"] == y)]
    crit = f'{CRW},"Y",{EL["B"]},1,{YR},A{{r}},{INC}'
    body.append([y, f"=COUNTIFS({crit})", f"=COUNTIFS({crit},{YY['B']},1)", "=IFERROR(C{r}/B{r},0)"])
    exp.append([None, len(e), int(e["y_B"].sum()), e["y_B"].mean()])
T_YPB = sh.add_table("year_pop_B", "Target B test years: clients scored and positives", ["Test year", "Clients scored", "Reached 10 in 24 months", "Base rate"], body,
                     formats=["0", "#,##0", "#,##0", "0.0%"], expected=exp, note="Formulas on Raw Data: target-B clients by start year. Too few positives per year to compare single years.",
                     n_col="Reached 10 in 24 months", min_n=30)
YT = {}
for tgt, yr_df, years in [("A", yearA, YEARS_A), ("B", yearB, YEARS_B)]:
    for metric, lab, fmt in [("roc_auc", "ROC AUC", "0.000"), ("pr_auc", "PR AUC", "0.000"), ("precision", "Precision", "0.0%"), ("recall", "Recall", "0.0%"),
                             ("flagged", "Clients flagged at the training-year threshold", "#,##0")]:
        pv = yr_df.pivot(index="model", columns="year", values=metric).reindex(MODELS)
        cols = ["Model"] + [str(y) for y in years]
        body = [[m] + [None if pd.isna(pv.at[m, y]) else float(pv.at[m, y]) for y in years] for m in MODELS]
        YT[(tgt, metric)] = sh.add_table(f"yr_{tgt}_{metric}", f"Target {tgt}: {lab} by test year", cols, body, formats=[None] + [fmt] * len(years),
                                         expected=[[None] + b[1:] for b in body], static_cols=cols[1:],
                                         note="Computed in Python by the notebook from out-of-time predictions (model trained and tuned on earlier start years only).")
        if tgt == "A" and metric == "roc_auc":
            sh.add_chart(YT[(tgt, metric)], kind="col", cats="Model", values=cols[1:], title="Target A: ROC AUC by test year")

# ---------------------------------------------------------------- 6 lift and calibration
sh = wb.add_tab("Lift and Calibration", explanation=cx(
    "How useful the scores are in practice. Lift: how much richer in future 5-seat accounts the top-scored clients are than the average client. "
    "Capture: the share of all future 5-seat accounts found by working only the top-scored clients. Calibration: clients grouped by predicted "
    "chance; when predicted and actual are close, the scores can be read as real probabilities."))
pp = pooledA.set_index("model")
LIFT_COLS = ["Model", "Top 10% lift", "Top 10% capture", "Top 10% precision", "Top 20% lift", "Top 20% capture", "Top 20% precision", "Top 20% capture (per year)"]
LK = ["lift_top10", "capture_top10", "precision_top10", "lift_top20", "capture_top20", "precision_top20", "capture_top20_per_year"]
body = [[m] + [float(pp.at[m, k]) for k in LK] for m in MODELS if m != "Baseline: base rate"]
T_LIFT = sh.add_table("lift", "Target A: lift and capture of the top-scored clients (pooled out of time)", LIFT_COLS, body,
                      formats=[None, "0.0", "0.0%", "0.0%", "0.0", "0.0%", "0.0%", "0.0%"], expected=[[None] + b[1:] for b in body], static_cols=LIFT_COLS[1:],
                      note="Computed in Python. Pooled columns rank all test-year clients together; the last column ranks within each test year (the way a monthly list would be used).")
sh.add_chart(T_LIFT, kind="bar", cats="Model", values=["Top 20% capture (per year)"], title="Share of future 5-seat accounts in the top 20% of scores", y_format="0%")
R_LAB = ruleA["rule"].iat[0]
tA = f[f["elig_A"] & f["start_year"].isin(YEARS_A)]
crit = f'{CRW},"Y",{EL["A"]},1,{YR},">={min(YEARS_A)}",{YR},"<={max(YEARS_A)}",{INC}'
rule_ok = (tA["seats_d90"] >= 2) | (tA["second_start_by_d90"] == 1)
T_RULE = sh.add_table("rule", "Target A: simple day-90 rule, test years 2022-2025", ["Rule", "Clients", "Flagged", "Share flagged", "Reached 5", "Caught", "Capture", "Precision"],
                      [[R_LAB, f"=COUNTIFS({crit})", f'=COUNTIFS({crit},{S90},">=2")+COUNTIFS({crit},{S90},"<2",{SEC},1)', "=IFERROR(C{r}/B{r},0)",
                        f"=COUNTIFS({crit},{YY['A']},1)", f'=COUNTIFS({crit},{YY["A"]},1,{S90},">=2")+COUNTIFS({crit},{YY["A"]},1,{S90},"<2",{SEC},1)',
                        "=IFERROR(F{r}/E{r},0)", "=IFERROR(F{r}/C{r},0)"]],
                      formats=[None, "#,##0", "#,##0", "0.0%", "#,##0", "#,##0", "0.0%", "0.0%"],
                      expected=[[None, len(tA), int(rule_ok.sum()), rule_ok.mean(), int(tA["y_A"].sum()), int((rule_ok & (tA["y_A"] == 1)).sum()),
                                 (rule_ok & (tA["y_A"] == 1)).sum() / tA["y_A"].sum(), (rule_ok & (tA["y_A"] == 1)).sum() / rule_ok.sum()]],
                      note="Formulas on Raw Data: target-A clients that started 2022-2025. A rule needs no model and is the baseline to beat for account management. "
                           "The rule was chosen after seeing these years, so its capture is in-sample, not an out-of-time result.")
body = [[int(r.year), int(r.clients), float(r.predicted), float(r.actual)] for r in calYear.itertuples()]
T_CALY = sh.add_table("cal_year", "Target A: calibration by test year (auto-selected + calibrated model)", ["Test year", "Clients", "Average predicted chance", "Actual rate"], body,
                      formats=["0", "#,##0", "0.0%", "0.0%"], expected=[[None] + b[1:] for b in body], static_cols=["Clients", "Average predicted chance", "Actual rate"],
                      note="Computed in Python from the out-of-time predictions. The base rate moves between start years, so a model trained on earlier years can run high or low in a given year; "
                           f"the largest gap is {int(calYear.assign(g=(calYear.actual - calYear.predicted).abs()).sort_values('g').iloc[-1]['year'])} "
                           f"({'under' if (lambda r: r.actual > r.predicted)(calYear.assign(g=(calYear.actual - calYear.predicted).abs()).sort_values('g').iloc[-1]) else 'over'}-predicted).")
body = [[f"{r.model}: {r.band}", int(r.clients), float(r.predicted), float(r.actual)] for r in calA.itertuples()]
T_CAL = sh.add_table("cal", "Target A: calibration, predicted chance vs actual rate (five equal bands, pooled out of time)",
                     ["Model and band", "Clients", "Average predicted chance", "Actual rate"], body, formats=[None, "#,##0", "0.0%", "0.0%"],
                     expected=[[None] + b[1:] for b in body], static_cols=["Clients", "Average predicted chance", "Actual rate"],
                     note="Computed in Python from the out-of-time predictions. Logistic regression uses class weights, so its raw scores run high; "
                          "the auto-selected model is calibrated (sigmoid) on the training years.")

# ---------------------------------------------------------------- 7 drivers, sensitivity, target C
sh = wb.add_tab("Drivers", explanation=cx(
    "Which early signals matter once the others are held fixed. An odds ratio above 1 means more likely to reach the target; the 95% range "
    "must sit wholly above or below 1 for a clear effect. Several signals move together (a second start and more staff at day 90 go hand in hand), "
    "so read each odds ratio with the others held fixed, not on its own. These are associations in past data, not proof of cause."))
DR = {}
for t, lab in [("A", "Target A: reached 5 within 12 months"), ("B", "Target B: reached 10 within 24 months"), ("C", "Target C: kept expanding after reaching 5")]:
    d = drivers[drivers["target"] == t]
    body = [[r.signal, int(r.clients_with_signal), float(r.odds_ratio), float(r.lo), float(r.hi), float(r.p_value),
             "Higher" if r.lo > 1 else ("Lower" if r.hi < 1 else "No clear effect")] for r in d.itertuples()]
    DR[t] = sh.add_table(f"or_{t}", f"{lab}: odds ratios (logistic regression)", ["Early signal", "Clients with the signal", "Odds ratio", "95% low", "95% high", "p-value", "Reading"],
                         body, formats=[None, "#,##0", "0.00", "0.00", "0.00", "0.0000", None], expected=[[None] + b[1:6] + [None] for b in body],
                         static_cols=["Clients with the signal", "Odds ratio", "95% low", "95% high", "p-value"],
                         note="Computed in Python (statsmodels Logit) on all eligible clients for the target. 'Staff at day 90' is per extra staff member; the others are yes / no. "
                              "Region is compared with APAC; region and OPTI come from today's MyStaff tags, a minor timing caveat.")
    if t == "A":
        sh.add_chart(DR[t], kind="bar", cats="Early signal", values=["Odds ratio"], title="Target A: odds ratios (1 = no effect)")
ic = imp.columns.tolist()
FEAT = {"seats_d90": "Staff at day 90", "peak_d90": "Peak staff by day 90", "leavers_d90": "Leavers by day 90", "function_known_d90": "Share of roles matched",
        "adds_d31_90": "Adds in days 31-90", "initial_function": "Initial function", "second_start_by_d90": "Second start by day 90", "functions_d90": "Functions by day 90",
        "region": "Region", "start_quarter": "Start quarter", "seats_d60": "Staff at day 60", "seats_d30": "Staff at day 30", "starting_seats": "Starting seats (end of month 1)",
        "starts_d90": "Starts by day 90", "starts_first_week": "Starts in week 1", "days_to_2nd_start_capped": "Days to second start"}
body = [[FEAT.get(r[0], r[0])] + [float(x) for x in r[1:]] for r in imp.itertuples(index=False)]
T_IMP = sh.add_table("imp", "Target A: what the models lean on (mean absolute contribution per client)", ["Feature"] + ic[1:], body,
                     formats=[None] + ["0.000"] * (len(ic) - 1), expected=[[None] + b[1:] for b in body], static_cols=ic[1:],
                     note="Computed in Python: SHAP values for LightGBM, coefficient x value for the auto-selected model, both fitted on all target-A clients.")
body = [[f"{r.variant}: {r.model}", float(r.roc_auc), float(r.roc_auc_lo), float(r.roc_auc_hi), float(r.pr_auc), float(r.capture_top20)] for r in sens.itertuples()]
T_SENS = sh.add_table("sens", "Target A: sensitivity models (out of time, test years 2022-2025 pooled)",
                      ["Variant and model", "ROC AUC", "ROC AUC 95% low", "ROC AUC 95% high", "PR AUC", "Top 20% capture (per year)"], body,
                      formats=[None, "0.000", "0.000", "0.000", "0.000", "0.0%"], expected=[[None] + b[1:] for b in body],
                      static_cols=["ROC AUC", "ROC AUC 95% low", "ROC AUC 95% high", "PR AUC", "Top 20% capture (per year)"],
                      note="Computed in Python with the same backtest. 'Plus Custom Division and industry' uses today's MyStaff tags, which may leak the outcome (plan issue 1). "
                           "'Without staff and start counts' drops every headcount, start, second-start and function-count signal, leaving initial function, share of roles matched, region and start "
                           "season. Ranges: 1,000 bootstrap resamples (Model Comparison uses 2,000).")
c_auc = meta_r["c_auc"]
eC = f[f["elig_C"]]
T_C = sh.add_table("c_cv", "Target C: can early signals predict continued expansion after 5?", ["Measure", "Value"],
                   [["Clients that reached 5 in year 1 (aged 24+ months)", f'=COUNTIFS({CRW},"Y",{EL["C"]},1,{INC})'],
                    ["Kept expanding (month 12 to 24)", f'=COUNTIFS({CRW},"Y",{EL["C"]},1,{YY["C"]},1,{INC})'],
                    ["Cross-validated ROC AUC", float(c_auc[0])], ["Lowest across CV repeats (2.5th percentile)", float(c_auc[1])], ["Highest across CV repeats (97.5th percentile)", float(c_auc[2])]],
                   formats=[None, "0.000"], expected=[[None, len(eC)], [None, int(eC["y_C"].sum())], [None, c_auc[0]], [None, c_auc[1]], [None, c_auc[2]]],
                   static_cols=["Value"], note="Counts are formulas on Raw Data. AUC: logistic regression on the readable signals, 20 repeats of 5-fold stratified "
                                               "cross-validation, computed in Python. Too few clients for an out-of-time model contest (plan).")

# ---------------------------------------------------------------- 8 watch list
sh = wb.add_tab("Watch List", explanation=cx(
    "Clients that started 90 days to 12 months ago, scored with the final model for target A (auto-selected by time-ordered cross-validation "
    "on all past cohorts, then calibrated) and the same approach for target B. Use it as a ranked list for account planning, not as a promise: "
    "scores are chances learned from past clients. A 'lowering' signal can simply mean the client is below average on it (for example no adds yet). Clients that "
    "have already reached 5 (by day 90 or since) are listed without a score."))
wl = watch.copy()
body = [[r.client_name, r.shortcode, r.region, pd.Timestamp(r.start_date).to_pydatetime(), int(r.age_days), int(r.seats_d90), int(r.adds_d31_90),
         int(r.second_start_by_d90), r.initial_function, None if pd.isna(r.p_5_in_12m) else float(r.p_5_in_12m),
         None if pd.isna(r.p_10_in_24m) else float(r.p_10_in_24m), r.raises_score, r.lowers_score, r.status] for r in wl.itertuples()]
WCOLS = ["Client", "Shortcode", "Region", "Start date", "Age (days)", "Staff at day 90", "Adds days 31-90", "Second start by day 90", "Initial function",
         "Chance of 5 within 12 months", "Chance of 10 within 24 months", "Signals raising the score", "Signals lowering the score", "Status"]
T_W = sh.add_table("watch", "Watch list: clients 90 days to 12 months old, highest chance first", WCOLS, body,
                   formats=[None, None, None, "yyyy-mm-dd", "0", "0", "0", "0", None, "0.0%", "0.0%", None, None, None],
                   expected=[[None, None, None, None] + b[4:9] + [b[9], b[10], None, None, None] for b in body], static_cols=WCOLS[4:],
                   note="Scores computed in Python by the notebook (step 12). Signals = the two features adding most to, or taking most from, the client's score.")
wb.add_check("Watch list rows = Raw Data watch-list clients", f'=ROWS({T_W.range("Client")})', len(wl))
wb.add_check("Watch list rows tie to Raw Data (Watch List = 1)", f'=COUNTIFS({CRW},"Y",{WL},1,{INC})', len(wl))

# ---------------------------------------------------------------- 9 summary
lr, auto, s90, lgb = "Logistic regression", "Auto-selected + calibrated", "Single signal: staff at day 90", "LightGBM"
ref = lambda tbl, row, col: tbl.ref(row, col)
yr_auc = YT[("A", "roc_auc")]
sm = wb.summary
sm.add_kpis([
    {"label": "Target A clients", "formula": f"={TT['A'].ref('Total', 'Eligible clients')}", "fmt": "#,##0", "expected": int(f["elig_A"].sum()),
     "caption": "Aged 12+ months, not at 5 by day 90"},
    {"label": "Reached 5 within 12 months", "formula": f"={TT['A'].ref('Total', 'Rate')}", "fmt": "0.0%", "expected": float(f[f['elig_A']]['y_A'].mean()),
     "caption": "Base rate across all cohorts"},
    {"label": "Out-of-time ROC AUC", "formula": f"={ref(T_CA, lr, 'ROC AUC')}", "fmt": "0.00", "expected": float(pp.at[lr, "roc_auc"]),
     "caption": "Logistic regression, test years 2022-2025"},
    {"label": "Out-of-time PR AUC", "formula": f"={ref(T_CA, lr, 'PR AUC')}", "fmt": "0.00", "expected": float(pp.at[lr, "pr_auc"]),
     "caption": "Against a base rate near the rate above"},
    {"label": "Found in top 20% of scores", "formula": f"={ref(T_CA, lr, 'Top 20% capture')}", "fmt": "0%", "expected": float(pp.at[lr, "capture_top20_per_year"]),
     "caption": "Share of future 5-seat accounts"},
    {"label": "Target B ROC AUC", "formula": f"={ref(T_CB, lr, 'ROC AUC')}", "fmt": "0.00", "expected": float(pooledB.set_index('model').at[lr, 'roc_auc']),
     "caption": "10 within 24 months, out of time"},
])
dA = diffA[diffA["versus"] == "Logistic regression"].set_index("model")
dS = diffA[diffA["versus"] == "Single signal: staff at day 90"].set_index("model")
dSB = diffB[diffB["versus"] == "Single signal: staff at day 90"].set_index("model")
trees_better = [m for m in ["Random forest", "LightGBM", "XGBoost"] if dA.at[m, "lo"] > 0]
trees_worse = [m for m in ["Random forest", "LightGBM", "XGBoost"] if dA.at[m, "hi"] < 0]
single_gap = "no clear gain" if dA.at[s90, "lo"] <= 0 <= dA.at[s90, "hi"] else ("a clear gain" if dA.at[s90, "hi"] < 0 else "no gain")
oa = drivers[drivers["target"] == "A"].set_index("signal")
clear_up = [x for x in oa.index if oa.at[x, "lo"] > 1 and not x.startswith("Staff at day 90")]
clear_down = [x for x in oa.index if oa.at[x, "hi"] < 1]
sens_i = sens.set_index(["variant", "model"])
tags = ("Plus Custom Division and industry", lr)
tag_gain = sens_i.loc[tags, "roc_auc"] - pp.at[lr, "roc_auc"]
# per-year range of logistic regression AUC (row of the by-year table)
lr_row = f"{yr_auc.ref(lr, '2022')}:{yr_auc.ref(lr, '2025')}"
findings = [
    cx(f"Early signals predict reaching 5 well out of time: logistic regression scores {num(ref(T_CA, lr, 'ROC AUC'), '0.00')} ROC AUC "
       f"(95% range {num(ref(T_CA, lr, 'ROC AUC 95% low'), '0.00')} to {num(ref(T_CA, lr, 'ROC AUC 95% high'), '0.00')}) on cohorts it never saw, "
       f"between {num('MIN(' + lr_row + ')', '0.00')} and {num('MAX(' + lr_row + ')', '0.00')} in each test year. Its PR AUC of "
       f"{num(ref(T_CA, lr, 'PR AUC'), '0.00')} compares with a base rate of {num(TT['A'].ref('Total', 'Rate'), '0.0%')}."),
    cx(f"At the threshold chosen on the training years, logistic regression flags clients with precision {num(ref(T_CA, lr, 'Precision'), '0%')} and recall "
       f"{num(ref(T_CA, lr, 'Recall'), '0%')}, and accuracy {num(ref(T_CA, lr, 'Accuracy'), '0%')} against {num(ref(T_CA, 'Baseline: base rate', 'Accuracy'), '0%')} for "
       f"always saying no ({num(ref(T_CA, lr, 'Test-year clients'))} clients, {num(ref(T_CA, lr, 'Positives'))} reached 5). Accuracy flatters when few clients reach "
       f"the target, so PR AUC and capture are the better guides. The agreed bar (ROC AUC 0.70, PR AUC twice the base rate, and better than the simple rule, staff at day 90 alone, in most "
       f"test years) is " + ("met" if pp.at[lr, "roc_auc"] >= 0.70 and pp.at[lr, "pr_auc"] >= 2 * pp.at[lr, "base_rate"] and int(beatsA.set_index("model").iloc[:, 0][lr]) >= 3 else "not met")
       + f": ahead of staff at day 90 alone in {num(ref(T_BEAT, lr, 'Test years ahead'))} of 4 test years, though by margins inside the bootstrap range."),
    cx(f"Most of the signal is size at day 90: staff on the books at day 90 on its own scores {num(ref(T_CA, s90, 'ROC AUC'), '0.00')} ROC AUC. Logistic regression "
       + ("ranks clearly better than that" if dS.at[lr, 'lo'] > 0 else ("ranks clearly worse" if dS.at[lr, 'hi'] < 0 else "is not clearly better"))
       + f" (difference {num(ref(T_DIFF[('A', s90)], lr, 'AUC difference'), '+0.000;-0.000')}, 95% range {num(ref(T_DIFF[('A', s90)], lr, '95% low'), '+0.000;-0.000')} to "
       f"{num(ref(T_DIFF[('A', s90)], lr, '95% high'), '+0.000;-0.000')}), although it is ahead in {num(ref(T_BEAT, lr, 'Test years ahead'))} of the 4 test years. "
       + ("The tree models (random forest, LightGBM, XGBoost) do no better than logistic regression"
          + (f"; {' and '.join(trees_worse)} {'is' if len(trees_worse) == 1 else 'are'} clearly worse." if trees_worse else ".")
          if not trees_better else f"{', '.join(trees_better)} beat logistic regression.")),
    cx(f"Beyond early momentum the signals add little: without any staff, start, second-start or function counts (initial function, share of roles matched, region and start season only), logistic regression "
       f"scores {num(ref(T_SENS, 'Without staff and start counts: Logistic regression', 'ROC AUC'), '0.00')} and LightGBM {num(ref(T_SENS, 'Without staff and start counts: LightGBM', 'ROC AUC'), '0.00')} ROC AUC. "
       + (f"With the others held fixed, {', '.join(lc(x) for x in clear_up)} {'is' if len(clear_up) == 1 else 'are'} linked to higher odds of reaching 5"
          + (f" (second start within 90 days: odds ratio {num(ref(DR['A'], 'Second start within 90 days', 'Odds ratio'), '0.0')})" if 'Second start within 90 days' in clear_up else "")
          + "; " if clear_up else "")
       + (f"{', '.join(lc(x) for x in clear_down)} {'lowers' if len(clear_down) == 1 else 'lower'} them (odds ratio "
          f"{num(ref(DR['A'], clear_down[0], 'Odds ratio'), '0.00')} for {lc(clear_down[0])})." if clear_down else "no signal clearly lowers them.")
),
    cx(f"Becoming meaningfully larger (10 staff within 24 months) is also predictable: logistic regression scores {num(ref(T_CB, lr, 'ROC AUC'), '0.00')} ROC AUC out of time, "
       f"but staff at day 90 alone scores {num(ref(T_CB, s90, 'ROC AUC'), '0.00')} and the model is "
       + ("clearly better than it" if dSB.at[lr, 'lo'] > 0 else ("clearly worse than it" if dSB.at[lr, 'hi'] < 0 else "not clearly different"))
       + f"; with only {num(ref(T_CB, lr, 'Positives'))} positives in the test years the ranges are wide. Continued expansion after reaching 5 is not predictable from "
       f"the first 90 days: cross-validated ROC AUC {num(ref(T_C, 'Cross-validated ROC AUC', 'Value'), '0.00')}"
       + (", close to chance (0.5)." if c_auc[0] < 0.6 else ".")),
    cx("Today's Custom Division and industry tags " + ("add little" if abs(tag_gain) < 0.01 else ("add some accuracy" if tag_gain > 0 else "do not help"))
       + f" (logistic regression {num(ref(T_SENS, 'Plus Custom Division and industry: Logistic regression', 'ROC AUC'), '0.000')} with them against "
         f"{num(ref(T_CA, lr, 'ROC AUC'), '0.000')} without), so the main models leave them out as planned."),
]
sm.add_findings(findings)
sm.add_recommendations([
    cx(f"Account management: at day 90, flag every client with 2 or more staff or a second start for an expansion review (in the backtest this rule flagged "
       f"{num(ref(T_RULE, R_LAB, 'Share flagged'), '0%')} of new clients and caught {num(ref(T_RULE, R_LAB, 'Capture'), '0%')} of those that reached 5), and work the "
       "Watch List from the highest score down each month; measure how many flagged clients reach 5 within 12 months against those backtest figures."),
    cx("Onboarding and client success: test, as a pilot with a comparison group, whether helping new clients make a second hire within 90 days raises the share "
       "that reach 5; the data shows an association, not yet a cause."),
    cx("Data & Analytics: re-run the notebook each quarter with the new engagement list, check the backtest stays above the agreed 0.70 ROC AUC bar, and request HubSpot company size "
       "and revenue so company size and account economics can be tested."),
])
sm.add_chart(T_CA, kind="bar", cats="Model", values=["ROC AUC"], title="Target A: out-of-time ROC AUC by model")
sm.add_chart(DR["A"], kind="bar", cats="Early signal", values=["Odds ratio"], title="Target A: odds ratios of early signals")

# ---------------------------------------------------------------- 10 governance
wb.log_decision("Scope: approved client growth cohort (clients first staffed Jan 2020 to Sep 2026; internal, test and excluded rows out)",
                int((~s["include"]).sum()), "Include = N; same rules as the client growth dashboard (commit 1bbef51)", "Jobs (2026-10-10)", ["Shortcode"])
wb.log_decision("Exact duplicate rows", int(df.astype(str).duplicated(keep="first").sum()), "Second copy set to Include = N (same as the client growth prep)",
                "Jobs (2026-10-10)", ["duplicate"])
wb.log_decision("Custom Division and industry track the outcome (today's MyStaff tags)", int(f["custom_division"].str.startswith("Unassigned").sum()),
                "Left out of the main models; one sensitivity model with them", "Jobs (2026-10-10)", ["Custom Division", "Industry"])
wb.log_decision("Role-title coverage changes by year (2020: most functions Unknown)", int((f["initial_function"] == "Unknown").sum()),
                "Unknown kept as its own function; sensitivity model without function features", "Jobs (2026-10-10)", ["Initial Function"])
wb.log_decision("Few positives (5 to 8%)", int(f[f["elig_A"]]["y_A"].sum()), "Class weights; PR AUC, lift and bootstrap ranges reported; no oversampling",
                "Jobs (2026-10-10)", ["Reached 5 in 12m"])
wb.log_decision("Clients too young for an outcome", int((f["age_days"] < 365).sum()), "Left out of training and testing; scored on the Watch List",
                "Jobs (2026-10-10)", ["Client Age (days)"])
wb.log_decision("Clients already at 5 (or 10) by day 90", int(((f["age_days"] >= 365) & (f["days_to_5"] <= 90)).sum()),
                "Left out of that target (outcome known at day 90). Rule tightened from 'fewer than 5 on day 90' to 'never 5 by day 90' (change log)",
                "Jobs (2026-10-10)", ["Days to 5"])
wb.log_decision("Start year not used as a signal", 0, "Backtest trains on earlier years; per-year results reported", "Jobs (2026-10-10)", ["Start Year"])
for term, d_, rule in [
    ("Target A", "Reached 5 staff at the same time within 12 months of the first start", "Clients aged 12+ months that had not reached 5 by day 90"),
    ("Target B", "Reached 10 staff at the same time within 24 months", "Clients aged 24+ months that had not reached 10 by day 90"),
    ("Target C", "Staff on day 730 above staff on day 365", "Clients that reached 5 within 12 months, aged 24+ months"),
    ("Early signal", "Anything known by day 90 after the first start", "Stints and dates up to day 90 only; nothing measured later"),
    ("Out of time (backtest)", "Each test year scored by models trained and tuned only on earlier start years", "Expanding window 2022-2025 (A), 2022-2024 (B)"),
    ("ROC AUC", "Chance that a random client who reached the target is scored above one who did not", "0.5 = coin toss, 1.0 = perfect"),
    ("PR AUC", "Average precision across all thresholds", "Compare with the base rate"),
    ("Precision / recall", "Of clients flagged, share that reached the target / of clients that reached it, share flagged", "Threshold chosen on the training years"),
    ("Top 20% capture", "Share of the year's positives among the top 20% of that year's scores", "Ranking within each test year"),
    ("Odds ratio", "Change in the odds of the target with the signal, others held fixed", "Logistic regression; above 1 = more likely"),
]:
    wb.define(term, d_, rule)
wb.attest("definitions_confirmed", True, "Targets, early window and treatments approved by Jobs on 2026-10-10 (plan.md Approvals)")
wb.attest("period_confirmed", True, "Clients first staffed Jan 2020 to Sep 2026; data to 29 Sep 2026")
wb.attest("outliers_reviewed", True, "Large clients kept; counts are log-scaled for the linear models and trees are scale-free")
wb.attest("sample_sizes_reviewed", True, "Groups under 30 flagged; Target B and C small and stated in findings")
wb.attest("no_causal_overreach", True, "Findings state associations; the onboarding recommendation is framed as a pilot")
wb.attest("requester_questions_answered", True, "Reach 5, keep expanding, become larger; several models; accuracy, precision, AUC; backtest")

result = wb.save(OUT)
