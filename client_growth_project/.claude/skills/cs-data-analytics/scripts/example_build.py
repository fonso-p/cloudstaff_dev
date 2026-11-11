"""Worked example: client churn analysis -> Cloudstaff-branded, QA-gated workbook.

Copy this file to the project's work folder, rename it (e.g. build_<topic>.py) and adapt it.
The shape to keep:
  1. load raw file losslessly         (profile_data.load_source)
  2. flag row issues                  (profile_data.row_issues)
  3. apply ONLY the ETL decisions the requester agreed, as added columns / Include flags
  4. build a clean pandas frame the SAME way, independently -> expected values
  5. write tabs: formulas reference Raw Data named ranges; pass `expected=` from pandas
  6. summary: KPIs + findings with num() tokens (never type numbers into text)
  7. log decisions, definitions, attestations -> save() runs the QA gate

Run:  python example_build.py <raw_csv> <output_xlsx>
"""
import os
import re
import sys
import datetime as dt

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cs_xl import CSWorkbook, const, num                      # noqa: E402
from profile_data import load_source, row_issues      # noqa: E402
import stats_helpers as st                             # noqa: E402

src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/client_churn_2026.csv"
out = sys.argv[2] if len(sys.argv) > 2 else f"outputs/excel/{dt.date.today():%Y-%m-%d}_Client_Churn_Review.xlsx"

# ---------------------------------------------------------------- 1-2 load + flag
df, meta = load_source(src)
issues = row_issues(
    df, required=["Client ID", "Region", "Start Date", "Seats"], numeric=["Seats", "Monthly Fee", "NPS"],
    dates=["Start Date", "End Date"], ids=["Client ID"], no_future=["End Date"],
    allowed={"Region": ["APAC", "AMER", "EMEA"]}, ranges={"Seats": (0, None), "NPS": (0, 10)})

# ---------------------------------------------------------------- 3 agreed ETL decisions
dup_mask = df.astype(str).duplicated(keep="first")
neg_seats = df["Seats"].map(lambda v: isinstance(v, (int, float)) and v < 0)
future_end = df["End Date"].map(lambda v: isinstance(v, dt.datetime) and v > dt.datetime.now())
exclude = dup_mask | neg_seats | future_end
include = ["N" if x else "Y" for x in exclude]


def parse_fee(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and re.fullmatch(r"\$?[\d,]+(\.\d+)?", v.strip()):
        return float(v.strip().replace("$", "").replace(",", ""))
    return None


def parse_start(v):
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, str):
        try:
            return dt.datetime.strptime(v.strip(), "%d/%m/%Y")   # agreed: text dates are day/month/year
        except ValueError:
            return None
    return None


fee_clean = [parse_fee(v) for v in df["Monthly Fee"]]
start_clean = [parse_start(v) for v in df["Start Date"]]

wb = CSWorkbook("Client Churn Review 2026", prepared_by="Jo Bert (Jobs) Olinares",
                requested_by="Leadership", period="Jan - Aug 2026")
wb.add_raw_data(
    df, meta, issues=issues, include=include,
    required=["Client ID", "Region", "Start Date", "Seats"],
    derived={
        "Region (clean)": {"formula": '=IF(TRIM({Region})="","UNASSIGNED",UPPER(TRIM({Region})))'},
        "Start Date (clean)": {"values": start_clean, "format": "yyyy-mm-dd",
                               "rule": "Start Date as a real date; text dates read as day/month/year (agreed)"},
        "Monthly Fee (clean)": {"values": fee_clean, "format": "#,##0",
                                "rule": "Monthly Fee as a number; '$' and ',' removed from text values"},
        "Status": {"formula": '=IF({End Date}="","Active","Churned")'},
        "End Month": {"formula": '=IF({End Date}="","",YEAR({End Date})&"-"&TEXT(MONTH({End Date}),"00"))'},
        "Tenure (months)": {"formula": '=IF(OR({End Date}="",{Start Date (clean)}=""),"",ROUND(({End Date}-{Start Date (clean)})/30.4375,1))',
                            "format": "0.0"},
    })

