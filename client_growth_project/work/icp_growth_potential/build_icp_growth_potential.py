"""High-growth-potential accounts (ICP from client history) -> Cloudstaff-branded, QA-gated workbook.

Question: what can we observe early in a client relationship that predicts whether an account reaches
5 seats, how fast, and what happens after? APAC and AMER separately, client starts 2021 to 2026.
Plan: work/icp_growth_potential/plan.md (approved 2026-10-08).

Run from the project root:  CS_QA_DIR=qa python work/icp_growth_potential/build_icp_growth_potential.py
Next period: point icp_prep.ENG_SRC at the new StaffCentral engagement list and update icp_prep.EXTRACT;
refresh the MyStaff client list and the monthly billed report paths if newer versions exist.
"""
import os
import re
import sys
import datetime as dt

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "cs-data-analytics", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cs_xl import CSWorkbook, const, num                # noqa: E402
from profile_data import load_source, row_issues        # noqa: E402
import stats_helpers as st                              # noqa: E402
import icp_prep as P                                    # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else f"outputs/excel/{dt.date.today():%Y-%m-%d}_High_Growth_Account_Profile.xlsx"
REGIONS = ["AMER", "APAC"]
GROUPS = ["1 Fast 5+", "2 Slow 5+", "3 Not reached 5, active", "4 Churned, never 5"]
X = f"DATE({P.EXTRACT.year},{P.EXTRACT.month},{P.EXTRACT.day})"


def cx(text):
    """Mark method constants in narrative text as const(); live {{...}} tokens untouched."""
    parts = re.split(r"(\{\{.+?\}\}|\[\[.+?\]\])", text)
    return "".join(x if x.startswith(("{{", "[[")) else re.sub(r"\d+(\.\d+)?%?", lambda m: const(m.group()), x) for x in parts)


# ---------------------------------------------------------------- 1 load + flag
df, meta = load_source(P.ENG_SRC)
N = len(df)
issues = row_issues(df, required=["CSID", "Shortcode", "Engagement Date"], dates=["Engagement Date", "Disengagement Date"],
                    ids=["Engagement ID"], no_future=["Engagement Date", "Disengagement Date"],
                    custom=[("Disengagement Date before Engagement Date",
                             lambda r: isinstance(r["Disengagement Date"], dt.datetime) and isinstance(r["Engagement Date"], dt.datetime)
                             and r["Disengagement Date"] < r["Engagement Date"])])

# ---------------------------------------------------------------- 2 agreed treatments (pandas prep, see icp_prep.py)
rows, cl, ms, roles = P.prepare(df)
include = ["Y" if x else "N" for x in rows["inc"]]
inc = rows["inc"].values
cl = cl.copy()
cl["age"] = cl["age_days"]

# industry group: industries with 30+ clients (observed 12+ months) in that region keep their name
obs12 = cl["age"] >= 365
ind_n = cl[obs12].groupby(["region", "industry"]).size()


def ind_group(rg, ind):
    if ind == "Unknown":
        return "Unknown industry" if ind_n.get((rg, ind), 0) >= 30 else "Other industries"
    return ind if ind_n.get((rg, ind), 0) >= 30 else "Other industries"


cl["industry_group"] = [ind_group(r, i) for r, i in zip(cl["region"], cl["industry"])]
fn_n = cl[obs12].groupby(["region", "initial_function"]).size()
cl["initial_function_group"] = [f if (fn_n.get((r, f), 0) >= 30 or f == "Unknown") else "Other functions (under 30 clients)"
                                for r, f in zip(cl["region"], cl["initial_function"])]
rows["industry_group"] = rows["sc"].map(cl["industry_group"])
rows["initial_function"] = rows["sc"].map(cl["initial_function"])
rows["initial_function_group"] = rows["sc"].map(cl["initial_function_group"])
client_row = [None] * N
for p in cl["client_row_pos"]:
    client_row[int(p)] = "Y"
date2 = rows["sc"].map(cl["date_2nd_fn"])
date5 = rows["sc"].map(cl["date5"])
date10 = rows["sc"].map(cl["date10"])
peak = rows["sc"].map(cl["peak"])
fn90 = rows["sc"].map(cl["functions_by_d90"])
region_rule = [ms[c]["region_rule"] if i else None for c, i in zip(rows["sc"], inc)]


def on_cr(series):
    """Client-level value written on the client row only."""
    out = []
    for i, v in enumerate(series):
        if client_row[i] != "Y" or v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
            out.append(None)
        elif isinstance(v, pd.Timestamp):
            out.append(v.to_pydatetime())
        elif isinstance(v, (np.integer,)):
            out.append(int(v))
        else:
            out.append(v)
    return out


def on_inc(series):
    return [(None if (not i or v is None or (isinstance(v, float) and np.isnan(v))) else
             (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v)) for v, i in zip(series, inc)]


CR = '{Client Row}="Y"'
INC = 'raw_Include,"Y"'


def seats_f(cp):
    """Active valid stints on the shortcode on day cp (Engagement Date <= cp <= Disengagement Date or open)."""
    return (f'COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Valid_Stint,"Y",raw_Engagement_Date,"<="&{cp},'
            f'raw_Disengagement_Date,">="&{cp},{INC})+COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Engagement_Date,"<="&{cp},'
            f'raw_Disengagement_Date,"",{INC})')


SEAT_DAYS = [30, 90, 180, 365, 730, 1095]
derived = {
    "Scope": {"values": list(rows["scope"]), "rule": "In scope = external client (internal-unit rule approved 2026-09-30), not flagged "
              "Internal in MyStaff, region APAC or AMER, first staff start on or after 2021-01-01. Otherwise the reason it is out."},
    "Region": {"values": on_inc(rows["region"]), "rule": "MyStaff client list (2026-09-27) Region. OPTI clients: office country, then "
               "timezone, then billing currency; Australia, New Zealand and Asia = APAC, all others = AMER"},
    "Region Rule": {"values": region_rule, "rule": "Which field set the region"},
    "Brand": {"values": on_inc(rows["brand"]), "rule": "OPTI if MyStaff Region = OPTI, otherwise Cloudstaff"},
    "Industry": {"values": on_inc(rows["industry"]), "rule": "MyStaff Industry Roll Up; HubSpot industry when the roll-up is blank, '-' or '0'; else Unknown"},
    "Industry Group": {"values": on_inc(rows["industry_group"]), "rule": "Industry if it has 30+ clients observed 12+ months in that region; "
                       "otherwise 'Other industries'; blank industry = 'Unknown industry'"},
    "Client Start": {"values": on_inc(rows["client_start"]), "format": "yyyy-mm-dd",
                     "rule": "Earliest Engagement Date on the shortcode (rows of external clients)"},
    "Day From Start": {"formula": '=IF({Include}="Y",{Engagement Date}-{Client Start},"")', "format": "0"},
    "Valid Stint": {"formula": '=IF(OR({Disengagement Date}="",{Disengagement Date}>={Engagement Date}),"Y","N")'},
    "First Stint": {"values": list(rows["first_stint"]), "rule": "Y = the staff member's first valid engagement on this shortcode "
                    "(earliest Engagement Date, file order breaks ties); later returns are N"},
    "Matched Role": {"values": on_inc(rows["role"]), "rule": "Role title from the 2026 New Monthly Billed Report (All Billed New Staff 2.0, "
                     "2023/2024 Closed Seats, Gross 2025, Jan-Sep 2026 tabs): same staff name with a kick-off date within 60 days "
                     "of the Engagement Date; same shortcode preferred, then closest date"},
    "Role Match Rule": {"values": on_inc(rows["role_rule"]), "rule": "How the role was matched"},
    "Function": {"values": on_inc(rows["function"]), "rule": "Matched Role mapped to a function family by ordered keyword rules "
                 "(icp_prep.FUNCTIONS); no matched role = Unknown"},
    "Initial Function": {"values": on_inc(rows["initial_function"]), "rule": "Client's most common known function among first stints "
                         "starting in the first 30 days (ties: earliest start); Unknown if none matched"},
    "Initial Function Group": {"values": on_inc(rows["initial_function_group"]), "rule": "Initial Function if it has 30+ clients observed "
                               "12+ months in that region (Unknown always kept); otherwise 'Other functions (under 30 clients)'"},
    "Expansion Type": {"formula": '=IF(AND({Include}="Y",{First Stint}="Y"),IF({Day From Start}>=30,IF(OR({Function}="Unknown",'
                       '{Initial Function}="Unknown"),"Unknown",IF({Function}={Initial Function},"Same function","New function")),'
                       '"Initial (first 30 days)"),"")'},
    "Client Row": {"values": client_row, "rule": "Y on one row per in-scope client (first in file order); client-level columns are filled on this row only"},
    "Client Age (days)": {"formula": f'=IF({CR},{X}-{{Client Start}},"")', "format": "0"},
    "Start Year": {"formula": f'=IF({CR},YEAR({{Client Start}}),"")', "format": "0"},
}
for n in SEAT_DAYS:
    derived[f"Seats D{n}"] = {"formula": f'=IF({CR},{seats_f(f"({{Client Start}}+{n})")},"")', "format": "0"}
derived.update({
    "Current Seats": {"formula": f'=IF({CR},{seats_f(X)},"")', "format": "0"},
    "Peak Seats": {"values": on_cr(peak), "format": "0", "rule": "Highest number of concurrent valid stints on any day (event sweep in icp_prep.py)"},
    "Date Reached 5": {"values": on_cr(date5), "format": "yyyy-mm-dd", "rule": "First day with 5 or more concurrent valid stints"},
    "Date Reached 10": {"values": on_cr(date10), "format": "yyyy-mm-dd", "rule": "First day with 10 or more concurrent valid stints"},
    "Days to 10": {"formula": f'=IF(AND({CR},{{Date Reached 10}}<>""),{{Date Reached 10}}-{{Client Start}},"")', "format": "0"},
    "RTG Starts D30": {"formula": f'=IF({CR},COUNTIFS(raw_Shortcode,{{Shortcode}},raw_First_Stint,"Y",raw_Day_From_Start,"<30",'
                       f'raw_Category,"RTG",{INC}),"")', "format": "0"},
    "Seats on Date Reached 5": {"formula": f'=IF(AND({CR},{{Date Reached 5}}<>""),{seats_f("{Date Reached 5}")},"")', "format": "0"},
    "Days to 5": {"formula": f'=IF(AND({CR},{{Date Reached 5}}<>""),{{Date Reached 5}}-{{Client Start}},"")', "format": "0"},
    "Outcome Group": {"formula": f'=IF({CR},IF({{Days to 5}}="",IF({{Current Seats}}>0,"3 Not reached 5, active","4 Churned, never 5"),'
                      f'IF({{Days to 5}}<={P.FAST_DAYS},"1 Fast 5+","2 Slow 5+")),"")'},
    "Fast 5 (within 6m)": {"formula": f'=IF({CR},IF({{Days to 5}}="",0,IF({{Days to 5}}<={P.FAST_DAYS},1,0)),"")', "format": "0"},
    "Reached 5 in 12m": {"formula": f'=IF({CR},IF({{Days to 5}}="",0,IF({{Days to 5}}<=365,1,0)),"")', "format": "0"},
    "Adds D31-90": {"formula": f'=IF({CR},COUNTIFS(raw_Shortcode,{{Shortcode}},raw_First_Stint,"Y",raw_Day_From_Start,">=30",'
                    f'raw_Day_From_Start,"<90",{INC}),"")', "format": "0"},
    "Leavers D90": {"formula": f'=IF({CR},COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Valid_Stint,"Y",raw_Disengagement_Date,'
                    f'"<"&({{Client Start}}+90),{INC}),"")', "format": "0"},
    "Functions by D90": {"values": on_cr(fn90), "format": "0", "rule": "Distinct known functions among first stints starting in the first 90 days"},
    "Adds Same Function": {"formula": f'=IF({CR},COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Expansion_Type,"Same function",{INC}),"")', "format": "0"},
    "Adds New Function": {"formula": f'=IF({CR},COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Expansion_Type,"New function",{INC}),"")', "format": "0"},
    "Adds Unknown Function": {"formula": f'=IF({CR},COUNTIFS(raw_Shortcode,{{Shortcode}},raw_Expansion_Type,"Unknown",{INC}),"")', "format": "0"},
    "Date 2nd Function": {"values": on_cr(date2), "format": "yyyy-mm-dd", "rule": "Earliest start of a first stint (after day 30) whose known function differs from the Initial Function"},
    "Days to 2nd Function": {"formula": f'=IF(AND({CR},{{Date 2nd Function}}<>""),{{Date 2nd Function}}-{{Client Start}},"")', "format": "0"},
    "2nd Function Before 5": {"formula": f'=IF(AND({CR},{{Date Reached 5}}<>""),IF(AND({{Date 2nd Function}}<>"",'
                              f'{{Date 2nd Function}}<={{Date Reached 5}}),"Yes","No"),"")'},
})
for n, lab in [(365, "12m"), (730, "24m"), (1095, "36m")]:
    derived[f"Status {lab} After 5"] = {"formula": f'=IF(AND({CR},{{Date Reached 5}}<>""),IF({{Date Reached 5}}+{n}>{X},"Too early",'
                                                    f'IF({seats_f(f"({{Date Reached 5}}+{n})")}>0,"Active","Churned")),"")'}

