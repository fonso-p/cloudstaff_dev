# Review: 2026-10-10_Early_Signals_of_Account_Growth.xlsx
Verdict: CHANGES NEEDED
Reviewed: 2026-10-10, round 1 (cs-data-reviewer)

Inputs complete; plan APPROVED with agreed treatments. QA PASS WITH WARNINGS (G3 Python-value tables not linked, as the plan allows; G6 small groups).

## Verified (reviewer's own code from the raw file; scope list from data/client_profile.csv)
- In-scope rows 12,469 (1 exact duplicate); 1,870 clients; start dates match.
- Target A 1,422 / 106 / 7.45%, every cohort year; Target B 1,205 / 57; Target C 178 / 68: match.
- Days to 5 matches for every client; no eligible A client had 5 staff by day 90 (eligibility does not leak the outcome).
- Raw Data formula columns: 0 mismatches over 1,870 client rows. Watch list 249 (236 scored, 13 at 5).
- Early Signals counts match. Prediction files cover exactly the eligible test-year clients (A 1,009 / 72; B 762 / 28).
- Logistic regression pooled A: ROC 0.8992, PR 0.4379, precision 24.9%, recall 76.4%, accuracy 81.9%, top 20% capture 79.2%; by year 0.888 / 0.895 / 0.916 / 0.884; bootstrap 0.870 to 0.927 (reviewer 0.869 to 0.925): match. Single signal A 0.8842, B 0.9318: match.
- Backtest design: outer fold trains on earlier years only; tuning, threshold and calibration inside training years; no test-year rows seen before scoring.
- Success bar met for A.

## Must fix
- RTG feature leaks post-day-90 information: Category is a person-level field showing current status (never varies across stints of 6,461 multi-stint staff; 2.3% of RTG rows open vs 35.6% of Engaged). It is LightGBM's second-largest SHAP feature, drives the 0.57 odds ratio in the findings and is a top signal on 164 watch-list rows. Remove it from the main models, drivers, Early Signals, watch list and finding 3; confirm the field's meaning with the data owner; re-run.
- Calibration per year (agreed treatment for issue 6) not shown: add calibration by test year.

## Should fix
- Baseline row: threshold = base rate flags everyone (accuracy 7.1%); show always-no accuracy (92.9%) and expected 20% capture; note tied scores for the single signal.
- Summary lacks accuracy and precision and test-year n; add a precision / recall / accuracy line with 1,009 clients / 72 positives against always-no accuracy, and state the success bar result.
- Backtest by Year: no clients / positives table for Target B.
- Labels for the latest training cohort are only known during or after the test year: say so (slightly optimistic) or add a gap variant.
- Time-fold calibration: the 2022 calibrated model is fitted on 2020 only with 2021 for calibration; disclose or refit.
- "Without any staff counts" still keeps second-start timing (count-based) and RTG: reword and re-run.
- Watch List: 9 clients already reached 5 after day 90 are scored as prospects; give them a separate status.
- Permutation importance planned but not delivered: add or log the change.

## Nice to have
- Region and OPTI come from today's MyStaff tags: note the timing caveat.
- "Stays above 0.80" differs from the plan's 0.70 bar; "no better than chance" hard-coded, make it conditional.
- plan.md counts (already updated after the analyst cross-check).
- QA tab font cells in Calibri; lift chart PNG missing; QA G4 compared 0 watch-list values.

## Could not verify
- Elastic net, random forest and XGBoost tuning per fold and the SHAP values (checked metrics from saved predictions only).
- The data owner's definition of the RTG category (inferred from the data pattern).

---
# Round 2 (full review: Category feature removed and models re-run)
Verdict: APPROVED WITH NOTES
Reviewed: 2026-10-10, round 2 (cs-data-reviewer)

## Verified (reviewer's own pandas code)
- Rows 12,469 (1 duplicate), 1,870 clients; Target A 1,422 / 106 / 7.45% and every cohort; B 1,205 / 57; C 178 / 68: match.
- Early Signals counts and Raw Data formula columns: 0 mismatches; no Category column.
- Predictions cover exactly the eligible test-year clients (A 1,009 / 72; B 762 / 28).
- Target A logistic regression: ROC 0.8909, PR 0.4336, precision 28.2%, recall 63.9%, accuracy 85.8%, top 20% capture 77.8%, bootstrap 0.856-0.923 vs 0.857-0.922: match. Per year LR vs staff at day 90: 0.884/0.876, 0.889/0.887, 0.900/0.897, 0.891/0.880 (ahead 4 of 4): match.
- Target B LR 0.9260, single signal 0.9318; calibration by year: match.
- Reviewer's own simple out-of-time logistic model without Category: A 0.873, B 0.915 (headline level holds).
- Round 1 items 1-11 confirmed fixed (RTG removed; calibration by year; baseline always-no; Summary precision / recall / accuracy; Target B year table; cautions; sensitivity; watch-list statuses (13 + 9 unscored, 227 scored); permutation importance change logged; paired comparisons vs staff at day 90; nice-to-haves).