# ---------------------------------------------------------------- 4 independent pandas frame
c = df.copy()
c["region"] = c["Region"].map(lambda v: "UNASSIGNED" if v is None or str(v).strip() == "" else str(v).strip().upper())
c["fee"] = fee_clean
c["start"] = start_clean
c["status"] = c["End Date"].map(lambda v: "Active" if v is None else "Churned")
c["end_month"] = c["End Date"].map(lambda v: f"{v:%Y-%m}" if isinstance(v, dt.datetime) else "")
c["tenure"] = [round((e - s).days / 30.4375, 1) if isinstance(e, dt.datetime) and s else None
               for e, s in zip(c["End Date"], c["start"])]
c = c[[x == "Y" for x in include]]
ch = c[c["status"] == "Churned"]

R, S, INC = wb.col("Region (clean)"), wb.col("Status"), wb.INC
SEATS, FEE = wb.col("Seats"), wb.col("Monthly Fee (clean)")

# ---------------------------------------------------------------- 5a churn by region
regions = [r for r in ["APAC", "AMER", "EMEA", "UNASSIGNED"] if r in set(c["region"])]
rows, exp = [], []
for rg in regions:
    sub = c[c["region"] == rg]
    n, k = len(sub), int((sub["status"] == "Churned").sum())
    lo, hi = st.wilson_ci(k, n)
    seats = float(sub.loc[sub["status"] == "Churned", "Seats"].sum())
    rows.append([rg, f'=COUNTIFS({R},A{{r}},{INC})', f'=COUNTIFS({R},A{{r}},{S},"Churned",{INC})',
                 "=IFERROR(C{r}/B{r},0)", st.WILSON_LO.format(k="C{r}", n="B{r}"), st.WILSON_HI.format(k="C{r}", n="B{r}"),
                 f'=SUMIFS({SEATS},{R},A{{r}},{S},"Churned",{INC})'])
    exp.append([rg, n, k, k / n if n else 0, lo, hi, seats])
tot_n, tot_k = len(c), int((c["status"] == "Churned").sum())
sh = wb.add_tab("Churn by Region", explanation=(
    "How many clients left in each region, and how sure we can be about each rate. The churn rate is "
    "churned clients divided by all clients in scope. The " + const("95%") + " range shows where the true rate is likely "
    "to sit; wide ranges mean the region is too small to compare with confidence."))
t_reg = sh.add_table(
    "by_region", "Churn rate by region",
    ["Region", "Clients", "Churned", "Churn rate", "95% range (low)", "95% range (high)", "Seats lost"],
    rows, formats=[None, "#,##0", "#,##0", "0.0%", "0.0%", "0.0%", "#,##0"], expected=exp,
    total={"label": "Total", "cells": {"Clients": "=SUM({c:Clients}{first}:{c:Clients}{last})",
                                        "Churned": "=SUM({c:Churned}{first}:{c:Churned}{last})",
                                        "Churn rate": "=IFERROR(C{r}/B{r},0)",
                                        "Seats lost": "=SUM({c:Seats lost}{first}:{c:Seats lost}{last})"}},
    expected_total=[None, tot_n, tot_k, tot_k / tot_n, None, None, float(ch["Seats"].sum())],
    note="Source: Raw Data, Include = Y. Region standardised in 'Region (clean)'. 95% range = Wilson score interval.",
    n_col="Clients", min_n=30,
    reconcile={"Clients": f'=COUNTIF({wb.col("Include")},"Y")', "Churned": f'=COUNTIFS({S},"Churned",{INC})'})
sh.add_chart(t_reg, kind="col", cats="Region", values=["Churn rate"], title="Churn rate by region", y_format="0%")

# ---------------------------------------------------------------- 5b monthly trend
months = sorted(m for m in set(ch["end_month"]) if m)
EM = wb.col("End Month")
rows, exp = [], []
for mth in months:
    sub = ch[ch["end_month"] == mth]
    rows.append([mth, f'=COUNTIFS({EM},A{{r}},{INC})', f'=SUMIFS({SEATS},{EM},A{{r}},{INC})',
                 f'=SUMIFS({FEE},{EM},A{{r}},{INC})'])
    exp.append([mth, len(sub), float(sub["Seats"].sum()), float(sub["fee"].sum())])
sh2 = wb.add_tab("Churn by Month", explanation=(
    "When clients left during the year, with the seats and monthly revenue that went with them. "
    "Use it to spot months that stand out and to check whether losses are rising or easing."))
