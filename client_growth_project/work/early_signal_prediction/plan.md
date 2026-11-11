# Analysis plan: Early Signals of Account Growth

- Topic folder: `work/early_signal_prediction/`
- Requested by: Jo Bert (Jobs) Olinares, Head of Data & Analytics
- Prepared by: Jo Bert (Jobs) Olinares (with Claude)
- Status: APPROVED (2026-10-10)
- Date: 2026-10-10

## 1. Question and decision
- Business question: what can we observe early in a client relationship that predicts whether an account will reach 5 seats, continue expanding, and become a meaningfully larger Cloudstaff customer?
- Who reads it: Jobs and Cloudstaff leadership (growth, account management, sales); the research team using the Path to 5 shortlist.
- Decision it supports: which new accounts to prioritise for expansion effort in their first months (a scored watch list), and which early signals to build into onboarding and account plans.
- Questions the requester asked, word for word:
  1. "what can we observe early in a client relationship that predicts whether an account will reach five seats, continue expanding, and become a meaningfully larger Cloudstaff customer? just basin ont he data we have"
  2. "run different models and i need to see a test of their accuracy rpecision auc etc that clearly will rpedict and run the backtesting"
  3. "dont do anything on the html yet"

## 2. Data
| File (read in place, never modified) | Rows | Columns | Period covered | SHA-256 (first 16) |
|---|---|---|---|---|
| `data/Organic rate/SC Engagement List2026-09-29 11_25_26.xlsx` | 30,703 | 14 | stints to 29 Sep 2026 | 844dffdb3bdb5c0a |
| `data/Organic rate/mystaff 1005 v2.xlsx`, sheet MyStaff (2) | 2,875 | 374 | snapshot to 2 Oct 2026 | 0b0c83f850145de9 |
| `data/raw/monika_incremental_seats/2026 New Monthly Billed Report.xlsx` | role titles | | to Sep 2026 | 579a612ad281c9e4 |

- Built on the approved, QA-passed client growth prep (`work/client_growth_dashboard/prep.py`, commit 1bbef51): same scope, exclusions and definitions. 1,870 clients whose first staff started Jan 2020 to Sep 2026.
- Grain: one row per client (shortcode). Features are computed from stint dates up to day 90 after the client's first start; labels from what happened afterwards.
- No new raw files are needed.

## 3. Targets (what we predict) and definitions
| Target | Definition in plain words | Who is in it | Positives | Agreed? |
|---|---|---|---|---|
| A. Reaches 5 seats (primary) | 5 staff at the same time within 12 months of the first start | Clients aged 12+ months that never had 5 staff at the same time by day 90 (so the model cannot cheat; see change log) | 106 of 1,422 (about 7.5%) | |
| B. Becomes meaningfully larger | 10 staff at the same time within 24 months | Clients aged 24+ months that never had 10 staff at the same time by day 90 | 57 of 1,205 (about 4.7%) | |
| C. Keeps expanding after 5 | Staff at month 24 above staff at month 12 | Clients that reached 5 in their first year, aged 24+ months | 68 of 178 | |

- Target C is too small for machine learning. It gets a descriptive table and a single logistic regression with confidence intervals, no model contest.
- Target B is thin (10 to 20 positives per test year), so its backtest is reported pooled across years as well as per year, with wide ranges.

## 4. Early signals (features), all known by day 90
| Group | Features |
|---|---|
| Size and speed | staff at end of month 1 (starting seats), staff at day 30, 60 and 90, staff added days 31 to 90, staff who left by day 90, days from first to second start, number of starts in the first week |
| Role mix | initial function, number of distinct functions by day 90 (the RTG category share was removed: issue 8) |
| Account context | region (APAC, AMER incl. EMEA, OPTI), brand, start month (season) |
| Sensitivity only (see issue 1) | Custom Division, industry roll-up |

- Not used, because they are measured after day 90 or reflect the outcome: MyStaff Active, Total Staff, status, current or peak seats, any stint after day 90.
- Start year is not used as a signal: the backtest trains on past years and scores later ones, so a year number cannot carry over.

## 5. Models and backtest
- Models compared on the same data and folds:
  1. No-skill baseline (always predict the base rate)
  2. Simple rule baseline (for example: 3+ staff at day 90, or any adds in days 31 to 90)
  3. Logistic regression (L2, class weights)
  4. Logistic regression with L1 / elastic net (automatic feature selection)
  5. Random forest
  6. Gradient boosting (LightGBM or XGBoost)
  7. The best model above with probability calibration
