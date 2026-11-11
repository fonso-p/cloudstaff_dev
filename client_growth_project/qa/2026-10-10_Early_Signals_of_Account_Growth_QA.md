# QA report - Early Signals of Account Growth

**Verdict: PASS WITH WARNINGS**  (workbook shows: PASS WITH WARNINGS)

- Output: `/Users/jobso/Documents/DATA WS/outputs/excel/2026-10-10_Early_Signals_of_Account_Growth.xlsx`
- Source: `SC Engagement List2026-09-29 11_25_26.xlsx` (30,703 rows, SHA-256 844dffdb3bdb5c0a...)
- Verified: 10 Oct 2026 18:14 via LibreOffice/Excel recalculation

## G1 Source integrity - PASS
- [PASS] Source file unchanged since it was loaded (SHA-256) - SC Engagement List2026-09-29 11_25_26.xlsx 844dffdb3bdb5c0a...
- [PASS] Row and column counts match the source - 30,703 rows x 14 columns
- [PASS] Every Raw Data cell identical to the source file - 429,842 cells compared

## G2 Data quality - PASS
- [PASS] Required field 'CSID' completeness - 0 missing (0.0%). Thresholds: <=2% pass, <=10% warn, >10% fail unless a treatment was agreed
- [PASS] Required field 'Shortcode' completeness - 7 missing (0.0%). Thresholds: <=2% pass, <=10% warn, >10% fail unless a treatment was agreed
- [PASS] Required field 'Engagement Date' completeness - 0 missing (0.0%). Thresholds: <=2% pass, <=10% warn, >10% fail unless a treatment was agreed
- [PASS] Exact duplicate rows handled - 1 exact duplicates in source - decision logged
- [PASS] Rows with data issues have an agreed treatment - 43 rows flagged; 8 decisions logged
- [PASS] Excluded rows are documented - 18,234 rows excluded (Include = N)

## G3 Formula integrity - WARN
- [PASS] No formula errors anywhere in the workbook (incl. QA tab) - 0 errors
- [PASS] Analysis numbers are live formulas, not typed-in values - 304 formula cells in tables
- [PASS] Every formula traces back to data (no constants like =120/3)
- [WARN] Each analysis table is linked to Raw Data - Not linked: Target A: ROC AUC difference from staff at day 90 alone (paired bootstrap); Target A: ROC AUC difference from logistic regression (paired bootstrap); Target B: ROC AUC difference from staff at day 90 alone (paired bootstrap); Target A: test years in which each model ranks better than staff at day 90 alone (of 4); Target A: ROC AUC by test year; Target A: PR AUC by test year; Target A: Precision by test year; Target A: Recall by test year; Target A: Clients flagged at the training-year threshold by test year; Target B: ROC AUC by test year; Target B: PR AUC by test year; Target B: Precision by test year; Target B: Recall by test year; Target B: Clients flagged at the training-year threshold by test year; Target A: lift and capture of the top-scored clients (pooled out of time); Target A: calibration by test year (auto-selected + calibrated model); Target A: calibration, predicted chance vs actual rate (five equal bands, pooled out of time); Target A: reached 5 within 12 months: odds ratios (logistic regression); Target B: reached 10 within 24 months: odds ratios (logistic regression); Target C: kept expanding after reaching 5: odds ratios (logistic regression); Target A: what the models lean on (mean absolute contribution per client); Target A: sensitivity models (out of time, test years 2022-2025 pooled); Watch list: clients 90 days to 12 months old, highest chance first