wb = CSWorkbook("High-Growth Account Profile", prepared_by="Jo Bert (Jobs) Olinares",
                requested_by="ICP / Marketing lead", period=f"Client starts Jan 2021 to {P.EXTRACT:%d %b %Y}")
wb.add_raw_data(df, meta, issues=issues, include=include, required=["CSID", "Shortcode", "Engagement Date"], derived=derived)
for h in ["Shortcode", "First Stint", "Day From Start", "Valid Stint", "Engagement Date", "Disengagement Date", "Expansion Type"]:
    assert wb.col(h) == "raw_" + re.sub(r"[^A-Za-z0-9_]+", "_", h).strip("_"), h
COL = wb.col
CRW, REG, AGE, OG = COL("Client Row"), COL("Region"), COL("Client Age (days)"), COL("Outcome Group")
R12, D5, CUR, PK = COL("Reached 5 in 12m"), COL("Days to 5"), COL("Current Seats"), COL("Peak Seats")


def base(rg, age=None, extra=""):
    a = f',{AGE},">={age}"' if age else ""
    return f'{CRW},"Y",{REG},"{rg}"{a},{INC}{extra}'


def wil(k, n):
    lo, hi = st.wilson_ci(k, n)
    return max(0.0, lo), min(1.0, hi)


def wlo(k, n):
    return "=MAX(0," + st.WILSON_LO.format(k=k, n=n)[1:] + ")"


def whi(k, n):
    return "=MIN(1," + st.WILSON_HI.format(k=k, n=n)[1:] + ")"


WLO, WHI = wlo("C{r}", "B{r}"), whi("C{r}", "B{r}")
RATE_COLS = ["Segment", "Clients", "Reached 5 within 12 months", "Rate", "95% range (low)", "95% range (high)"]
RATE_FMT = [None, "#,##0", "#,##0", "0.0%", "0.0%", "0.0%"]
chi_results = []   # (table, region, p) for the test tables


OUT5 = ("Reached 5 within 12 months", f"{R12},1", lambda d: d["days_to5"] <= 365)


def rate_table(sh, key, title, levels, note, extra_cols=(), age=365, outcome=None):
    """levels: list of (label, region, excel_extra_criteria, pandas_mask). Outcome default = reached 5 within 12 months."""
    oname, ocrit, ofun = outcome or OUT5
    cols = ["Segment", "Clients", oname, "Rate", "95% range (low)", "95% range (high)"] + [c[0] for c in extra_cols]
    fmts = RATE_FMT + [c[1] for c in extra_cols]
    body, exp = [], []
    for lab, rg, xc, m in levels:
        crit = base(rg, age, xc)
        sub = cl[m & (cl["region"] == rg) & (cl["age"] >= age)]
        n_, k_ = len(sub), int(ofun(sub).sum())
        lo, hi = wil(k_, n_)
        row = [lab, f"=COUNTIFS({crit})", f"=COUNTIFS({crit},{ocrit})", "=IFERROR(C{r}/B{r},0)", WLO, WHI]
        e = [lab, n_, k_, k_ / n_ if n_ else 0, lo, hi]
        for _, _, fx, fp in extra_cols:
            row.append(fx(crit))
            e.append(fp(sub))
        body.append(row)
        exp.append(e)
    t = sh.add_table(key, title, cols, body, formats=fmts, expected=exp, note=note, n_col="Clients", min_n=30)
    return t, exp


def chi_for(levels, age=365, ofun=None):
    ofun = ofun or OUT5[2]
    out = {}
    for rg in REGIONS:
        tab = []
        for lab, r_, xc, m in levels:
            if r_ != rg:
                continue
            sub = cl[m & (cl["region"] == rg) & (cl["age"] >= age)]
            k_ = int(ofun(sub).sum())
            if len(sub):
                tab.append([k_, len(sub) - k_])
        out[rg] = st.chi_square(tab)["p_value"] if len(tab) > 1 else float("nan")
    return out


# ---------------------------------------------------------------- 3a outcome groups
sh = wb.add_tab("Outcome Groups", explanation=cx(
    "The four comparison groups for clients that started from 2021, AMER and APAC side by side. Fast = 5 or more seats "
    "at the same time within 6 months of the first staff start; Slow = 5+ later; the other two never had 5 at once, split by "
    "whether they still have staff today. Clients that started recently may still reach 5, so read the third group with the "
    "client age in mind."))
body, exp = [], []
for g in GROUPS:
    row, e = [g], [g]
    for rg in REGIONS:
        crit = base(rg) + f",{OG},A{{r}}"
        k_ = int(((cl["region"] == rg) & (cl["group"] == g)).sum())
        n_ = int((cl["region"] == rg).sum())
        row += [f"=COUNTIFS({crit})", f"=IFERROR({{c:{rg} clients}}{{r}}/SUM({{c:{rg} clients}}{{first}}:{{c:{rg} clients}}{{last}}),0)"]
        e += [k_, k_ / n_]
    body.append(row)
    exp.append(e)
t_og = sh.add_table("groups", "Clients by outcome group and region",
                    ["Outcome group", "AMER clients", "AMER share", "APAC clients", "APAC share"], body,
                    formats=[None, "#,##0", "0.0%", "#,##0", "0.0%"], expected=exp, pct_sum_col="AMER share",
                    total={"label": "Total", "cells": {"AMER clients": "=SUM({c:AMER clients}{first}:{c:AMER clients}{last})",
                                                       "APAC clients": "=SUM({c:APAC clients}{first}:{c:APAC clients}{last})"}},
                    expected_total=[None, int((cl["region"] == "AMER").sum()), None, int((cl["region"] == "APAC").sum()), None],
                    note="Source: Raw Data client rows (Client Row = Y, Include = Y). Seats = concurrent staff stints from the StaffCentral engagement list.",
                    reconcile={"AMER clients": f'=COUNTIFS({base("AMER")})', "APAC clients": f'=COUNTIFS({base("APAC")})'})
sh.add_chart(t_og, kind="col", cats="Outcome group", values=["AMER share", "APAC share"], title="Share of clients in each outcome group", y_format="0%")

body, exp = [], []
for rg in REGIONS:
    for g in GROUPS:
        crit = base(rg) + f',{OG},"{g}"'
        s_ = cl[(cl["region"] == rg) & (cl["group"] == g)]
        body.append([f"{rg} | {g}", f"=COUNTIFS({crit})", f"=IFERROR(AVERAGEIFS({COL('Seats D30')},{crit}),0)",
                     f'=IFERROR(COUNTIFS({crit},{COL("Seats D30")},"<=1")/B{{r}},0)',
                     f"=IFERROR(AVERAGEIFS({PK},{crit}),0)", f"=IFERROR(AVERAGEIFS({CUR},{crit}),0)",
                     f'=IFERROR(COUNTIFS({crit},{PK},">=10")/B{{r}},0)', f"=IFERROR(AVERAGEIFS({AGE},{crit})/30.4375,0)"])
        n_ = len(s_)
        exp.append([f"{rg} | {g}", n_, s_["seats_d30"].mean() if n_ else 0, (s_["seats_d30"] <= 1).mean() if n_ else 0,
                    s_["peak"].mean() if n_ else 0, s_["current"].mean() if n_ else 0, (s_["peak"] >= 10).mean() if n_ else 0,
                    s_["age"].mean() / 30.4375 if n_ else 0])
med_body = []
for rg in REGIONS:
    for g in GROUPS:
        s_ = cl[(cl["region"] == rg) & (cl["group"] == g)]
        med_body.append([f"{rg} | {g}", f'=COUNTIFS({base(rg)},{OG},"{g}")', float(s_["seats_d30"].median()), float(s_["peak"].median()),
                         float(s_["current"].median()), float(s_["age"].median() / 30.4375)])
t_med = sh.add_table("medians", "Typical (median) client in each outcome group",
                     ["Region | group", "Clients", "Median seats at day 30", "Median peak seats", "Median current seats", "Median client age (months)"],
                     med_body, formats=[None, "#,##0", "0.0", "0.0", "0.0", "0.0"],
                     expected=[[b[0], int(((cl["region"] == b[0].split(" | ")[0]) & (cl["group"] == b[0].split(" | ")[1])).sum())] + b[2:] for b in med_body],
                     static_cols=["Median seats at day 30", "Median peak seats", "Median current seats", "Median client age (months)"],
                     n_col="Clients", min_n=30,
                     note="Medians computed in Python (pandas) at build time from the Raw Data client rows, because a grouped median needs an array formula. "
                          "Use the median for the typical client; the averages below are pulled up by a few large accounts.")
t_prof = sh.add_table("profile", "Averages for each outcome group",
                      ["Region | group", "Clients", "Avg seats at day 30", "% starting with 0-1 seat", "Avg peak seats",
                       "Avg current seats", "% reached 10+ seats", "Avg client age (months)"], body,
                      formats=[None, "#,##0", "0.0", "0.0%", "0.0", "0.0", "0.0%", "0.0"], expected=exp,
                      note="Averages are pulled up by a few large clients; use them to compare groups, not as typical values. "
                      "Day 30 = 30 days after the first staff start.", n_col="Clients", min_n=30)
TB = [("Under 12 months old", 0, 364), ("12-23 months old", 365, 729), ("24+ months old", 730, 100000)]
body, exp = [], []
for lab, lo, hi in TB:
    row, e = [lab], [lab]
    for rg in REGIONS:
        s_ = cl[(cl["region"] == rg) & (cl["group"] == GROUPS[2])]
        k_ = int(((s_["age"] >= lo) & (s_["age"] <= hi)).sum())
        row += [f'=COUNTIFS({base(rg)},{OG},"{GROUPS[2]}",{AGE},">={lo}",{AGE},"<={hi}")',
                f"=IFERROR({{c:{rg} clients}}{{r}}/SUM({{c:{rg} clients}}{{first}}:{{c:{rg} clients}}{{last}}),0)"]
        e += [k_, k_ / len(s_)]
    body.append(row)
    exp.append(e)