## Must fix
- None.

## Should fix
- "Without staff, start or second-start counts" still keeps functions_d90 (2+ functions implies 2+ starts); drop it or reword.
- The success-bar sentence omits the plan's third condition (better than the simple rule in most test years; met, 4 of 4).
- Target C "95% range" is the spread across CV repeats, not a confidence interval; label it so and word "close to chance".
- Recommendation compares the "2+ staff or second start" rule with the top-20% capture; state the rule's own flag share (349 / 1,009) and capture (65 / 72).
- Model Comparison text says "Seven ways"; the table shows 8 rows.

## Nice to have
- Calibration wording: one fit per training year after the first, so "calibrated on the last training year" is exact only for 2022.
- "raises the odds" could be "is linked to higher odds".
- Drivers importance table: readable feature names.
- Watch List note: a "lowering" signal can mean below average (for example no adds).
- Calibration by year note: 2024 under-predicted.
- Remove unused `no_size`.
- QA & Data Quality tab: 323 cells in Calibri (library styling).

## Could not verify
- Per-fold tuning of elastic net, random forest, LightGBM and XGBoost, and SHAP values (metrics checked from saved predictions plus own simpler backtest).
- The data owner's meaning of Category (plan issue 8 open with the StaffCentral owner).

---
# Round 3 (focused re-review)
Verdict: APPROVED WITH NOTES
Reviewed: 2026-10-10, round 3 (cs-data-reviewer)

- Scope of change check: esp_data.py and esp_models.py unchanged since round 2 (timestamps); make_notebook.py and the build script read in full; only the 7 listed items changed; every headline number identical to round 2. Notebook 18 of 18 code cells, no errors.
- Verified: targets A 1,422 / 106, B 1,205 / 57, C 178 / 68 and every cohort; day-90 rule 1,009 / 349 flagged (34.6%) / 72 / 65 caught (90.3%) / precision 18.6%; LR ROC 0.8909, PR 0.4336, precision 28.2%, recall 63.9%, accuracy 85.8%; single signal 0.8842; B LR 0.926 / single 0.9318; flagged counts per year for every model; years ahead of staff at day 90 (LR 4, elastic net 4, RF 3, LightGBM 0, XGBoost 0, auto 2); no-counts sensitivity LR 0.557 / LightGBM 0.587 (reviewer 0.575); Target C labels and wording; watch list 249 (227 scored, 13 + 9 already at 5), 0 differences from watch_list.csv. No causal words.

## Must fix
- None.

## Should fix
- Targets and Cohorts notes show a literal "[[95%]] range" (cx() applied to note text).
- "Without staff and start counts" keeps function_known_d90 (share of roles matched); the note and finding list the features wrongly. Drop it or name it in the texts (AUC effect negligible: 0.575 vs 0.570).

## Nice to have
- Rule table criteria need an upper year bound ("<=2025") for future periods.
- The rule was chosen after seeing the backtest years: say its capture is in-sample.
- Sensitivity ranges use 1,000 resamples (Model Comparison 2,000): state it.
- Grammar: "LightGBM, XGBoost are" -> "LightGBM and XGBoost are".
- Success-bar sentence: "better than the simple rule (staff at day 90 alone)".
- Notebook step 10 prints "95% range" for Target C.
- Calibration-by-year note could name the under-predicted year; QA tab Calibri cells (library styling).

## Could not verify
- Cell-by-cell comparison with round 2 (no copy kept); per-fold tuning and SHAP values; the data owner's meaning of Category.

## Fixes after round 3 (analyst; text and labels only, no numbers changed; verified by QA and reconcile.py, no fourth round under the three-round limit)
- Targets and Cohorts notes: plain text (no literal [[95%]] markers); workbook scan finds 0 markers.
- "Without staff and start counts": note, finding and notebook text now name every remaining feature (initial function, share of roles matched, region, start season); the model itself is unchanged.
- Rule table: upper year bound (<=2025) added; note says its capture is in-sample.
- Sensitivity note states 1,000 resamples; grammar "LightGBM and XGBoost are"; success bar says "the simple rule, staff at day 90 alone".
- Notebook step 10 label "spread across 20 CV repeats"; calibration-by-year note names the year with the largest gap.
- Verification: notebook re-run end to end (no errors), QA PASS WITH WARNINGS (same warnings), reconcile.py re-run: Cross-check MATCHED, every headline value identical.