## G4 Independent recomputation - PASS
- [PASS] 'Target A: reached 5 within 12 months' matches independent recalculation - 33 values compared
- [PASS] 'Target B: reached 10 within 24 months' matches independent recalculation - 28 values compared
- [PASS] 'Target C: kept expanding after reaching 5' matches independent recalculation - 28 values compared
- [PASS] 'Reached 5 within 12 months, by early signal (target A clients)' matches independent recalculation - 186 values compared
- [PASS] 'Target A (5 within 12 months): models compared out of time, test years 2022-2025 pooled' matches independent recalculation - 127 values compared
- [PASS] 'Target B (10 within 24 months): models compared out of time, test years 2022-2024 pooled' matches independent recalculation - 127 values compared
- [PASS] 'Target A: ROC AUC difference from staff at day 90 alone (paired bootstrap)' matches independent recalculation - 18 values compared
- [PASS] 'Target A: ROC AUC difference from logistic regression (paired bootstrap)' matches independent recalculation - 18 values compared
- [PASS] 'Target B: ROC AUC difference from staff at day 90 alone (paired bootstrap)' matches independent recalculation - 18 values compared
- [PASS] 'Target A test years: clients scored and positives' matches independent recalculation - 12 values compared
- [PASS] 'Target A: test years in which each model ranks better than staff at day 90 alone (of 4)' matches independent recalculation - 6 values compared
- [PASS] 'Target B test years: clients scored and positives' matches independent recalculation - 9 values compared
- [PASS] 'Target A: ROC AUC by test year' matches independent recalculation - 32 values compared
- [PASS] 'Target A: PR AUC by test year' matches independent recalculation - 32 values compared
- [PASS] 'Target A: Precision by test year' matches independent recalculation - 32 values compared
- [PASS] 'Target A: Recall by test year' matches independent recalculation - 32 values compared
- [PASS] 'Target A: Clients flagged at the training-year threshold by test year' matches independent recalculation - 32 values compared
- [PASS] 'Target B: ROC AUC by test year' matches independent recalculation - 24 values compared
- [PASS] 'Target B: PR AUC by test year' matches independent recalculation - 24 values compared
- [PASS] 'Target B: Precision by test year' matches independent recalculation - 24 values compared
- [PASS] 'Target B: Recall by test year' matches independent recalculation - 24 values compared
- [PASS] 'Target B: Clients flagged at the training-year threshold by test year' matches independent recalculation - 24 values compared
- [PASS] 'Target A: lift and capture of the top-scored clients (pooled out of time)' matches independent recalculation - 49 values compared
- [PASS] 'Target A: simple day-90 rule, test years 2022-2025' matches independent recalculation - 7 values compared
- [PASS] 'Target A: calibration by test year (auto-selected + calibrated model)' matches independent recalculation - 12 values compared
- [PASS] 'Target A: calibration, predicted chance vs actual rate (five equal bands, pooled out of time)' matches independent recalculation - 30 values compared
- [PASS] 'Target A: reached 5 within 12 months: odds ratios (logistic regression)' matches independent recalculation - 35 values compared
- [PASS] 'Target B: reached 10 within 24 months: odds ratios (logistic regression)' matches independent recalculation - 35 values compared
- [PASS] 'Target C: kept expanding after reaching 5: odds ratios (logistic regression)' matches independent recalculation - 35 values compared
- [PASS] 'Target A: what the models lean on (mean absolute contribution per client)' matches independent recalculation - 32 values compared
- [PASS] 'Target A: sensitivity models (out of time, test years 2022-2025 pooled)' matches independent recalculation - 40 values compared
- [PASS] 'Target C: can early signals predict continued expansion after 5?' matches independent recalculation - 5 values compared
- [PASS] 'Watch list: clients 90 days to 12 months old, highest chance first' matches independent recalculation - 1714 values compared
- [PASS] KPI 'Target A clients' matches independent recalculation - Excel=1422 expected=1422
- [PASS] KPI 'Reached 5 within 12 months' matches independent recalculation - Excel=0.07454289732770746 expected=0.07454289732770746
- [PASS] KPI 'Out-of-time ROC AUC' matches independent recalculation - Excel=0.890852899324084 expected=0.890852899324084
- [PASS] KPI 'Out-of-time PR AUC' matches independent recalculation - Excel=0.4335855364237481 expected=0.4335855364237481
- [PASS] KPI 'Found in top 20% of scores' matches independent recalculation - Excel=0.7777777777777778 expected=0.7777777777777778
- [PASS] KPI 'Target B ROC AUC' matches independent recalculation - Excel=0.926041261191125 expected=0.926041261191125