t_ten = sh.add_table("tenure3", "Group 3 (not reached 5, still active) by client age",
                     ["Client age", "AMER clients", "AMER share", "APAC clients", "APAC share"], body,
                     formats=[None, "#,##0", "0.0%", "#,##0", "0.0%"], expected=exp, pct_sum_col="AMER share",
                     total={"label": "Total", "cells": {"AMER clients": "=SUM({c:AMER clients}{first}:{c:AMER clients}{last})",
                                                        "APAC clients": "=SUM({c:APAC clients}{first}:{c:APAC clients}{last})"}},
                     expected_total=[None, int(((cl["region"] == "AMER") & (cl["group"] == GROUPS[2])).sum()), None,
                                     int(((cl["region"] == "APAC") & (cl["group"] == GROUPS[2])).sum()), None],
                     note="Clients under 12 months old may still reach 5; the 24+ months band is the settled 'never reached 5 but stayed' group.",
                     reconcile={"AMER clients": f'=COUNTIFS({base("AMER")},{OG},"{GROUPS[2]}")', "APAC clients": f'=COUNTIFS({base("APAC")},{OG},"{GROUPS[2]}")'})
from scipy.stats import mannwhitneyu   # noqa: E402
body, exp = [], []
for rg in REGIONS:
    d = cl[(cl["region"] == rg) & obs12]
    a, b = d[d["days_to5"] <= 365]["seats_d30"], d[~(d["days_to5"] <= 365)]["seats_d30"]
    pmw = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
    body.append([rg, f'=COUNTIFS({base(rg, 365)},{R12},1)', float(a.median()), f'=COUNTIFS({base(rg, 365)},{R12},0)', float(b.median()), pmw])
    exp.append([rg, len(a), float(a.median()), len(b), float(b.median()), pmw])
t_mw = sh.add_table("mw", "Mann-Whitney test: seats at day 30, reached 5 within 12 months vs not (clients aged 12+ months)",
                    ["Region", "Reached 5 clients", "Median seats at day 30 (reached)", "Not reached clients", "Median seats at day 30 (not reached)", "p-value"],
                    body, formats=[None, "#,##0", "0.0", "#,##0", "0.0", "0.0000"], expected=exp,
                    static_cols=["Median seats at day 30 (reached)", "Median seats at day 30 (not reached)", "p-value"],
                    note="Medians and the Mann-Whitney U test (two-sided, scipy) computed in Python at build time. p < 0.05 = the seat distributions differ by more than chance. "
                         "Includes clients already at 5+ seats on day 30, who reached 5 by construction.")

# ---------------------------------------------------------------- 3b speed to 5
sh = wb.add_tab("Speed to 5", explanation=cx(
    "How quickly clients reach 5 seats. The first table shows the share of clients that reached 5 within each time "
    "window, counting only clients old enough to have had that full window. The second table shows, for clients that did "
    "reach 5, how long it took. A flat line after the early months means most clients that get to 5 do so early."))
WIN = [("Within 1 month", 30), ("Within 3 months", 91), ("Within 6 months", 183), ("Within 12 months", 365),
       ("Within 18 months", 548), ("Within 24 months", 730), ("Within 36 months", 1095)]
body, exp = [], []
for lab, d in WIN:
    row, e = [lab], [lab]
    for rg in REGIONS:
        crit = base(rg, d)
        s_ = cl[(cl["region"] == rg) & (cl["age"] >= d)]
        k_ = int((s_["days_to5"] <= d).sum())
        L = len(row)
        row += [f"=COUNTIFS({crit})", f'=COUNTIFS({crit},{D5},"<={d}")', f"=IFERROR({{c:{rg} reached 5}}{{r}}/{{c:{rg} eligible}}{{r}},0)",
                wlo(f"{{c:{rg} reached 5}}{{r}}", f"{{c:{rg} eligible}}{{r}}"), whi(f"{{c:{rg} reached 5}}{{r}}", f"{{c:{rg} eligible}}{{r}}")]
        lo_, hi_ = wil(k_, len(s_))
        e += [len(s_), k_, k_ / len(s_) if len(s_) else 0, lo_, hi_]
    body.append(row)
    exp.append(e)
t_speed = sh.add_table("speed", "Share of clients reaching 5 seats within each window",
                       ["Window", "AMER eligible", "AMER reached 5", "AMER %", "AMER low", "AMER high",
                        "APAC eligible", "APAC reached 5", "APAC %", "APAC low", "APAC high"], body,
                       formats=[None, "#,##0", "#,##0", "0.0%", "0.0%", "0.0%", "#,##0", "#,##0", "0.0%", "0.0%", "0.0%"], expected=exp,
                       note="Eligible = client at least as old as the window on the extract date; low / high = Wilson 95% range. Months = days / 30.4 (6 months = 183 days). "
                            "Each row has its own set of eligible clients, so later rows rest on older clients only (36 months = 2021-2023 starters); a rise "
                            "between late rows can reflect which clients are counted, not later growth. Used instead of the planned Kaplan-Meier curve so every rate is a live formula.",
                       n_col="AMER eligible", min_n=30)
sh.add_chart(t_speed, kind="line", cats="Window", values=["AMER %", "APAC %"], title="Cumulative share of clients reaching 5 seats", y_format="0%", anchor="below")
speed_tests = {}
body, exp = [], []
for lab, d in [("Within 6 months", 183), ("Within 12 months", 365)]:
    a = cl[(cl["region"] == "AMER") & (cl["age"] >= d)]
    b = cl[(cl["region"] == "APAC") & (cl["age"] >= d)]
    ka, kb = int((a["days_to5"] <= d).sum()), int((b["days_to5"] <= d).sum())
    tt = st.two_proportion_test(ka, len(a), kb, len(b))
    speed_tests[lab] = tt["p_value"]
    body.append([lab, "=" + t_speed.ref(lab, "AMER %"), "=" + t_speed.ref(lab, "APAC %"), "=B{r}-C{r}", tt["p_value"]])
    exp.append([lab, ka / len(a), kb / len(b), ka / len(a) - kb / len(b), tt["p_value"]])
t_spt = sh.add_table("speed_test", "AMER vs APAC: two-proportion test", ["Window", "AMER %", "APAC %", "Difference (points)", "p-value"], body,
                     formats=[None, "0.0%", "0.0%", "0.0%", "0.0000"], expected=exp, static_cols=["p-value"],
                     note="Two-proportion z-test computed in Python (stats_helpers.two_proportion_test) at build time. p < 0.05 = the regions differ by more than chance.")
BANDS5 = [("Within 30 days", 0, 30), ("31-90 days", 31, 90), ("91-183 days", 91, 183), ("6-12 months", 184, 365),
          ("12-24 months", 366, 730), ("Over 24 months", 731, 100000)]
body, exp = [], []
for lab, lo, hi in BANDS5:
    row, e = [lab], [lab]
    for rg in REGIONS:
        s_ = cl[(cl["region"] == rg) & cl["days_to5"].notna()]
        k_ = int(((s_["days_to5"] >= lo) & (s_["days_to5"] <= hi)).sum())
        row += [f'=COUNTIFS({base(rg)},{D5},">={lo}",{D5},"<={hi}")',
                f"=IFERROR({{c:{rg} clients}}{{r}}/SUM({{c:{rg} clients}}{{first}}:{{c:{rg} clients}}{{last}}),0)"]
        e += [k_, k_ / len(s_)]
    body.append(row)
    exp.append(e)
t_t5 = sh.add_table("time5", "Time taken to reach 5 seats (clients that reached 5)",
                    ["Time to 5 seats", "AMER clients", "AMER share", "APAC clients", "APAC share"], body,
                    formats=[None, "#,##0", "0.0%", "#,##0", "0.0%"], expected=exp, pct_sum_col="AMER share",
                    total={"label": "Total", "cells": {"AMER clients": "=SUM({c:AMER clients}{first}:{c:AMER clients}{last})",
                                                       "APAC clients": "=SUM({c:APAC clients}{first}:{c:APAC clients}{last})"}},
                    expected_total=[None, int(((cl["region"] == "AMER") & cl["days_to5"].notna()).sum()), None,
                                    int(((cl["region"] == "APAC") & cl["days_to5"].notna()).sum()), None],
                    note="Days from the first staff start to the first day with 5 concurrent staff. Recent clients have had less time, so later bands are understated.",
                    reconcile={"AMER clients": f'=COUNTIFS({base("AMER")},{D5},">=0")', "APAC clients": f'=COUNTIFS({base("APAC")},{D5},">=0")'})
sh.add_chart(t_t5, kind="col", cats="Time to 5 seats", values=["AMER share", "APAC share"], title="Time taken to reach 5 seats", y_format="0%")

# ---------------------------------------------------------------- 3c early signals
sh = wb.add_tab("Early Signals", explanation=cx(
    "What the first 90 days tell us about reaching 5 seats within 12 months. Only clients at least 12 months old are "
    "counted. The first table uses seats at day 30. The second keeps only clients still under 5 seats at day 90 (the ones "
    "that still need to grow) and compares their seats at day 90, staff added in days 31-90, functions hired and early "
    "leavers. The 95% range shows how sure each rate is; small rows are flagged."))
S30, S90, A90, L90, F90 = COL("Seats D30"), COL("Seats D90"), COL("Adds D31-90"), COL("Leavers D90"), COL("Functions by D90")
lv30 = []
for rg in REGIONS:
    for lab, lo, hi in [("0 seats", 0, 0), ("1 seat", 1, 1), ("2 seats", 2, 2), ("3-4 seats", 3, 4), ("5+ seats", 5, 9999)]:
        lv30.append((f"{rg} | {lab}", rg, f',{S30},">={lo}",{S30},"<={hi}"', (cl["seats_d30"] >= lo) & (cl["seats_d30"] <= hi)))
t_s30, exp_s30 = rate_table(sh, "seats30", "Reached 5 within 12 months, by seats at day 30", lv30,
                            "Clients aged 12+ months. Seats at day 30 = concurrent staff 30 days after the first staff start. "
                            "0 seats = the first staff had already left by day 30. The 5+ rows are 100% by construction.")
sh.add_chart(t_s30, kind="bar", cats="Segment", values=["Rate"], title="Reached 5 within 12 months, by seats at day 30", y_format="0%")
chi_results.append(("Seats at day 30", chi_for(lv30)))

YRC, RTGC = COL("Start Year"), COL("RTG Starts D30")
lv_start = []
for rg in REGIONS:
    for y in sorted(cl[obs12 & (cl["region"] == rg)]["start"].dt.year.unique()):
        lv_start.append((f"{rg} | Started {y}", rg, f",{YRC},{y}", cl["start"].dt.year == y))
    lv_start.append((f"{rg} | RTG staff in first 30 days: yes", rg, f',{RTGC},">=1"', cl["rtg_d30"] >= 1))
    lv_start.append((f"{rg} | RTG staff in first 30 days: no", rg, f",{RTGC},0", cl["rtg_d30"] == 0))
t_start, exp_start = rate_table(sh, "start_attr", "Reached 5 within 12 months, by start year and RTG staff at start", lv_start,
                                "Clients aged 12+ months. RTG = staff from the Ready-To-Go pool (Category = RTG) among first stints in the first 30 days. "
                                "2025 starters are counted only if at least 12 months old.")
chi_results.append(("Start year", chi_for([x for x in lv_start if "Started" in x[0]])))
chi_results.append(("RTG staff at start", chi_for([x for x in lv_start if "RTG" in x[0]])))

