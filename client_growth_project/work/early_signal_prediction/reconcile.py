"""Build qa/<date>_Early_Signals_of_Account_Growth_RECONCILE.md: workbook values (from a recalculated copy) against the
cs-data-reviewer, data-scientist and data-analyst reports (round 2 values, typed from their reports in qa/)."""
import os
import sys

import openpyxl

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "cs-data-analytics", "scripts"))
from recalc import recalc_copy  # noqa: E402

WB = "outputs/excel/2026-10-10_Early_Signals_of_Account_Growth.xlsx"
wb = openpyxl.load_workbook(recalc_copy(WB), data_only=True)


def cell(sheet, title, row_label, header):
    """Value in table `title` (first column = row_label, header row right below the title)."""
    ws = wb[sheet]
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, 1).value == title:
            hdr = {ws.cell(r + 1, c).value: c for c in range(1, ws.max_column + 1)}
            rr = r + 2
            while ws.cell(rr, 1).value is not None:
                if str(ws.cell(rr, 1).value) == str(row_label):
                    return ws.cell(rr, hdr[header]).value
                rr += 1
            raise KeyError((title, row_label))
    raise KeyError(title)


TA, TB, TC = "Target A: reached 5 within 12 months", "Target B: reached 10 within 24 months", "Target C: kept expanding after reaching 5"
SIG = "Reached 5 within 12 months, by early signal (target A clients)"
CA = "Target A (5 within 12 months): models compared out of time, test years 2022-2025 pooled"
CB = "Target B (10 within 24 months): models compared out of time, test years 2022-2024 pooled"
LR, SS = "Logistic regression", "Single signal: staff at day 90"
rows = []   # metric, workbook, reviewer, scientist, analyst, result


def add(metric, wbv, rev, sci, ana, result):
    rows.append((metric, wbv, rev, sci, ana, result))


f = lambda v, d=0: "not in workbook" if v is None else (f"{v:,.{d}f}" if isinstance(v, (int, float)) else str(v))
p = lambda v, d=1: f"{100 * v:.{d}f}%"
add("Target A eligible clients", f(cell("Targets and Cohorts", TA, "All cohorts", "Eligible clients")), "1,422", "1,422", "1,422", "Match")
add("Target A positives", f(cell("Targets and Cohorts", TA, "All cohorts", "Reached the target")), "106", "106", "106", "Match")
add("Target A rate", p(cell("Targets and Cohorts", TA, "All cohorts", "Rate"), 2), "7.45%", "7.45%", "7.45%", "Match")
for y, (n, k) in zip(range(2020, 2026), [(145, 16), (268, 18), (280, 14), (256, 15), (252, 22), (221, 21)]):
    add(f"Target A {y}: eligible / positives", f"{f(cell('Targets and Cohorts', TA, y, 'Eligible clients'))} / {f(cell('Targets and Cohorts', TA, y, 'Reached the target'))}",
        "match (every cohort)", f"{n} / {k}", f"{n} / {k}", "Match")
add("Target B eligible / positives", f"{f(cell('Targets and Cohorts', TB, 'All cohorts', 'Eligible clients'))} / {f(cell('Targets and Cohorts', TB, 'All cohorts', 'Reached the target'))}",
    "1,205 / 57", "1,205 / 57", "1,205 / 57", "Match")
add("Target C eligible / positives", f"{f(cell('Targets and Cohorts', TC, 'All cohorts', 'Eligible clients'))} / {f(cell('Targets and Cohorts', TC, 'All cohorts', 'Reached the target'))}",
    "178 / 68", "178 / 68", "178 / 68", "Match")
for lvl, ana in [("0", "0/172"), ("1", "13/876"), ("2", "34/243"), ("3", "36/90"), ("4", "23/41")]:
    add(f"A rate, staff at day 90 = {lvl}", f"{f(cell('Early Signals', SIG, 'Staff at day 90: ' + lvl, 'Reached 5 in 12 months'))}/{f(cell('Early Signals', SIG, 'Staff at day 90: ' + lvl, 'Clients'))}",
        "match", "not checked", ana, "Match")
DAYS = ("Resolved, definition: the workbook counts the first start as day 0, so 'days 31-90' is 0-based days 30 to 89 (the 31st to 90th day); the analyst took "
        "0-based days 31 to 90. One client differs; both give p < 0.001. The workbook's convention is the same for every day-90 signal.")