## G5 Reconciliation (live checks) - PASS
- [PASS] Raw Data row count equals source file - actual=30703 expected=30703
- [PASS] Included + excluded rows equal total rows - actual=30703 expected=30703
- [PASS] Include flags unchanged since verification (if FAIL: data edited - re-run QA) - actual=12469 expected=12469
- [PASS] Target A: reached 5 within 12 months: 'Eligible clients' ties back to raw data - actual=1422 expected='=COUNTIFS(raw_Client_Row,"Y",raw_Eligible_A,1,raw_Include,"Y")'
- [PASS] Target A: reached 5 within 12 months: 'Reached the target' ties back to raw data - actual=106 expected='=COUNTIFS(raw_Client_Row,"Y",raw_Eligible_A,1,raw_Reached_5_in_12m,1,raw_Include,"Y")'
- [PASS] Target B: reached 10 within 24 months: 'Eligible clients' ties back to raw data - actual=1205 expected='=COUNTIFS(raw_Client_Row,"Y",raw_Eligible_B,1,raw_Include,"Y")'
- [PASS] Target B: reached 10 within 24 months: 'Reached the target' ties back to raw data - actual=57 expected='=COUNTIFS(raw_Client_Row,"Y",raw_Eligible_B,1,raw_Reached_10_in_24m,1,raw_Include,"Y")'
- [PASS] Target C: kept expanding after reaching 5: 'Eligible clients' ties back to raw data - actual=178 expected='=COUNTIFS(raw_Client_Row,"Y",raw_Eligible_C,1,raw_Include,"Y")'
- [PASS] Target C: kept expanding after reaching 5: 'Reached the target' ties back to raw data - actual=68 expected='=COUNTIFS(raw_Client_Row,"Y",raw_Eligible_C,1,raw_Kept_Expanding,1,raw_Include,"Y")'
- [PASS] Watch list rows = Raw Data watch-list clients - actual=249 expected=249
- [PASS] Watch list rows tie to Raw Data (Watch List = 1) - actual=249 expected=249

## G6 Statistical soundness - WARN
- [PASS] Enough data for conclusions - 12,469 rows in scope
- [PASS] 'Target A: reached 5 within 12 months' group sizes >= 30
- [PASS] 'Target B: reached 10 within 24 months' group sizes >= 30
- [WARN] 'Target C: kept expanding after reaching 5' group sizes >= 30 - Small groups - call out in narrative, avoid ranking them: 2024 (n=24)
- [WARN] 'Reached 5 within 12 months, by early signal (target A clients)' group sizes >= 30 - Small groups - call out in narrative, avoid ranking them: Initial function: Other (under 30 clients) (n=26)
- [PASS] 'Target A (5 within 12 months): models compared out of time, test years 2022-2025 pooled' group sizes >= 30
- [WARN] 'Target B (10 within 24 months): models compared out of time, test years 2022-2024 pooled' group sizes >= 30 - Small groups - call out in narrative, avoid ranking them: Baseline: base rate (n=28), Single signal: staff at day 90 (n=28), Logistic regression (n=28), Elastic net logistic (n=28), Random forest (n=28), LightGBM (n=28), XGBoost (n=28), Auto-selected + calibrated (n=28)
- [WARN] 'Target A test years: clients scored and positives' group sizes >= 30 - Small groups - call out in narrative, avoid ranking them: 2022 (n=14), 2023 (n=15), 2024 (n=22), 2025 (n=21)
- [WARN] 'Target B test years: clients scored and positives' group sizes >= 30 - Small groups - call out in narrative, avoid ranking them: 2022 (n=8), 2023 (n=9), 2024 (n=11)

## G7 Presentation & narrative - PASS
- [PASS] Tab 'Targets and Cohorts' has a plain-English explanation - 81 words
- [PASS] Tab 'Early Signals' has a plain-English explanation - 70 words
- [PASS] Tab 'Model Comparison' has a plain-English explanation - 84 words
- [PASS] Tab 'Backtest by Year' has a plain-English explanation - 54 words
- [PASS] Tab 'Lift and Calibration' has a plain-English explanation - 58 words
- [PASS] Tab 'Drivers' has a plain-English explanation - 77 words
- [PASS] Tab 'Watch List' has a plain-English explanation - 88 words
- [PASS] Narrative figures are pulled live from cells (num tokens)
- [PASS] All narrative text evaluates
- [PASS] Every table has a source/definition note
- [PASS] Charts titled and linked to tables - 7 charts
- [PASS] Summary tab has KPIs and findings
- [PASS] Cloudstaff logo on every tab - cloudstaff-logo.png

## G8 Analyst review - PASS
- [PASS] Metric definitions agreed with the requester - Targets, early window and treatments approved by Jobs on 2026-10-10 (plan.md Approvals)
- [PASS] Time period and filters confirmed - Clients first staffed Jan 2020 to Sep 2026; data to 29 Sep 2026
- [PASS] Outliers reviewed and treatment agreed - Large clients kept; counts are log-scaled for the linear models and trees are scale-free
- [PASS] Small groups called out, not over-interpreted - Groups under 30 flagged; Target B and C small and stated in findings
- [PASS] Findings describe patterns, not causes, unless a test supports it - Findings state associations; the onboarding recommendation is framed as a pilot
- [PASS] Every question the requester asked is answered - Reach 5, keep expanding, become larger; several models; accuracy, precision, AUC; backtest