u5 = cl["seats_d90"] < 5
U5 = f',{S90},"<5"'
SIG = [
    ("Seats at day 90", [("0", f',{S90},0', cl["seats_d90"] == 0), ("1", f',{S90},1', cl["seats_d90"] == 1),
                         ("2", f',{S90},2', cl["seats_d90"] == 2), ("3-4", f',{S90},">=3"', cl["seats_d90"] >= 3)]),
    ("Staff added days 31-90", [("none", f',{A90},0', cl["adds_31_90"] == 0), ("1+", f',{A90},">=1"', cl["adds_31_90"] >= 1)]),
    ("Functions hired by day 90", [("0-1", f',{F90},"<=1"', cl["functions_by_d90"] <= 1),
                                   ("2+", f',{F90},">=2"', cl["functions_by_d90"] >= 2)]),
    ("Leavers in first 90 days", [("none", f',{L90},0', cl["leavers_90"] == 0), ("1+", f',{L90},">=1"', cl["leavers_90"] >= 1)]),
]
lv_sig = []
for rg in REGIONS:
    for sig, levels in SIG:
        for lab, xc, m in levels:
            lv_sig.append((f"{rg} | {sig}: {lab}", rg, U5 + xc, u5 & m))
t_sig, exp_sig = rate_table(sh, "signals", "Clients under 5 seats at day 90: reached 5 within 12 months, by early signal", lv_sig,
                            "Clients aged 12+ months with fewer than 5 seats at day 90. Functions = distinct known function families "
                            "among staff starting in the first 90 days (from matched roles). Leavers = staff stints ending in the first 90 days.")
for sig, levels in SIG:
    chi_results.append((sig + " (under 5 at day 90)", chi_for([(f"{rg}|{lab}", rg, xc, u5 & m) for rg in REGIONS for lab, xc, m in levels])))

# ---------------------------------------------------------------- 3d industry
sh = wb.add_tab("Industry", explanation=cx(
    "Whether some industries reach 5 seats more often. Industries with at least 30 clients aged 12+ months in a region "
    "are shown by name; the rest are grouped. Compare the rate with its 95% range: when ranges overlap the difference "
    "may be chance. The test table below gives the chi-square result per region."))
IG = COL("Industry Group")
lv_ind = []
for rg in REGIONS:
    names = cl[obs12 & (cl["region"] == rg)]["industry_group"].value_counts()
    order = [i for i in names.index if i not in ("Other industries", "Unknown industry")] + \
            [i for i in ("Other industries", "Unknown industry") if i in names.index]
    for i in order:
        lv_ind.append((f"{rg} | {i}", rg, f',{IG},"{i}"', cl["industry_group"] == i))
churn_col = ("Churned (no staff today)", "0.0%", lambda c: f'=IFERROR(COUNTIFS({c},{CUR},0)/B{{r}},0)', lambda s: float((s["current"] == 0).mean()) if len(s) else 0)
peak_col = ("Avg peak seats", "0.0", lambda c: f"=IFERROR(AVERAGEIFS({PK},{c}),0)", lambda s: float(s["peak"].mean()) if len(s) else 0)
t_ind, exp_ind = rate_table(sh, "industry", "Reached 5 within 12 months, by industry", lv_ind,
                            "Clients aged 12+ months. Industry = MyStaff Industry Roll Up (HubSpot industry where blank). Sorted by client count at build time.",
                            extra_cols=[churn_col, peak_col])
sh.add_chart(t_ind, kind="bar", cats="Segment", values=["Rate"], title="Reached 5 within 12 months, by industry", y_format="0%", anchor="below")
chi_results.append(("Industry", chi_for(lv_ind)))

# ---------------------------------------------------------------- 3e initial function
sh = wb.add_tab("Initial Function", explanation=cx(
    "Whether the first role a client hires is linked to reaching 5 seats. The initial function is the most common "
    "function among staff who started in the first 30 days, taken from role titles in the monthly billed report. "
    "'Executive Services (generic)' is a broad Cloudstaff title that hides the real job. Rows under 30 clients are flagged "
    "and should not be ranked."))
IF_ = COL("Initial Function Group")
lv_fn = []
for rg in REGIONS:
    vc = cl[obs12 & (cl["region"] == rg)]["initial_function_group"].value_counts()
    order = [f for f in vc.index if f not in ("Unknown", "Other functions (under 30 clients)")] + \
            [f for f in ("Other functions (under 30 clients)", "Unknown") if f in vc.index]
    for f in order:
        lv_fn.append((f"{rg} | {f}", rg, f',{IF_},"{f}"', cl["initial_function_group"] == f))
new12 = ("Added a new function within 12 months", "0.0%", lambda c: f'=IFERROR(COUNTIFS({c},{COL("Days to 2nd Function")},"<=365")/B{{r}},0)',
         lambda s: float((s["days_to_2nd_fn"] <= 365).mean()) if len(s) else 0)
t_fn, exp_fn = rate_table(sh, "initfn", "Reached 5 within 12 months, by initial function", lv_fn,
                          "Clients aged 12+ months. Functions with fewer than 30 clients in the region are grouped. Unknown = no first-month staff matched to a role title.", extra_cols=[new12, peak_col])
sh.add_chart(t_fn, kind="bar", cats="Segment", values=["Rate"], title="Reached 5 within 12 months, by initial function", y_format="0%", anchor="below")
chi_results.append(("Initial function", chi_for(lv_fn)))

# ---------------------------------------------------------------- 3f expansion path
sh = wb.add_tab("Expansion Path", explanation=cx(
    "How clients grow after the first 30 days: more staff in the same function as their first hires, or staff in a new "
    "function. Adds are each staff member's first stint on the client after day 30 (replacements included). The share of "
    "new-function adds uses only adds with a known function. The lower tables show how soon clients add a second function "
    "and whether 5+ clients did so before reaching 5."))
SAME, NEW, UNK, D2 = COL("Adds Same Function"), COL("Adds New Function"), COL("Adds Unknown Function"), COL("Days to 2nd Function")
body, exp = [], []
for rg in REGIONS:
    for g in GROUPS:
        crit = base(rg) + f',{OG},"{g}"'
        s_ = cl[(cl["region"] == rg) & (cl["group"] == g)]
        sa, ne, un = s_["adds_Same function"].sum(), s_["adds_New function"].sum(), s_["adds_Unknown"].sum()
        body.append([f"{rg} | {g}", f"=COUNTIFS({crit})", f"=SUMIFS({SAME},{crit})", f"=SUMIFS({NEW},{crit})", f"=SUMIFS({UNK},{crit})",
                     "=IFERROR(D{r}/(C{r}+D{r}),0)", f'=IFERROR(COUNTIFS({crit},{NEW},">0")/B{{r}},0)',
                     f'=IFERROR(AVERAGEIFS({D2},{crit},{D2},"<>")/30.4375,0)'])
        d2 = s_["days_to_2nd_fn"].dropna()
        exp.append([f"{rg} | {g}", len(s_), int(sa), int(ne), int(un), ne / (sa + ne) if (sa + ne) else 0,
                    float((s_["adds_New function"] > 0).mean()) if len(s_) else 0, d2.mean() / 30.4375 if len(d2) else 0])
t_exp = sh.add_table("expansion", "Adds after day 30: same function vs new function, by outcome group",
                     ["Region | group", "Clients", "Adds in same function", "Adds in new function", "Adds, function unknown",
                      "% of known adds in a new function", "% clients that added a new function", "Avg months to 2nd function"], body,
                     formats=[None, "#,##0", "#,##0", "#,##0", "#,##0", "0.0%", "0.0%", "0.0"], expected=exp,
                     note="Adds = first stint per staff member starting on day 30 or later. Same / new is judged against the client's initial function. "
                          "Avg months to 2nd function counts only clients that added one.", n_col="Clients", min_n=30,
                     reconcile={"Adds in new function": f'=COUNTIFS({COL("Expansion Type")},"New function",{INC})'})
sh.add_chart(t_exp, kind="bar", cats="Region | group", values=["% of known adds in a new function", "% clients that added a new function"],
             title="Expansion into new functions, by outcome group", y_format="0%", anchor="below")

B2 = [("Within 3 months", 0, 91), ("3-6 months", 92, 183), ("6-12 months", 184, 365)]
body, exp = [], []
for lab, lo, hi in B2 + [("No 2nd function by 12 months", None, None)]:
    row, e = [lab], [lab]
    for rg in REGIONS:
        s_ = cl[(cl["region"] == rg) & obs12]
        if lo is None:
            k_ = int((~(s_["days_to_2nd_fn"] <= 365)).sum())
            row.append(f'=COUNTIFS({base(rg, 365)})-COUNTIFS({base(rg, 365)},{D2},"<=365")')
        else:
            k_ = int(((s_["days_to_2nd_fn"] >= lo) & (s_["days_to_2nd_fn"] <= hi)).sum())
            row.append(f'=COUNTIFS({base(rg, 365)},{D2},">={lo}",{D2},"<={hi}")')
        row.append(f"=IFERROR({{c:{rg} clients}}{{r}}/SUM({{c:{rg} clients}}{{first}}:{{c:{rg} clients}}{{last}}),0)")
        e += [k_, k_ / len(s_)]
    body.append(row)
    exp.append(e)
t_2fn = sh.add_table("second_fn", "Time to a second function (clients aged 12+ months)",
                     ["Time to 2nd function", "AMER clients", "AMER share", "APAC clients", "APAC share"], body,
                     formats=[None, "#,##0", "0.0%", "#,##0", "0.0%"], expected=exp, pct_sum_col="AMER share",
                     total={"label": "Total", "cells": {"AMER clients": "=SUM({c:AMER clients}{first}:{c:AMER clients}{last})",
                                                        "APAC clients": "=SUM({c:APAC clients}{first}:{c:APAC clients}{last})"}},
                     expected_total=[None, int((obs12 & (cl["region"] == "AMER")).sum()), None, int((obs12 & (cl["region"] == "APAC")).sum()), None],
                     note="Second function = first staff added after day 30 whose known function differs from the initial function.",
                     reconcile={"AMER clients": f'=COUNTIFS({base("AMER", 365)})', "APAC clients": f'=COUNTIFS({base("APAC", 365)})'})
B5 = COL("2nd Function Before 5")
body, exp = [], []
for rg in REGIONS:
    for g in GROUPS[:2]:
        crit = base(rg) + f',{OG},"{g}"'
        s_ = cl[(cl["region"] == rg) & (cl["group"] == g)]
        k_ = int((s_["date2_before5"] == "Yes").sum())
        lo, hi = wil(k_, len(s_))
        body.append([f"{rg} | {g}", f"=COUNTIFS({crit})", f'=COUNTIFS({crit},{B5},"Yes")', "=IFERROR(C{r}/B{r},0)", WLO, WHI])
        exp.append([f"{rg} | {g}", len(s_), k_, k_ / len(s_) if len(s_) else 0, lo, hi])
t_b5 = sh.add_table("before5", "Clients that reached 5: had a second function by the day they reached 5",
                    ["Region | group", "Clients", "2nd function before 5", "Share", "95% range (low)", "95% range (high)"], body,
                    formats=[None, "#,##0", "#,##0", "0.0%", "0.0%", "0.0%"], expected=exp, n_col="Clients", min_n=30,
                    note="A 'No' can also mean the second function's role was not matched; see the role match rate on the Method & Scope tab.")

# ---------------------------------------------------------------- 3g after 5
sh = wb.add_tab("After 5", explanation=cx(
    "What happens to clients once they reach 5 seats, and whether 5 seats behaves like a retention threshold. The first "
    "table follows clients 12, 24 and 36 months after the day they reached 5. The second compares the share of clients still "
    "with staff today across peak-size bands, for clients at least 24 months old, so every band had the same chance to churn. "
    "The third shows how far 5+ clients keep growing."))