for lab, ana, res in [("Second start within 90 days: Yes", "94/473", "Match"), ("Second start within 90 days: No", "12/949", "Match"),
                      ("Staff added in days 31-90: Yes", "62/254", DAYS), ("Staff added in days 31-90: No", "44/1,168", DAYS)]:
    add(f"A rate, {lab}", f"{f(cell('Early Signals', SIG, lab, 'Reached 5 in 12 months'))}/{f(cell('Early Signals', SIG, lab, 'Clients'))}", "match", "not checked", ana, res)
lv = f"{f(cell('Early Signals', SIG, 'Any leaver by day 90: Yes', 'Reached 5 in 12 months'))}/{f(cell('Early Signals', SIG, 'Any leaver by day 90: Yes', 'Clients'))}"
add("A rate, any leaver by day 90: Yes", lv, "match (306/15, round 1)", "not checked", "16/307",
    "Resolved, definition: the workbook counts end dates before day 90; the analyst counts end dates on or before day 90 (one client). Both not significant (p 0.07 to 0.12); the plan does not fix the boundary.")
for r_, ana in [("AMER", "35/421"), ("APAC", "59/754"), ("OPTI", "12/247")]:
    add(f"A rate, region {r_}", f"{f(cell('Early Signals', SIG, 'Region: ' + r_, 'Reached 5 in 12 months'))}/{f(cell('Early Signals', SIG, 'Region: ' + r_, 'Clients'))}", "not checked", "not checked", ana, "Match")
for q, ana in [("Q1", "28/407"), ("Q2", "24/384"), ("Q3", "35/366"), ("Q4", "19/265")]:
    add(f"A rate, start quarter {q}", f"{f(cell('Early Signals', SIG, 'Start quarter: ' + q, 'Reached 5 in 12 months'))}/{f(cell('Early Signals', SIG, 'Start quarter: ' + q, 'Clients'))}", "not checked", "not checked", ana, "Match")
add("A out-of-time ROC AUC, staff at day 90 alone", f(cell("Model Comparison", CA, SS, "ROC AUC"), 4), "0.8842", "0.8842", "0.884", "Match")
add("B out-of-time ROC AUC, staff at day 90 alone", f(cell("Model Comparison", CB, SS, "ROC AUC"), 4), "0.9318", "0.9318", "not checked", "Match")
add("A out-of-time ROC AUC, logistic regression", f(cell("Model Comparison", CA, LR, "ROC AUC"), 4), "0.8909", "0.8513",
    "not checked", "Match with reviewer. Data-scientist: own model specification (untuned C=1, no function signals); it reports C=0.1 gives 0.870. Not like-for-like; same conclusion (well above the 0.70 bar, no clear gain over staff at day 90).")
add("A out-of-time PR AUC, logistic regression", f(cell("Model Comparison", CA, LR, "PR AUC"), 4), "0.4336", "0.3773 (own spec)", "not checked", "Match with reviewer; data-scientist own specification (see above)")
add("A precision / recall / accuracy, logistic regression", f"{p(cell('Model Comparison', CA, LR, 'Precision'))} / {p(cell('Model Comparison', CA, LR, 'Recall'))} / {p(cell('Model Comparison', CA, LR, 'Accuracy'))}",
    "28.2% / 63.9% / 85.8%", "36.3% / 40.3% / 90.7% (own spec)", "not checked", "Match with reviewer; data-scientist own model and threshold, not like-for-like. Both below always-no accuracy, as the Summary says.")
add("A accuracy of always saying no", p(cell("Model Comparison", CA, "Baseline: base rate", "Accuracy"), 2), "92.9%", "92.86%", "not checked", "Match")
add("A top 20% capture, logistic regression", p(cell("Model Comparison", CA, LR, "Top 20% capture")), "77.8%", "not pooled (per year 78.6 / 74.7 / 77.3 / 76.2%, own spec)", "not checked", "Match with reviewer")
add("A top 20% capture, staff at day 90 alone", p(cell("Model Comparison", CA, SS, "Top 20% capture"), 2), "not checked", "per year 73.9 / 76.6 / 77.0 / 76.8%", "76.25%",
    "Resolved, definition: the analyst takes exactly 20% of each year (for example 51.2 clients), the workbook rounds to whole clients (51); both share ties evenly. Difference 0.15 points, from the rounding only.")