t_m = sh2.add_table(
    "by_month", "Churned clients by month of exit", ["Month", "Clients churned", "Seats lost", "Monthly revenue lost"],
    rows, formats=[None, "#,##0", "#,##0", "#,##0"], expected=exp,
    total={"label": "Total", "cells": {h: f"=SUM({{c:{h}}}{{first}}:{{c:{h}}}{{last}})" for h in ["Clients churned", "Seats lost", "Monthly revenue lost"]}},
    expected_total=[None, len(ch), float(ch["Seats"].sum()), float(ch["fee"].sum())],
    note="Month = month of End Date. Revenue uses 'Monthly Fee (clean)'.",
    reconcile={"Clients churned": f'=COUNTIFS({S},"Churned",{INC})'})
sh2.add_chart(t_m, kind="line", cats="Month", values=["Seats lost"], title="Seats lost per month", y_title="Seats")
trend = st.linear_trend(list(range(len(months))), [e[2] for e in exp])

# ---------------------------------------------------------------- 5c Pareto by industry
IND = wb.col("Industry")
by_ind = ch.groupby("Industry")["Seats"].sum().sort_values(ascending=False)
rows, exp, cum = [], [], 0
total_seats = float(by_ind.sum())
for ind, v in by_ind.items():
    cum += v
    rows.append([ind, f'=SUMIFS({SEATS},{IND},A{{r}},{S},"Churned",{INC})',
                 "=IFERROR(B{r}/SUM($B${first}:$B${last}),0)", "=IFERROR(SUM($B${first}:B{r})/SUM($B${first}:$B${last}),0)"])
    exp.append([ind, float(v), v / total_seats, cum / total_seats])
sh3 = wb.add_tab("Pareto - Industry", explanation=(
    "Which industries account for most of the seats we lost, largest first (a Pareto view). The line "
    "shows the running share; the industries before it crosses " + const("80%") + " are where retention effort pays off most."))
t_p = sh3.add_table("pareto_industry", "Seats lost by industry (Pareto)", ["Industry", "Seats lost", "Share", "Cumulative share"],
                    rows, formats=[None, "#,##0", "0.0%", "0.0%"], expected=exp, pct_sum_col="Share",
                    note="Sorted largest to smallest at build time. Churned clients, Include = Y.",
                    reconcile={"Seats lost": f'=SUMIFS({SEATS},{S},"Churned",{INC})'})
sh3.add_chart(t_p, kind="combo", cats="Industry", values=["Seats lost"], secondary=["Cumulative share"],
              title="Pareto: seats lost by industry", y_title="Seats")

# ---------------------------------------------------------------- 5d tenure bands
TEN = wb.col("Tenure (months)")
bands = [("Under 12 months", 0, 12), ("12-24 months", 12, 24), ("24-36 months", 24, 36), ("36+ months", 36, 10_000)]
rows, exp = [], []
for lab, lo, hi in bands:
    k = int(((ch["tenure"] >= lo) & (ch["tenure"] < hi)).sum())
    rows.append([lab, f'=COUNTIFS({TEN},">={lo}",{TEN},"<{hi}",{INC})', "=IFERROR(B{r}/SUM($B${first}:$B${last}),0)"])
    exp.append([lab, k, k / len(ch) if len(ch) else 0])
sh4 = wb.add_tab("Tenure at Exit", explanation=(
    "How long churned clients stayed before leaving. A cluster in the early bands points to onboarding or "
    "fit issues; a cluster later points to renewal or pricing conversations."))
t_t = sh4.add_table("tenure", "Churned clients by tenure at exit", ["Tenure band", "Clients", "Share"], rows,
                    formats=[None, "#,##0", "0.0%"], expected=exp, pct_sum_col="Share",
                    note="Tenure = (End Date - Start Date) / 30.44 days.",
                    reconcile={"Clients": f'=COUNTIFS({S},"Churned",{INC})'})
sh4.add_chart(t_t, kind="bar", cats="Tenure band", values=["Clients"], title="Churned clients by tenure band")