S12, S24 = COL("Status 12m After 5"), COL("Status 24m After 5")
body, exp = [], []
for rg in REGIONS:
    crit = base(rg) + f',{D5},">=0"'
    s_ = cl[(cl["region"] == rg) & cl["days_to5"].notna()]
    row, e = [rg, f"=COUNTIFS({crit})"], [rg, len(s_)]
    for m, col, sc_ in [(12, "status_5p365", COL("Status 12m After 5")), (24, "status_5p730", COL("Status 24m After 5")),
                        (36, "status_5p1095", COL("Status 36m After 5"))]:
        ee = s_[s_[col] != "Too early"]
        k_ = int((ee[col] == "Active").sum())
        lo_, hi_ = wil(k_, len(ee))
        F_, A_ = f"{{c:Followed {m}m}}{{r}}", f"{{c:Active {m}m later}}{{r}}"
        row += [f'=COUNTIFS({crit},{sc_},"Active")+COUNTIFS({crit},{sc_},"Churned")', f'=COUNTIFS({crit},{sc_},"Active")',
                f"=IFERROR({A_}/{F_},0)", wlo(A_, F_), whi(A_, F_)]
        e += [len(ee), k_, k_ / len(ee) if len(ee) else 0, lo_, hi_]
    body.append(row)
    exp.append(e)
cols5 = ["Region", "Reached 5"]
for m in (12, 24, 36):
    cols5 += [f"Followed {m}m", f"Active {m}m later", f"% active at {m}m", f"{m}m low", f"{m}m high"]
t_ret5 = sh.add_table("ret5", "Still with staff 12, 24 and 36 months after reaching 5 seats", cols5, body,
                      formats=[None, "#,##0"] + ["#,##0", "#,##0", "0.0%", "0.0%", "0.0%"] * 3, expected=exp,
                      note="Active = at least one staff stint on that day. 'Followed' excludes clients that reached 5 too recently to be checked. "
                           "low / high = Wilson 95% range.")
PB = [("Peak 1 seat", 0, 1), ("Peak 2 seats", 2, 2), ("Peak 3-4 seats", 3, 4), ("Peak 5-9 seats", 5, 9), ("Peak 10+ seats", 10, 100000)]
body, exp = [], []
for rg in REGIONS:
    for lab, lo, hi in PB:
        crit = base(rg, 730) + f',{PK},">={lo}",{PK},"<={hi}"'
        s_ = cl[(cl["region"] == rg) & (cl["age"] >= 730) & (cl["peak"] >= lo) & (cl["peak"] <= hi)]
        k_ = int((s_["current"] > 0).sum())
        lo_, hi_ = wil(k_, len(s_))
        body.append([f"{rg} | {lab}", f"=COUNTIFS({crit})", f'=COUNTIFS({crit},{CUR},">0")', "=IFERROR(C{r}/B{r},0)", WLO, WHI])
        exp.append([f"{rg} | {lab}", len(s_), k_, k_ / len(s_) if len(s_) else 0, lo_, hi_])
t_pk = sh.add_table("peakret", "Still with staff today, by peak seats (clients aged 24+ months)",
                    ["Region | peak size", "Clients", "Still with staff", "% still with staff", "95% range (low)", "95% range (high)"], body,
                    formats=[None, "#,##0", "#,##0", "0.0%", "0.0%", "0.0%"], expected=exp, n_col="Clients", min_n=30,
                    note="Peak = highest number of staff at the same time. Clients aged 24+ months on the extract date, so all bands are compared at the same "
                         "age. Caution: a client that stays longer has more time to reach a high peak, so part of this link runs from tenure to size.")
sh.add_chart(t_pk, kind="bar", cats="Region | peak size", values=["% still with staff"], title="Still with staff today, by peak seats", y_format="0%")
# two-proportion test: peak under 5 vs 5+
ptests = {}
for rg in REGIONS:
    s_ = cl[(cl["region"] == rg) & (cl["age"] >= 730)]
    a, b = s_[s_["peak"] >= 5], s_[s_["peak"] < 5]
    ptests[rg] = st.two_proportion_test(int((a["current"] > 0).sum()), len(a), int((b["current"] > 0).sum()), len(b))
body, exp = [], []
for rg in REGIONS:
    s_ = cl[(cl["region"] == rg) & (cl["age"] >= 730)]
    a, b = s_[s_["peak"] >= 5], s_[s_["peak"] < 5]
    body.append([rg, f'=COUNTIFS({base(rg, 730)},{PK},">=5")', f'=COUNTIFS({base(rg, 730)},{PK},">=5",{CUR},">0")/B{{r}}',
                 f'=COUNTIFS({base(rg, 730)},{PK},"<5")', f'=COUNTIFS({base(rg, 730)},{PK},"<5",{CUR},">0")/D{{r}}',
                 "=C{r}-E{r}", ptests[rg]["p_value"]])
    exp.append([rg, len(a), (a["current"] > 0).mean(), len(b), (b["current"] > 0).mean(),
                (a["current"] > 0).mean() - (b["current"] > 0).mean(), ptests[rg]["p_value"]])
t_pt = sh.add_table("ptest", "Peak 5+ vs peak under 5: share still with staff (clients aged 24+ months)",
                    ["Region", "Peak 5+ clients", "Peak 5+ % active", "Peak under 5 clients", "Peak under 5 % active",
                     "Difference (points)", "p-value"], body,
                    formats=[None, "#,##0", "0.0%", "#,##0", "0.0%", "0.0%", "0.0000"], expected=exp, static_cols=["p-value"],
                    note="p-value = two-proportion z-test computed in Python (stats_helpers.two_proportion_test) at build time; p < 0.05 = difference unlikely to be chance.")
GR = [("Reached 10+ seats", 10), ("Reached 20+ seats", 20)]
body, exp = [], []
for rg in REGIONS:
    for g in GROUPS[:2]:
        crit = base(rg) + f',{OG},"{g}"'
        s_ = cl[(cl["region"] == rg) & (cl["group"] == g)]
        body.append([f"{rg} | {g}", f"=COUNTIFS({crit})", f'=IFERROR(COUNTIFS({crit},{PK},">=10")/B{{r}},0)',
                     f'=IFERROR(COUNTIFS({crit},{PK},">=20")/B{{r}},0)', f"=IFERROR(AVERAGEIFS({PK},{crit}),0)",
                     f"=IFERROR(AVERAGEIFS({CUR},{crit}),0)", f'=IFERROR(COUNTIFS({crit},{CUR},0)/B{{r}},0)'])
        exp.append([f"{rg} | {g}", len(s_), (s_["peak"] >= 10).mean(), (s_["peak"] >= 20).mean(), s_["peak"].mean(),
                    s_["current"].mean(), (s_["current"] == 0).mean()])
t_grow = sh.add_table("grow5", "How far 5+ clients grow, fast vs slow",
                      ["Region | group", "Clients", "% reached 10+", "% reached 20+", "Avg peak seats", "Avg current seats", "% churned since"], body,
                      formats=[None, "#,##0", "0.0%", "0.0%", "0.0", "0.0", "0.0%"], expected=exp, n_col="Clients", min_n=30,
                      note="Fast clients have usually been with Cloudstaff for a different length of time than slow ones; compare with the client age on Outcome Groups.")

# ---------------------------------------------------------------- 3h seat trajectory
sh = wb.add_tab("Seat Trajectory", explanation=cx(
    "Seats at fixed points after the first staff start, for each outcome group: medians (the typical client) first, then "
    "averages and the number of clients behind each point. Each point counts only clients old enough to have reached it, "
    "so the later points rest on older clients. Use the lines to see when the groups separate."))
CP = [("Day 30", 30), ("Day 90", 90), ("Day 180", 180), ("Month 12", 365), ("Month 24", 730), ("Month 36", 1095)]
traj = {}
for rg in REGIONS:
    body, exp = [], []
    for lab, d in CP:
        row, e = [lab], [lab]
        for g in GROUPS:
            row.append(f'=IFERROR(AVERAGEIFS({COL(f"Seats D{d}")},{base(rg, d)},{OG},"{g}"),0)')
            s_ = cl[(cl["region"] == rg) & (cl["group"] == g) & (cl["age"] >= d)]
            e.append(s_[f"seats_d{d}"].mean() if len(s_) else 0)
        body.append(row)
        exp.append(e)
    mb, nb_, ne_ = [], [], []
    for lab, d in CP:
        mrow, nrow, nexp = [lab, f"=COUNTIFS({base(rg, d)})"], [lab], [lab]
        for g in GROUPS:
            s_ = cl[(cl["region"] == rg) & (cl["group"] == g) & (cl["age"] >= d)]
            mrow.append(float(s_[f"seats_d{d}"].median()) if len(s_) else 0.0)
            nrow.append(f'=COUNTIFS({base(rg, d)},{OG},"{g}")')
            nexp.append(len(s_))
        mb.append(mrow)
        nb_.append(nrow)
        ne_.append(nexp)
    tm = sh.add_table(f"trajmed_{rg}", f"{rg}: median seats over time by outcome group", ["Checkpoint", "Clients counted"] + GROUPS, mb,
                      formats=[None, "#,##0"] + ["0.0"] * 4,
                      expected=[[m[0], int(((cl["region"] == rg) & (cl["age"] >= d)).sum())] + m[2:] for m, (_, d) in zip(mb, CP)], static_cols=GROUPS,
                      note="Medians computed in Python (pandas) at build time from the Raw Data client rows (a grouped median needs an array formula). "
                           "Clients counted at a checkpoint only if at least that old.")
    sh.add_chart(tm, kind="line", cats="Checkpoint", values=GROUPS, title=f"{rg}: median seats over time by outcome group", anchor="below")
    traj[rg] = sh.add_table(f"traj_{rg}", f"{rg}: average seats over time by outcome group", ["Checkpoint"] + GROUPS, body,
                            formats=[None] + ["0.0"] * 4, expected=exp,
                            note="Seats = concurrent staff on that day. Averages are pulled up by a few large accounts; read with the medians above. "
                                 "Where an average falls at a later checkpoint, the set of clients old enough to count has changed and some have churned; "
                                 "compare with the medians and client counts in the tables above before reading it as a fall for the typical client.")
    sh.add_table(f"trajn_{rg}", f"{rg}: clients counted at each checkpoint", ["Checkpoint"] + GROUPS, nb_,
                 formats=[None] + ["#,##0"] * 4, expected=ne_, note="Clients at least as old as the checkpoint on the extract date.")

# ---------------------------------------------------------------- 3h2 path to 10+
sh = wb.add_tab("Path to 10+", explanation=cx(
    "Which early signs go with becoming a meaningfully larger customer, taken here as 10 or more seats at the same time "
    "within 24 months. Only clients at least 24 months old are counted (2021 to 2024 starters). Compare each rate with its "
    "95% range; small rows are flagged and should not be ranked."))
D10 = COL("Days to 10")
OUT10 = ("Reached 10 within 24 months", f'{D10},"<=730"', lambda d: d["days_to10"] <= 730)
FAST = COL("Fast 5 (within 6m)")
lv10 = []
for rg in REGIONS:
    for lab, lo, hi in [("0-1 seats", 0, 1), ("2 seats", 2, 2), ("3-4 seats", 3, 4), ("5+ seats", 5, 99999)]:
        lv10.append((f"{rg} | Seats at day 90: {lab}", rg, f',{COL("Seats D90")},">={lo}",{COL("Seats D90")},"<={hi}"',
                     (cl["seats_d90"] >= lo) & (cl["seats_d90"] <= hi)))
t_10a, exp_10a = rate_table(sh, "path10_seats", "Reached 10 within 24 months, by seats at day 90", lv10,
                            "Clients aged 24+ months. 10+ = 10 or more concurrent staff on any day. Chi-square test: see 'Seats at day 90, outcome reach 10 in 24 months' "
                            "in the test table on Early Signals (some expected counts are small).", age=730, outcome=OUT10)