- Backtest (out of time, expanding window by start year): train on clients that started in earlier years, test on the next year's cohort. Target A test years 2022, 2023, 2024, 2025; Target B test years 2022, 2023, 2024. Tuning uses only the training years (time-ordered cross-validation inside them). Nothing from a test year is seen before it is scored.
- Metrics per model and per test year, plus pooled across years with bootstrap 95% ranges:
  - ROC AUC
  - PR AUC (average precision, the key metric when only 5 to 8% are positive)
  - accuracy, balanced accuracy
  - precision, recall, F1, specificity at the chosen threshold
  - Brier score and a calibration table
  - lift and capture in the top 10% and top 20% of scored clients
- Threshold: chosen on training-year predictions only (best F1, and a second operating point "top 20% of new clients"), then applied unchanged to the test year.
- Comparing models: paired bootstrap of AUC differences against logistic regression; a model is called better only if the 95% range excludes zero.
- Drivers: logistic regression odds ratios with 95% ranges; permutation importance and SHAP for the tree models; single-signal rates with Wilson ranges and chi-square.
- Success bar, agreed up front: pooled out-of-time ROC AUC of at least 0.70, PR AUC of at least twice the base rate, and better than the simple rule in most test years. If no model clears it, the report says the early signals are weak rather than claiming a prediction.

## 6. Deliverables
- Workbook `outputs/excel/2026-10-10_Early_Signals_of_Account_Growth.xlsx`:
  - Summary
  - Targets and Cohorts
  - Early Signals (single-signal rates)
  - Model Comparison
  - Backtest by Year
  - Lift and Calibration
  - Drivers
  - Watch List
  - QA and Data Quality
  - Raw Data
- Watch List: the 249 clients now between 90 days and 12 months old, scored by the chosen model, with their top signals.
- Notebook `notebooks/early_signal_prediction.ipynb`; charts (ROC, PR, calibration, lift) in `outputs/charts/early_signal_prediction/`.
- Counts and rates are workbook formulas linked to Raw Data. Model metrics, ranges and SHAP values are computed in Python and stored as values, each table saying so. This is the same approach approved for the High-Growth Account Profile.
- The HTML dashboard is not changed.

## 7. Data issues and treatments
| # | Issue | Rows affected | Recommended treatment | Agreed treatment |
|---|---|---|---|---|
| 1 | Custom Division and industry are today's MyStaff values and track the outcome. Unassigned division: 71% churned vs 42%. Industry Unknown: 4% churned (mostly recent clients). | 651 Unassigned, industry Unknown clients | Leave out of the main models. Run one sensitivity model with them and report the difference. | As recommended (2026-10-10) |
| 2 | Role-title match coverage changes by year (2020: 73% unknown function; 2021 onwards: 3 to 18%) | 2020 cohort mainly | Keep "Unknown" as its own function value, and run a sensitivity model without function features. | As recommended (2026-10-10) |
| 3 | Only 5 to 8% positives | Targets A and B | Use class weights and report PR AUC, lift and bootstrap ranges. No synthetic oversampling. | As recommended (2026-10-10) |
| 4 | Clients too young to have an outcome yet | 328 clients under 12 months for A; more for B | Leave them out of training and testing. Score them on the Watch List only. | As recommended (2026-10-10) |
| 5 | Clients already at 5 (or 10) by day 90 | 124 (A), 45 (B) | Leave them out of that target: their outcome is already known at day 90. | As recommended (2026-10-10) |
| 6 | Base rate moves by start year (6% to 12% for A) | | Report per-year results and calibration per year. Do not use start year as a feature. | As recommended (2026-10-10) |
| 7 | Scope and exclusions | | Carry over the approved client growth dashboard rules: 2020+ cohort, internal and test accounts out, peak counted per day. | As recommended (2026-10-10) |
| 8 | Category (Engaged / RTG / Hub) is a person-level current status: it never differs between the stints of the 6,461 staff with 2+ stints, and only 2.3% of RTG stints are still open (35.6% of Engaged). It is not known at day 90. | all stints | Found by the reviewer (round 1). Removed from every model, table, finding and the watch list. Confirm the field's meaning with the StaffCentral owner. | Removed (analyst, 2026-10-10; requester to confirm meaning) |