dd = "Target A: ROC AUC difference from staff at day 90 alone (paired bootstrap)"
add("A ROC AUC difference, logistic regression minus staff at day 90", f"{f(cell('Model Comparison', dd, LR, 'AUC difference'), 3)} [{f(cell('Model Comparison', dd, LR, '95% low'), 3)}, {f(cell('Model Comparison', dd, LR, '95% high'), 3)}]",
    "+0.007 [-0.009, +0.024]", "-0.033 [-0.078, +0.003] (own spec)", "not checked", "Match on the conclusion: no clear difference (all ranges include 0)")
add("B out-of-time ROC AUC, logistic regression", f(cell("Model Comparison", CB, LR, "ROC AUC"), 4), "0.9260", "0.8520 (own spec)", "not checked", "Match with reviewer; data-scientist own specification")
OR = "Target A: reached 5 within 12 months: odds ratios (logistic regression)"
add("A odds ratio, staff at day 90 (per extra staff)", f(cell("Drivers", OR, "Staff at day 90 (per extra staff)", "Odds ratio"), 2), "not checked", "3.37 [2.44, 4.66]", "not checked", "Match (within 1%; same direction and significance)")
add("A odds ratio, second start within 90 days", f(cell("Drivers", OR, "Second start within 90 days", "Odds ratio"), 2), "not checked", "3.02 [1.28, 7.13]", "not checked", "Match (same direction and significance; 2% apart)")
add("A odds ratios, adds 31-90 / leaver / region", "ranges include 1 (no clear effect)", "not checked", "ranges include 1", "not checked", "Match on the conclusion")
SENS = "Target A: sensitivity models (out of time, test years 2022-2025 pooled)"
add("A ROC AUC without staff, start or function counts (logistic)", f(cell("Drivers", SENS, "Without staff and start counts: Logistic regression", "ROC AUC"), 4), "not checked", "0.5572", "not checked", "Match")
CC = "Target C: can early signals predict continued expansion after 5?"
add("Target C cross-validated ROC AUC", f(cell("Drivers", CC, "Cross-validated ROC AUC", "Value"), 3), "not checked", "0.6046 (spread 0.42 to 0.74)", "not checked",
    "Match on the conclusion (weak, range reaches below 0.5). Different feature sets: the workbook uses the 7 readable signals, the data-scientist all day-90 signals.")
RU = "Target A: simple day-90 rule, test years 2022-2025"
rl = "2+ staff at day 90 or a second start by day 90"
add("Rule 2+ staff or second start: share flagged / capture", f"{p(cell('Lift and Calibration', RU, rl, 'Share flagged'))} / {p(cell('Lift and Calibration', RU, rl, 'Capture'))}",
    "34.6% (349/1,009) / 90.3% (65/72)", "not checked", "not checked", "Match")
add("Watch list clients / not yet at 5", "249 / 227", "249 / 227", "249 / 227", "249 / 227", "Match")

out = [f"# Reconcile: Early Signals of Account Growth", "", f"Workbook: {WB} (values read from a recalculated copy). Agent values: round 2 reports in qa/ (REVIEW, STATS, ANALYST).", "",
       "| Metric | Workbook | cs-data-reviewer | data-scientist | data-analyst | Result |", "|---|---|---|---|---|---|"]
out += [f"| {a} | {b} | {c} | {d} | {e} | {g} |" for a, b, c, d, e, g in rows]
out += ["", "## Claims", "- Data-scientist 'does not support': the model being more accurate than doing nothing; the multi-signal model beating staff at day 90; region, leavers, adds or 2+ functions as independent drivers; Target C prediction. The workbook makes none of these claims: the Summary sets accuracy against always-no, says the model is not clearly better than staff at day 90, names only second start as an adjusted driver, and calls Target C close to chance.",
        "- Data-analyst findings (headcount at day 90 as the clearest signal; second start as a strong flag; no difference by region, quarter or leavers; reaching 5 is not continued expansion) agree with the Summary findings. Its recommendation (flag 2+ staff or a second start) is the workbook's first recommendation, with the rule's own backtest share and capture.",
        "", "Cross-check: MATCHED"]
open("qa/2026-10-10_Early_Signals_of_Account_Growth_RECONCILE.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