sh.add_chart(t_10a, kind="bar", cats="Segment", values=["Rate"], title="Reached 10 within 24 months, by seats at day 90", y_format="0%", anchor="below")
lv10b = []
for rg in REGIONS:
    lv10b.append((f"{rg} | Reached 5 within 6 months", rg, f",{FAST},1", cl["days_to5"] <= P.FAST_DAYS))
    lv10b.append((f"{rg} | Not 5 within 6 months, under 5 at day 90, added staff days 31-90", rg,
                  f',{FAST},0,{COL("Seats D90")},"<5",{COL("Adds D31-90")},">=1"',
                  ~(cl["days_to5"] <= P.FAST_DAYS) & (cl["seats_d90"] < 5) & (cl["adds_31_90"] >= 1)))
    lv10b.append((f"{rg} | Not 5 within 6 months, under 5 at day 90, no adds days 31-90", rg,
                  f',{FAST},0,{COL("Seats D90")},"<5",{COL("Adds D31-90")},0',
                  ~(cl["days_to5"] <= P.FAST_DAYS) & (cl["seats_d90"] < 5) & (cl["adds_31_90"] == 0)))
t_10b, exp_10b = rate_table(sh, "path10_speed", "Reached 10 within 24 months, by speed to 5 and early adds", lv10b,
                            "Clients aged 24+ months. The three rows per region cover every client of that age: a client not at 5 within 6 months "
                            "is always under 5 at day 90. Reached 5 within 6 months is partly the outcome itself, so read the seats-at-day-90 table as the early signal.", age=730, outcome=OUT10)
chi_results.append(("Seats at day 90, outcome reach 10 in 24 months", chi_for(lv10, age=730, ofun=OUT10[2])))

# ---------------------------------------------------------------- 3i predictive model (statsmodels, values)
import statsmodels.api as sm   # noqa: E402

FEATS = [("Seats at day 90 (0-4)", lambda d: d["seats_d90"].astype(float)),
         ("Staff added days 31-90 (capped at 3)", lambda d: d["adds_31_90"].clip(upper=3).astype(float)),
         ("2+ functions hired by day 90", lambda d: (d["functions_by_d90"] >= 2).astype(float)),
         ("Any leaver in first 90 days", lambda d: (d["leavers_90"] >= 1).astype(float)),
         ("OPTI brand", lambda d: (d["brand"] == "OPTI").astype(float))]


def auc(y, s):
    y, s = np.asarray(y), np.asarray(s)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()) / (len(pos) * len(neg)))


model = {}
for rg in REGIONS:
    d = cl[(cl["region"] == rg) & obs12 & u5].copy()
    Xm = pd.DataFrame({k: f(d) for k, f in FEATS}, index=d.index)
    y = (d["days_to5"] <= 365).astype(int)
    fit = sm.Logit(y, sm.add_constant(Xm)).fit(disp=0)
    ci = fit.conf_int()
    rng = np.random.default_rng(42)
    fold = rng.permutation(len(d)) % 5
    cv = np.zeros(len(d))
    for k in range(5):
        tr, te = fold != k, fold == k
        f_k = sm.Logit(y[tr], sm.add_constant(Xm[tr])).fit(disp=0)
        cv[te] = f_k.predict(sm.add_constant(Xm[te], has_constant="add"))
    model[rg] = {"n": len(d), "events": int(y.sum()), "auc_cv": auc(y, cv), "or": np.exp(fit.params), "lo": np.exp(ci[0]),
                 "hi": np.exp(ci[1]), "p": fit.pvalues}
sh = wb.add_tab("Predictive Model", explanation=cx(
    "A combined check of the early signals, run separately for each region on clients that were still under 5 seats at "
    "day 90 and are at least 12 months old. An odds ratio above 1 means the signal goes with a higher chance of reaching 5 "
    "within 12 months, holding the other signals equal. The cross-validated AUC shows how well the signals sort clients "
    "(0.5 = no better than chance, 1.0 = perfect). These are associations, not causes."))
body, exp = [], []
for rg in REGIONS:
    m = model[rg]
    for k, _ in FEATS:
        body.append([f"{rg} | {k}", f'=COUNTIFS({base(rg, 365)}{U5})', m["or"][k], m["lo"][k], m["hi"][k], m["p"][k]])
        exp.append([f"{rg} | {k}", m["n"], m["or"][k], m["lo"][k], m["hi"][k], m["p"][k]])
t_mod = sh.add_table("model", "Logistic regression: odds of reaching 5 within 12 months (clients under 5 at day 90)",
                     ["Region | signal", "Clients in model", "Odds ratio", "95% range (low)", "95% range (high)", "p-value"], body,
                     formats=[None, "#,##0", "0.00", "0.00", "0.00", "0.0000"], expected=exp,
                     static_cols=["Odds ratio", "95% range (low)", "95% range (high)", "p-value"],
                     note="Model output computed in Python (statsmodels Logit) at build time from the Raw Data client rows; not live formulas. "
                          "Re-run the build script or notebook to refresh.")
body, exp = [], []
for rg in REGIONS:
    body.append([rg, f'=COUNTIFS({base(rg, 365)}{U5})', f'=COUNTIFS({base(rg, 365)}{U5},{R12},1)', model[rg]["auc_cv"]])
    exp.append([rg, model[rg]["n"], model[rg]["events"], model[rg]["auc_cv"]])
t_fit = sh.add_table("model_fit", "Model sample and fit", ["Region", "Clients in model", "Reached 5 within 12 months", "Cross-validated AUC"], body,
                     formats=[None, "#,##0", "#,##0", "0.00"], expected=exp, static_cols=["Cross-validated AUC"],
                     note="AUC from 5-fold cross-validation (fixed seed 42), computed in Python at build time.")

# chi-square test summary (Early Signals, Industry, Initial Function)
sh_sig = [s for s in wb.sheets if s.name == "Early Signals"][0]
body, exp = [], []
for lab, res in chi_results:
    for rg in REGIONS:
        u = "under 5" in lab
        ag = 730 if "reach 10" in lab else 365
        body.append([f"{lab} | {rg}", f'=COUNTIFS({base(rg, ag)}{U5 if u else ""})', res[rg]])
        exp.append([f"{lab} | {rg}", int(((cl["region"] == rg) & (cl["age"] >= ag) & (u5 if u else True)).sum()), res[rg]])
t_chi = sh_sig.add_table("chi", "Chi-square tests: does the reach-5 rate differ across levels?", ["Signal | region", "Clients tested", "p-value"], body,
                         formats=[None, "#,##0", "0.0000"], expected=exp, static_cols=["p-value"],
                         note="Chi-square test of independence computed in Python (stats_helpers.chi_square) at build time. p < 0.05 = the rates differ by more than chance. "
                              "Industry and initial function results are listed here too.")

# ---------------------------------------------------------------- 3j research shortlist
sh = wb.add_tab("Research Shortlist", explanation=cx(
    "Candidate clients for primary research interviews, up to 8 per region and outcome group. Fast and slow 5+ clients "
    "are those still active, largest first. 'Not reached 5' lists active clients at least 12 months old, largest first. "
    "'Churned' lists clients at least 12 months old whose last staff left most recently, so contacts are more likely to be reachable. Check with "
    "the account manager before contacting anyone."))
last_end = rows[rows["inc"] & rows["valid"]].groupby("sc")["dd"].max()
cand = []
for rg in REGIONS:
    for g in GROUPS:
        s_ = cl[(cl["region"] == rg) & (cl["group"] == g)].copy()
        if g in GROUPS[:2]:
            s_ = s_[s_["current"] > 0].sort_values(["current", "peak"], ascending=False)
        elif g == GROUPS[2]:
            s_ = s_[s_["age"] >= 365].sort_values(["current", "age"], ascending=False)
        else:
            s_ = s_[s_["age"] >= 365].copy()
            s_["last"] = last_end.reindex(s_.index)
            s_ = s_.sort_values(["last", "peak"], ascending=False)
        for sc_ in s_.index[:8]:
            cand.append((rg, g, sc_))
names = df["Client Name"].groupby(rows["sc"]).first()
SC = COL("Shortcode")
body, exp = [], []
for rg, g, sc_ in cand:
    c = cl.loc[sc_]
    m = f'MATCH("{sc_}",{SC},0)'
    body.append([sc_, str(names.get(sc_, "")), rg, g, c["industry"], c["initial_function"],
                 f"=INDEX({COL('Client Start')},{m})", f"=INDEX({PK},{m})", f"=INDEX({CUR},{m})"])
    exp.append([sc_, None, None, None, None, None, c["start"].to_pydatetime(), int(c["peak"]), int(c["current"])])
t_short = sh.add_table("shortlist", "Interview candidates by region and outcome group",
                       ["Shortcode", "Client name", "Region", "Outcome group", "Industry", "Initial function", "Client start",
                        "Peak seats", "Current seats"], body,
                       formats=[None, None, None, None, None, None, "yyyy-mm-dd", "0", "0"], expected=exp,
                       note="Selected and sorted in Python at build time; dates and seat counts are live lookups to Raw Data.")

# ---------------------------------------------------------------- 3k method & scope
sh = wb.add_tab("Method & Scope", explanation=cx(
    "What is in the analysis and how the added fields were built. Rows come from the StaffCentral engagement list; region "
    "and industry come from the MyStaff client list (27 Sep 2026); role titles come from the monthly billed report. Company "
    "size and gross margin are not in any of these files, so they are listed as a data request at the bottom."))
SCOPE = COL("Scope")
scope_order = list(pd.Series(rows["scope"]).value_counts().index)
body = [[s_, f"=COUNTIF({SCOPE},A{{r}})", "=IFERROR(B{r}/SUM($B${first}:$B${last}),0)"] for s_ in scope_order]
exp = [[s_, int((rows["scope"] == s_).sum()), (rows["scope"] == s_).mean()] for s_ in scope_order]
t_scope = sh.add_table("scope", "Engagement rows by scope", ["Scope", "Rows", "Share of rows"], body,
                       formats=[None, "#,##0", "0.0%"], expected=exp, pct_sum_col="Share of rows",
                       total={"label": "Total", "cells": {"Rows": "=SUM({c:Rows}{first}:{c:Rows}{last})"}}, expected_total=[None, N, None],
                       note="Internal-unit rule approved 2026-09-30 (organic growth analysis). Client started before 2021 = outside the requested cohort.",
                       reconcile={"Rows": f"=ROWS({SCOPE})"})
RR = COL("Region Rule")
body, exp = [], []
for rg in REGIONS:
    for br in ["Cloudstaff", "OPTI"]:
        s_ = cl[(cl["region"] == rg) & (cl["brand"] == br)]
        body.append([f"{rg} | {br}", f'=COUNTIFS({base(rg)},{COL("Brand")},"{br}")',
                     f'=COUNTIFS({base(rg)},{COL("Brand")},"{br}",{RR},"office country")'])
        exp.append([f"{rg} | {br}", len(s_), int(sum(ms[x]["region_rule"] == "office country" for x in s_.index)) if br == "OPTI" else 0])
t_reg = sh.add_table("region", "Clients in scope by region and brand", ["Region | brand", "Clients", "OPTI region set by office country"], body,
                     formats=[None, "#,##0", "#,##0"], expected=exp,
                     total={"label": "Total", "cells": {"Clients": "=SUM({c:Clients}{first}:{c:Clients}{last})"}},
                     expected_total=[None, len(cl), None],
                     note="OPTI clients: region from office country, else timezone, else billing currency (Australia, New Zealand, Asia = APAC; rest = AMER).",
                     reconcile={"Clients": f'=COUNTIFS({CRW},"Y",{INC})'})
MR, ED = COL("Matched Role"), COL("Engagement Date")
body, exp = [], []
inr = rows[rows["inc"]]
for y in sorted(inr["ed"].dt.year.unique()):
    crit = f'{ED},">="&DATE({y},1,1),{ED},"<"&DATE({y + 1},1,1),{INC}'
    s_ = inr[inr["ed"].dt.year == y]
    body.append([str(y), f"=COUNTIFS({crit})", f'=COUNTIFS({crit},{MR},"<>")', "=IFERROR(C{r}/B{r},0)"])
    exp.append([str(y), len(s_), int(s_["role"].notna().sum()), s_["role"].notna().mean()])