# ---------------------------------------------------------------- 6 summary
s = wb.summary
top_ind = by_ind.index[0]
s.add_kpis([
    {"label": "Clients in scope", "formula": f'=COUNTIF({wb.col("Include")},"Y")', "fmt": "#,##0", "expected": tot_n,
     "caption": "After agreed exclusions"},
    {"label": "Churned clients", "formula": f"={t_reg.ref('Total', 'Churned')}", "fmt": "#,##0", "expected": tot_k,
     "caption": "End Date recorded in 2026"},
    {"label": "Churn rate", "formula": f"={t_reg.ref('Total', 'Churn rate')}", "fmt": "0.0%", "expected": tot_k / tot_n,
     "caption": "Churned / clients in scope"},
    {"label": "Seats lost", "formula": f"={t_reg.ref('Total', 'Seats lost')}", "fmt": "#,##0", "expected": float(ch["Seats"].sum()),
     "caption": f"Revenue lost {num(t_m.ref('Total', 'Monthly revenue lost'), '#,##0')} per month"},
])
s.add_findings([f for f in [
    f"Overall churn is {num(t_reg.ref('Total', 'Churn rate'), '0.0%')}: {num(t_reg.ref('Total', 'Churned'))} of "
    f"{num(t_reg.ref('Total', 'Clients'))} clients left, taking {num(t_reg.ref('Total', 'Seats lost'))} seats.",
    f"APAC churn is {num(t_reg.ref('APAC', 'Churn rate'), '0.0%')} against {num(t_reg.ref('AMER', 'Churn rate'), '0.0%')} in AMER; "
    f"the " + const("95%") + " ranges overlap, so treat the gap as indicative, not proven." if "AMER" in regions else "",
    f"{top_ind} is the largest source of lost seats ({num(t_p.ref(top_ind, 'Share'), '0%')} of the total).",
    "Monthly seat losses show " + ("no clear upward or downward trend." if trend["p_value"] > 0.05 else
                                   ("a rising trend." if trend["slope"] > 0 else "an easing trend.")),
] if f])
s.add_recommendations([
    f"Prioritise retention reviews for {top_ind} and the next industries above the " + const("80%") + " line on the Pareto tab.",
    "Confirm the flagged future End Date with the account manager before the next refresh.",
])
s.add_chart(t_reg, kind="col", cats="Region", values=["Churn rate"], title="Churn rate by region", y_format="0%")
s.add_chart(t_p, kind="combo", cats="Industry", values=["Seats lost"], secondary=["Cumulative share"],
            title="Where seats were lost (Pareto)", y_title="Seats")

# ---------------------------------------------------------------- 7 governance
wb.log_decision("Exact duplicate rows", int(dup_mask.sum()), "Second copy set to Include = N", "Requester", ["duplicate"])
wb.log_decision("Negative Seats value", int(neg_seats.sum()), "Row excluded pending correction in source", "Requester", ["Seats"])
wb.log_decision("End Date in the future", int(future_end.sum()), "Row excluded; AM to confirm", "Requester", ["End Date"])
wb.log_decision("Region spelled inconsistently / blank", int(sum("Region" in i for i in issues)),
                "Standardised to upper case; blanks reported as UNASSIGNED", "Requester", ["Region"])
wb.log_decision("Monthly Fee stored as text", 2, "Converted to numbers in 'Monthly Fee (clean)'", "Requester", ["Monthly Fee"])
wb.log_decision("Start Date as text (15/03/2024)", 1, "Read as day/month/year in 'Start Date (clean)'", "Requester", ["Start Date"])
wb.log_decision("Duplicate Client ID CL-0100 (two different clients)", 2, "Kept both; flagged for CRM fix", "Requester", ["Client ID"])
wb.define("Churned client", "Client with an End Date in the data", "Status = Churned")
wb.define("Churn rate", "Churned clients / clients in scope", "COUNTIFS on Raw Data, Include = Y")
wb.define("95% range", "Wilson score interval for a proportion", "z = 1.96")
wb.attest("definitions_confirmed", True, "Example run - confirm with requester in real use")
wb.attest("period_confirmed", True, "Jan-Aug 2026")
wb.attest("outliers_reviewed", True, "Large-seat clients kept; they are real accounts")
wb.attest("sample_sizes_reviewed", True, "EMEA / UNASSIGNED flagged as small")
wb.attest("no_causal_overreach", True, "Findings describe patterns only")
wb.attest("requester_questions_answered", True, "Churn level, where, when, how long")

result = wb.save(out)