## 8. Environment
- scikit-learn, LightGBM, XGBoost and SHAP are not installed; only statsmodels is. Install with `pip install scikit-learn lightgbm xgboost shap` and add them to `requirements.txt`. This only downloads the packages; no data leaves the machine.

## 9. Expected QA and review
- Target verdict: PASS. A warning is allowed only for the small-group gate on Target B and C tables.
- Control totals:
  - eligible clients and positives per target and cohort tie to the profile table
  - test-year rows sum to the pooled backtest
  - Watch List count ties to clients aged 90 days to 12 months
- Review: cs-data-reviewer plus blind data-scientist and data-analyst cross-checks. Focus areas: leakage (features dated after day 90), the backtest design (no test-year data in training or tuning), threshold choice, and metric calculations.

## 10. Open questions
1. Targets: model A, B and C as above, or change the thresholds (for example 10 within 24 months, or 20 within 36 months)?
2. "Early": features up to day 90 (recommended), or day 30 / day 180?
3. Division and industry: leave out of the main model with a sensitivity check (recommended), or include?
4. Install scikit-learn, LightGBM, XGBoost and SHAP?

## 11. Approvals
| Date | Item | Answer | By |
|---|---|---|---|
| 2026-10-10 | Targets | A + B + C as planned (A primary; B pooled and per-year backtest; C logistic regression only) | Jobs |
| 2026-10-10 | Early window | Day 90 | Jobs |
| 2026-10-10 | Custom Division and industry | Leave out of the main models; one sensitivity model with them | Jobs |
| 2026-10-10 | Environment | Install scikit-learn, LightGBM, XGBoost and SHAP | Jobs |
| 2026-10-10 | Data issues 2 to 7 | Recommended treatments, as listed in section 7 | Jobs (approved the plan) |

## 12. Change log
| Date | Change | Why |
|---|---|---|
| 2026-10-10 | Plan drafted | |
| 2026-10-10 | Targets A and B eligibility: "fewer than 5 (10) staff on day 90" tightened to "never had 5 (10) staff at the same time by day 90" | A client that touched 5 on day 60 and dipped to 4 by day 90 would otherwise count as a future success already visible at day 90 (leakage). Target A eligible clients 1,422 (was 1,434). |
| 2026-10-10 | Added a sensitivity model "without staff-count signals" | Staff at day 90 carries most of the signal; this shows what role mix, speed of the second start, region and start season predict on their own, which is the requester's question ("what can we observe early"). |
| 2026-10-10 | Target C keeps "staff on day 730 above staff on day 365" (day-based, same counting rule as the other targets) | Matches the day-based seat counts used everywhere else. |
| 2026-10-10 | Auto-selected model threshold chosen on its own training-year predictions | The calibrated model has no separate inner-fold predictions; the test year is still never used. |
| 2026-10-10 | RTG category feature removed from all models, Early Signals, Drivers, findings and the watch list | Reviewer round 1 Must fix: Category is a current person-level status, so it leaks information from after day 90 (issue 8) |
| 2026-10-10 | Base-rate baseline flags nobody ("always no"); top 10% / 20% capture shares tied scores evenly | Reviewer and data-analyst: correct no-skill accuracy, and a fair top-20% figure for the tied staff counts |
| 2026-10-10 | Added paired comparisons against staff at day 90 alone (A and B), calibration by test year, and a Target B test-year count table | Data-scientist and reviewer round 1 |
| 2026-10-10 | Sensitivity "without staff-count signals" now also drops second-start signals ("without staff and start counts") | Reviewer round 1: second-start timing is count-based |
| 2026-10-10 | Watch List: clients that have already reached 5 (by day 90 or since) are listed without a score | Reviewer round 1: 9 clients had reached 5 after day 90 |
| 2026-10-10 | Permutation importance replaced by SHAP (tree model) and coefficient contributions (logistic) on the Drivers tab | Same question (which features the models use) answered per client; avoids unstable permutation estimates on 1,422 clients |
| 2026-10-10 | "Without staff and start counts" sensitivity also drops the number of functions by day 90; a simple day-90 rule table (2+ staff or a second start) added as the account-management baseline; Target C range relabelled as the spread across CV repeats | Reviewer round 2 Should fix items |