t_match = sh.add_table("match", "Role match rate by engagement start year (in-scope rows)",
                       ["Engagement year", "Staff stints", "Matched to a role", "Match rate"], body,
                       formats=[None, "#,##0", "#,##0", "0.0%"], expected=exp,
                       note="Match = same staff name and a billed-report kick-off date within 60 days of the Engagement Date.",
                       reconcile={"Staff stints": f'=COUNTIF({COL("Include")},"Y")'},
                       total={"label": "Total", "cells": {"Staff stints": "=SUM({c:Staff stints}{first}:{c:Staff stints}{last})",
                                                          "Matched to a role": "=SUM({c:Matched to a role}{first}:{c:Matched to a role}{last})",
                                                          "Match rate": "=IFERROR(C{r}/B{r},0)"}},
                       expected_total=[None, len(inr), int(inr["role"].notna().sum()), float(inr["role"].notna().mean())])
FN = COL("Function")
body, exp = [], []
for f in P.FUNCTION_ORDER:
    body.append([f, f'=COUNTIFS({FN},A{{r}},{INC})', "=IFERROR(B{r}/SUM($B${first}:$B${last}),0)"])
    exp.append([f, int((inr["function"] == f).sum()), (inr["function"] == f).mean()])
t_fnmap = sh.add_table("functions", "Staff stints by function family (in scope)", ["Function", "Staff stints", "Share"], body,
                       formats=[None, "#,##0", "0.0%"], expected=exp, pct_sum_col="Share",
                       note="Keyword rules in work/icp_growth_potential/icp_prep.py (FUNCTIONS), applied in order; first match wins.",
                       reconcile={"Staff stints": f'=COUNTIF({COL("Include")},"Y")'},
                       total={"label": "Total", "cells": {"Staff stints": "=SUM({c:Staff stints}{first}:{c:Staff stints}{last})"}},
                       expected_total=[None, len(inr), None])
sh.add_bullets([
    "Company size (employees, annual revenue): pull HubSpot company properties 'Number of employees' and 'Annual revenue' "
    "with the MyStaff shortcode (or CRM Company ID, which is in the MyStaff client list) for all clients started since 2021.",
    "Gross margin / account economics: pull the monthly invoice lines by shortcode from Finance (NetSuite): Cloudstaff fee, "
    "employee direct cost and other charges per month since 2021. The billed report has a Cloudstaff fee only for 2019, 2020 and 2024 new seats, which is too patchy to use.",
    "Function: StaffCentral job title or department per engagement would replace the name-and-date role match and remove the 'Unknown' group.",
], heading="Data request: fields needed to answer the remaining questions")

# ---------------------------------------------------------------- 4 summary
s = wb.summary
speed_exp = {e[0]: e for e in [t for t in wb.tables if t["key"] == "speed"][0]["expected"]}
r12 = {rg: cl[(cl["region"] == rg) & obs12] for rg in REGIONS}
rate12 = {rg: float((r12[rg]["days_to5"] <= 365).mean()) for rg in REGIONS}
s.add_kpis([
    {"label": "Clients in scope", "formula": f'=COUNTIFS({CRW},"Y",{INC})', "fmt": "#,##0", "expected": len(cl),
     "caption": "Started Jan 2021 to Oct 2026, AMER and APAC"},
    {"label": "AMER: reached 5 within 6 months", "formula": f"={t_speed.ref('Within 6 months', 'AMER %')}", "fmt": "0.0%",
     "expected": speed_exp["Within 6 months"][3],
     "caption": f"Within 12 months: {num(t_speed.ref('Within 12 months', 'AMER %'), '0.0%')}"},
    {"label": "APAC: reached 5 within 6 months", "formula": f"={t_speed.ref('Within 6 months', 'APAC %')}", "fmt": "0.0%",
     "expected": speed_exp["Within 6 months"][8],
     "caption": f"Within 12 months: {num(t_speed.ref('Within 12 months', 'APAC %'), '0.0%')}"},
    {"label": "Still active: peak 5+ vs under 5", "formula": f"={t_pt.ref('AMER', 'Peak 5+ % active')}", "fmt": "0%",
     "expected": float((cl[(cl['region'] == 'AMER') & (cl['age'] >= 730) & (cl['peak'] >= 5)]['current'] > 0).mean()),
     "caption": f"AMER, clients aged 24+ months; peak under 5: {num(t_pt.ref('AMER', 'Peak under 5 % active'), '0%')}. "
                f"APAC: {num(t_pt.ref('APAC', 'Peak 5+ % active'), '0%')} vs {num(t_pt.ref('APAC', 'Peak under 5 % active'), '0%')}"},
])


def ref_rate(t, label):
    return num(t.ref(label, "Rate"), "0%")


def sig_word(p):
    return "p < 0.05" if p < 0.05 else "p >= 0.05, not a clear difference"


chi = {lab: res for lab, res in chi_results}
ind_top = {}
for rg in REGIONS:
    cand_i = [e for e in exp_ind if e[0].startswith(rg) and e[1] >= 30 and not e[0].endswith(("Other industries", "Unknown industry"))]
    ind_top[rg] = (max(cand_i, key=lambda e: e[3]), min(cand_i, key=lambda e: e[3])) if cand_i else None
fn_rows = {rg: [e for e in exp_fn if e[0].startswith(rg) and e[1] >= 30 and not e[0].endswith(("Unknown", "(under 30 clients)"))] for rg in REGIONS}
sig_model = {rg: [k for k, _ in FEATS if model[rg]["p"][k] < 0.05] for rg in REGIONS}
top_fn = {rg: max(fn_rows[rg], key=lambda e: e[3]) for rg in REGIONS}
pk_rates = {rg: [e[3] for e in [x for x in wb.tables if x["key"] == "peakret"][0]["expected"] if e[0].startswith(rg)] for rg in REGIONS}
steady = all(all(b_ > a_ for a_, b_ in zip(v, v[1:])) for v in pk_rates.values())
mom_p = chi["Staff added days 31-90 (under 5 at day 90)"]
fun_p = chi["Functions hired by day 90 (under 5 at day 90)"]
both_sig = lambda d: max(d.values()) < 0.05
# which functions does the top function's 95% range clear in both regions (its low above their high)?
clear_sets, overlap_each = [], True
for rg in REGIONS:
    top = top_fn[rg]
    others = [e for e in fn_rows[rg] if e[0] != top[0]]
    clear_sets.append({e[0].split(" | ")[1] for e in others if top[4] > e[5]})
    overlap_each &= any(top[4] <= e[5] for e in others)
clear_fn = set.intersection(*clear_sets) if clear_sets else set()
# reach-10 test without the small 5+ rows (robustness of the chi-square in finding 8)
chi10_no5 = chi_for([x for x in lv10 if "5+" not in x[0]], age=730, ofun=OUT10[2])
findings = [
    f"Few clients reach 5 seats, and many of those that do start large. Of clients at least 12 months old, "
    f"{num(t_speed.ref('Within 12 months', 'AMER %'), '0.0%')} in AMER and {num(t_speed.ref('Within 12 months', 'APAC %'), '0.0%')} in APAC "
    f"reached 5 within 12 months, and {num(t_speed.ref('Within 6 months', 'AMER %'), '0.0%')} and {num(t_speed.ref('Within 6 months', 'APAC %'), '0.0%')} "
    f"within 6 months" + (" (AMER higher than APAC at both points, p < 0.05)" if max(speed_tests.values()) < 0.05 else "") + ". "
    f"Among clients that reached 5, {num(t_t5.ref('Within 30 days', 'AMER share'), '0%')} (AMER) and {num(t_t5.ref('Within 30 days', 'APAC share'), '0%')} "
    f"(APAC) did so within 30 days, while {num(t_t5.ref('12-24 months', 'AMER share'), '0%')} and {num(t_t5.ref('12-24 months', 'APAC share'), '0%')} "
    "took 12-24 months, so a real slow path exists, especially in APAC.",
    (f"Starting size is closely linked to reaching 5. Clients with 1 seat at day 30 reached 5 within 12 months at "
     f"{ref_rate(t_s30, 'AMER | 1 seat')} (AMER) and {ref_rate(t_s30, 'APAC | 1 seat')} (APAC), against "
     f"{ref_rate(t_s30, 'AMER | 3-4 seats')} and {ref_rate(t_s30, 'APAC | 3-4 seats')} for clients with 3-4 seats "
     f"(chi-square p < 0.05 in both regions).") if both_sig(chi["Seats at day 30"]) else
    "Seats at day 30 are not clearly linked to reaching 5 in both regions; see Early Signals for the test results.",
    f"For clients still under 5 at day 90, those that added staff in days 31-90 reached 5 at "
    f"{ref_rate(t_sig, 'AMER | Staff added days 31-90: 1+')} (AMER) and {ref_rate(t_sig, 'APAC | Staff added days 31-90: 1+')} (APAC), "
    f"against {ref_rate(t_sig, 'AMER | Staff added days 31-90: none')} and {ref_rate(t_sig, 'APAC | Staff added days 31-90: none')} for those that added none"
    + (" (chi-square p < 0.05 in both regions)" if both_sig(mom_p) else "") + ". "
    f"Clients that had hired into 2 or more functions by day 90 reached 5 at {ref_rate(t_sig, 'AMER | Functions hired by day 90: 2+')} and "
    f"{ref_rate(t_sig, 'APAC | Functions hired by day 90: 2+')}, against {ref_rate(t_sig, 'AMER | Functions hired by day 90: 0-1')} and "
    f"{ref_rate(t_sig, 'APAC | Functions hired by day 90: 0-1')} with one function or none"
    + (" (chi-square p < 0.05 in both regions)." if both_sig(fun_p) else "."),
    f"When the early signals are combined, seats at day 90 carry most of the information: each extra seat goes with about "
    f"{num(t_mod.ref('AMER | Seats at day 90 (0-4)', 'Odds ratio'), '0.0')} times the odds of reaching 5 within 12 months in AMER and "
    f"{num(t_mod.ref('APAC | Seats at day 90 (0-4)', 'Odds ratio'), '0.0')} in APAC. "
    + ("Once seats at day 90 are in the model, early adds and a second function show no clear extra link (p >= 0.05); their link to "
       "reaching 5 overlaps with seat count. " if all(set(sig_model[rg]) <= {"Seats at day 90 (0-4)"} for rg in REGIONS) else
       "Other signals that hold up on their own are listed on Predictive Model. ")
    + f"The model sorts clients well (cross-validated AUC {num(t_fit.ref('AMER', 'Cross-validated AUC'), '0.00')} AMER, "
    f"{num(t_fit.ref('APAC', 'Cross-validated AUC'), '0.00')} APAC; 0.5 = chance).",
    ("Industry shows no clear difference in either region (chi-square p >= 0.05). " if not any(v < 0.05 for v in chi["Industry"].values()) else
     f"Industry: AMER {sig_word(chi['Industry']['AMER'])}; APAC {sig_word(chi['Industry']['APAC'])}. ")
    + ((f"The initial function is linked to reaching 5 (p < 0.05 in both regions). {top_fn['AMER'][0].split(' | ')[1]} starters reached 5 at "
        f"{num(t_fn.ref(top_fn['AMER'][0], 'Rate'), '0%')} (AMER) and {num(t_fn.ref(top_fn['APAC'][0], 'Rate'), '0%')} (APAC), against "
        f"{num(t_speed.ref('Within 12 months', 'AMER %'), '0%')} and {num(t_speed.ref('Within 12 months', 'APAC %'), '0%')} for all clients. "
        f"Its 95% range is clear of {' and '.join([', '.join(sorted(clear_fn)[:-1]), sorted(clear_fn)[-1]]) if len(clear_fn) > 1 else next(iter(clear_fn))} in both regions but overlaps at least one other function in each region, "
        "so treat it as a lead for the research rather than a proven ranking.")
       if both_sig(chi["Initial function"]) and top_fn['AMER'][0].split(' | ')[1] == top_fn['APAC'][0].split(' | ')[1] and clear_fn and overlap_each else
       f"Initial function: AMER {sig_word(chi['Initial function']['AMER'])}; APAC {sig_word(chi['Initial function']['APAC'])}; see the tab, ranges overlap."),
    ("Retention rises step by step with size rather than jumping at 5 seats. " if steady else "Retention is higher for larger clients. ")
    + f"Of clients aged 24+ months, {num(t_pk.ref('AMER | Peak 1 seat', '% still with staff'), '0%')} of AMER clients that peaked at 1 seat still have staff, "
    f"{num(t_pk.ref('AMER | Peak 3-4 seats', '% still with staff'), '0%')} at 3-4, {num(t_pk.ref('AMER | Peak 5-9 seats', '% still with staff'), '0%')} at 5-9 "
    f"and {num(t_pk.ref('AMER | Peak 10+ seats', '% still with staff'), '0%')} at 10+; APAC runs from "
    f"{num(t_pk.ref('APAC | Peak 1 seat', '% still with staff'), '0%')} to {num(t_pk.ref('APAC | Peak 10+ seats', '% still with staff'), '0%')}. "
    f"Peak 5+ vs under 5: AMER {sig_word(ptests['AMER']['p_value'])}, APAC {sig_word(ptests['APAC']['p_value'])}. "
    "Clients that stay longer also have more time to reach a high peak, so part of this link runs from tenure to size.",
    f"After reaching 5, most clients stay: {num(t_ret5.ref('AMER', '% active at 12m'), '0%')} (AMER) and "
    f"{num(t_ret5.ref('APAC', '% active at 12m'), '0%')} (APAC) still had staff 12 months later, "
    f"{num(t_ret5.ref('AMER', '% active at 24m'), '0%')} and {num(t_ret5.ref('APAC', '% active at 24m'), '0%')} after 24 months, and "
    f"{num(t_ret5.ref('AMER', '% active at 36m'), '0%')} and {num(t_ret5.ref('APAC', '% active at 36m'), '0%')} after 36 months.",
    f"Becoming a larger customer (10+ seats within 24 months, clients aged 24+ months) also shows early: "
    f"{num(t_10a.ref('AMER | Seats at day 90: 0-1 seats', 'Rate'), '0.0%')} (AMER) and {num(t_10a.ref('APAC | Seats at day 90: 0-1 seats', 'Rate'), '0.0%')} (APAC) of clients with 0-1 seats "
    f"at day 90 got there, against {ref_rate(t_10a, 'AMER | Seats at day 90: 3-4 seats')} and {ref_rate(t_10a, 'APAC | Seats at day 90: 3-4 seats')} with 3-4 seats "
    f"and {ref_rate(t_10a, 'AMER | Seats at day 90: 5+ seats')} and {ref_rate(t_10a, 'APAC | Seats at day 90: 5+ seats')} with 5+ "
    + ("(chi-square p < 0.05 in both regions, in the test table on Early Signals; some expected counts are small, but the result also holds "
       "without the 5+ rows; the APAC 5+ row has fewer than 30 clients)." if both_sig(chi["Seats at day 90, outcome reach 10 in 24 months"]) and both_sig(chi10_no5)
       else "(see the test table on Early Signals; the APAC 5+ row has fewer than 30 clients)."),
    f"Most 5+ clients branch into a new function: {num(t_exp.ref('AMER | 1 Fast 5+', '% clients that added a new function'), '0%')} of fast "
    f"and {num(t_exp.ref('AMER | 2 Slow 5+', '% clients that added a new function'), '0%')} of slow AMER 5+ clients added a new function after day 30, against "
    f"{num(t_exp.ref('AMER | 4 Churned, never 5', '% clients that added a new function'), '0%')} of clients that churned without reaching 5 "
    f"(APAC: {num(t_exp.ref('APAC | 1 Fast 5+', '% clients that added a new function'), '0%')}, "
    f"{num(t_exp.ref('APAC | 2 Slow 5+', '% clients that added a new function'), '0%')} and {num(t_exp.ref('APAC | 4 Churned, never 5', '% clients that added a new function'), '0%')}). "
    "Larger clients add more staff overall, so part of this gap comes with size.",
    "Not answered from this data: company size and gross margin (see the data request on Method & Scope). Role titles were matched for "
    f"{num(t_match.ref('Total', 'Match rate'), '0%')} of in-scope staff stints, so function results carry an 'Unknown' group. "
    "Small rows (under 30 clients) are flagged on each tab and not ranked.",
]
s.add_findings([cx(f) for f in findings])
s.add_recommendations([cx(f) for f in [
    "Marketing / ICP owner: build the high-growth profile around the size of the first order and the seat count by day 90, "
    "rather than industry, and use the primary research (Research Shortlist tab) to learn what made fast 5+ clients start "
    "bigger. Measure: share of new clients starting with 2+ seats, by region, each quarter.",
    "Sales and account management leads: treat the first 90 days as the expansion window and review single-seat clients "
    "before day 90. Measure: % of new clients with 2+ seats at day 90, tracked monthly by region.",
    "Data & Analytics: request HubSpot company size and Finance margin by shortcode (Method & Scope tab) and rerun this "
    "workbook with them. Measure: both fields joined for at least 90% of in-scope clients.",
]])
s.add_chart(t_speed, kind="line", cats="Window", values=["AMER %", "APAC %"], title="Cumulative share of clients reaching 5 seats", y_format="0%")
s.add_chart(t_pk, kind="bar", cats="Region | peak size", values=["% still with staff"], title="Still with staff today, by peak seats (aged 24+ months)", y_format="0%")

# ---------------------------------------------------------------- 5 checks + governance
wb.add_check("Every client with a Date Reached 5 had 5+ seats on that day (formula recount)",
             f'=COUNTIFS({COL("Seats on Date Reached 5")},"<5",{INC})', 0)
wb.add_check("Clients with peak 5+ equal clients with a Date Reached 5",
             f'=COUNTIFS({CRW},"Y",{PK},">=5",{INC})-COUNTIFS({CRW},"Y",{COL("Date Reached 5")},"<>",{INC})', 0)
wb.add_check("Clients with a new-function add equal clients with a Date 2nd Function",
             f'=COUNTIFS({CRW},"Y",{NEW},">0",{INC})-COUNTIFS({CRW},"Y",{COL("Date 2nd Function")},"<>",{INC})', 0)
wb.add_check("No client has more current seats than peak seats", f'=SUMPRODUCT(({CRW}="Y")*({CUR}<>"")*(N(+{CUR})>N(+{PK})))', 0)
wb.add_check("Outcome groups cover every client", f'=COUNTIFS({CRW},"Y",{INC})-COUNTIFS({OG},"?*",{INC})', 0)

sc_cnt = pd.Series(rows["scope"]).value_counts()
wb.log_decision("Internal units, Disengaged Staff Pool, test records (rule approved 2026-09-30)",
                int(sum(sc_cnt.get(k, 0) for k in ["Internal unit", "Internal unit (Hub 50%+)", "Disengaged Staff Pool", "Test record"])),
                "Excluded (Include = N); see Scope column", "Requester (2026-09-30 rule)", ["Category", "Shortcode", "Client Name"])
wb.log_decision("Internal = Yes in MyStaff or shortcode not in the MyStaff list", int(sc_cnt.get("Internal (MyStaff flag)", 0) + sc_cnt.get("Not in MyStaff client list", 0)),
                "Excluded (Include = N)", "Requester (delegated to analyst)", ["Shortcode"])
wb.log_decision("Region OPTI", int(sum(1 for x in cl.index if ms[x]["brand"] == "OPTI")),
                "Assigned APAC / AMER from MyStaff office country, timezone, then billing currency (clients)", "Requester (2026-10-08)", ["Shortcode"])
wb.log_decision("Region out of scope ('Internal', '-', 'VAR') or OPTI with no location", int(sc_cnt.get("Region out of scope or unknown", 0)),
                "Excluded (Include = N)", "Requester (delegated to analyst)", ["Shortcode"])
wb.log_decision("Client started before 2021", int(sc_cnt.get("Client started before 2021", 0)), "Excluded (Include = N): outside the requested cohort",
                "Requester (2026-10-08)", ["Engagement Date"])
wb.log_decision("Blank Shortcode", int(sc_cnt.get("Blank shortcode", 0)), "Excluded (Include = N)", "Requester (delegated to analyst)", ["Shortcode"])
wb.log_decision("Exact duplicate rows", int(sc_cnt.get("Duplicate row", 0)), "Second copy set to Include = N", "Requester (delegated to analyst)", ["duplicate"])
wb.log_decision("Disengagement Date before Engagement Date", int((~rows["valid"]).sum()),
                "Kept for client start; not counted in seats or adds (Valid Stint = N)", "Requester (delegated to analyst)", ["Disengagement Date", "Engagement Date"])
wb.log_decision("Engagement ID reused for a different row", int(df["Engagement ID"].duplicated(keep=False).sum()), "Kept and flagged",
                "Requester (delegated to analyst)", ["Engagement ID"])
wb.log_decision("Engagement Date after extract date (2026-10-07)", int((rows["ed"] > P.EXTRACT).sum()), "Kept; counted from its start date",
                "Requester (delegated to analyst)", ["Engagement Date"])
wb.log_decision("Role not matched to the billed report", int((rows["inc"] & rows["role"].isna()).sum()),
                "Function = Unknown; shown as its own group", "Requester (delegated to analyst)", ["CSID"])
wb.define("Seat", "One active staff stint on the client on a given day (headcount, all categories on external clients: Engaged, RTG and the few Hub rows that the 2026-09-30 internal-unit rule keeps)", "Engagement Date <= day <= Disengagement Date, or open")
wb.define("Client start", "First staff Engagement Date on the shortcode", "Client Start")
wb.define("Reached 5", "5 or more staff at the same time on any day", "Date Reached 5")
wb.define("Fast / Slow 5+", "Fast = reached 5 within 183 days (6 months) of client start; Slow = later", "Days to 5")
wb.define("Churned", "No active staff stint on the extract date", f"Current Seats = 0 on {P.EXTRACT:%Y-%m-%d}")
wb.define("Outcome group", "1 Fast 5+, 2 Slow 5+, 3 Not reached 5 and still active, 4 Churned without reaching 5", "Outcome Group")
wb.define("Initial function", "Most common known function among staff starting in the first 30 days", "Initial Function")
wb.define("Second function", "First staff added after day 30 in a known function different from the initial function", "Date 2nd Function")
wb.define("Extract date", "Date the StaffCentral list was pulled", f"{P.EXTRACT:%Y-%m-%d}, from the file name")
wb.define("95% range", "Wilson score interval for a proportion", "z = 1.96")
wb.attest("definitions_confirmed", True, "Fast = 6 months, four exclusive groups (requester, 2026-10-08)")
wb.attest("period_confirmed", True, "Client starts 2021 to 2026; OPTI assigned to APAC/AMER (requester, 2026-10-08)")
wb.attest("outliers_reviewed", True, "Large clients kept; rates shown alongside averages, averages flagged as skewed")
wb.attest("sample_sizes_reviewed", True, "Rows under 30 clients flagged and not ranked in findings")
wb.attest("no_causal_overreach", True, "Findings describe associations; model tab says associations, not causes")
wb.attest("requester_questions_answered", False, "Company size and gross margin not available in the data; data request listed")

result = wb.save(OUT)
