# Reconcile: Early Signals of Account Growth

Workbook: outputs/excel/2026-10-10_Early_Signals_of_Account_Growth.xlsx (values read from a recalculated copy). Agent values: round 2 reports in qa/ (REVIEW, STATS, ANALYST).

| Metric | Workbook | cs-data-reviewer | data-scientist | data-analyst | Result |
|---|---|---|---|---|---|
| Target A eligible clients | 1,422 | 1,422 | 1,422 | 1,422 | Match |
| Target A positives | 106 | 106 | 106 | 106 | Match |
| Target A rate | 7.45% | 7.45% | 7.45% | 7.45% | Match |
| Target A 2020: eligible / positives | 145 / 16 | match (every cohort) | 145 / 16 | 145 / 16 | Match |
| Target A 2021: eligible / positives | 268 / 18 | match (every cohort) | 268 / 18 | 268 / 18 | Match |
| Target A 2022: eligible / positives | 280 / 14 | match (every cohort) | 280 / 14 | 280 / 14 | Match |
| Target A 2023: eligible / positives | 256 / 15 | match (every cohort) | 256 / 15 | 256 / 15 | Match |
| Target A 2024: eligible / positives | 252 / 22 | match (every cohort) | 252 / 22 | 252 / 22 | Match |
| Target A 2025: eligible / positives | 221 / 21 | match (every cohort) | 221 / 21 | 221 / 21 | Match |
| Target B eligible / positives | 1,205 / 57 | 1,205 / 57 | 1,205 / 57 | 1,205 / 57 | Match |
| Target C eligible / positives | 178 / 68 | 178 / 68 | 178 / 68 | 178 / 68 | Match |
| A rate, staff at day 90 = 0 | 0/172 | match | not checked | 0/172 | Match |
| A rate, staff at day 90 = 1 | 13/876 | match | not checked | 13/876 | Match |
| A rate, staff at day 90 = 2 | 34/243 | match | not checked | 34/243 | Match |
| A rate, staff at day 90 = 3 | 36/90 | match | not checked | 36/90 | Match |
| A rate, staff at day 90 = 4 | 23/41 | match | not checked | 23/41 | Match |
| A rate, Second start within 90 days: Yes | 94/473 | match | not checked | 94/473 | Match |
| A rate, Second start within 90 days: No | 12/949 | match | not checked | 12/949 | Match |
| A rate, Staff added in days 31-90: Yes | 61/253 | match | not checked | 62/254 | Resolved, definition: the workbook counts the first start as day 0, so 'days 31-90' is 0-based days 30 to 89 (the 31st to 90th day); the analyst took 0-based days 31 to 90. One client differs; both give p < 0.001. The workbook's convention is the same for every day-90 signal. |
| A rate, Staff added in days 31-90: No | 45/1,169 | match | not checked | 44/1,168 | Resolved, definition: the workbook counts the first start as day 0, so 'days 31-90' is 0-based days 30 to 89 (the 31st to 90th day); the analyst took 0-based days 31 to 90. One client differs; both give p < 0.001. The workbook's convention is the same for every day-90 signal. |
| A rate, any leaver by day 90: Yes | 15/306 | match (306/15, round 1) | not checked | 16/307 | Resolved, definition: the workbook counts end dates before day 90; the analyst counts end dates on or before day 90 (one client). Both not significant (p 0.07 to 0.12); the plan does not fix the boundary. |
| A rate, region AMER | 35/421 | not checked | not checked | 35/421 | Match |
| A rate, region APAC | 59/754 | not checked | not checked | 59/754 | Match |
| A rate, region OPTI | 12/247 | not checked | not checked | 12/247 | Match |
| A rate, start quarter Q1 | 28/407 | not checked | not checked | 28/407 | Match |
| A rate, start quarter Q2 | 24/384 | not checked | not checked | 24/384 | Match |
| A rate, start quarter Q3 | 35/366 | not checked | not checked | 35/366 | Match |
| A rate, start quarter Q4 | 19/265 | not checked | not checked | 19/265 | Match |
| A out-of-time ROC AUC, staff at day 90 alone | 0.8842 | 0.8842 | 0.8842 | 0.884 | Match |
| B out-of-time ROC AUC, staff at day 90 alone | 0.9318 | 0.9318 | 0.9318 | not checked | Match |
| A out-of-time ROC AUC, logistic regression | 0.8909 | 0.8909 | 0.8513 | not checked | Match with reviewer. Data-scientist: own model specification (untuned C=1, no function signals); it reports C=0.1 gives 0.870. Not like-for-like; same conclusion (well above the 0.70 bar, no clear gain over staff at day 90). |
| A out-of-time PR AUC, logistic regression | 0.4336 | 0.4336 | 0.3773 (own spec) | not checked | Match with reviewer; data-scientist own specification (see above) |
| A precision / recall / accuracy, logistic regression | 28.2% / 63.9% / 85.8% | 28.2% / 63.9% / 85.8% | 36.3% / 40.3% / 90.7% (own spec) | not checked | Match with reviewer; data-scientist own model and threshold, not like-for-like. Both below always-no accuracy, as the Summary says. |
| A accuracy of always saying no | 92.86% | 92.9% | 92.86% | not checked | Match |
| A top 20% capture, logistic regression | 77.8% | 77.8% | not pooled (per year 78.6 / 74.7 / 77.3 / 76.2%, own spec) | not checked | Match with reviewer |
| A top 20% capture, staff at day 90 alone | 76.10% | not checked | per year 73.9 / 76.6 / 77.0 / 76.8% | 76.25% | Resolved, definition: the analyst takes exactly 20% of each year (for example 51.2 clients), the workbook rounds to whole clients (51); both share ties evenly. Difference 0.15 points, from the rounding only. |
| A ROC AUC difference, logistic regression minus staff at day 90 | 0.007 [-0.008, 0.024] | +0.007 [-0.009, +0.024] | -0.033 [-0.078, +0.003] (own spec) | not checked | Match on the conclusion: no clear difference (all ranges include 0) |
| B out-of-time ROC AUC, logistic regression | 0.9260 | 0.9260 | 0.8520 (own spec) | not checked | Match with reviewer; data-scientist own specification |
| A odds ratio, staff at day 90 (per extra staff) | 3.35 | not checked | 3.37 [2.44, 4.66] | not checked | Match (within 1%; same direction and significance) |
| A odds ratio, second start within 90 days | 3.09 | not checked | 3.02 [1.28, 7.13] | not checked | Match (same direction and significance; 2% apart) |
| A odds ratios, adds 31-90 / leaver / region | ranges include 1 (no clear effect) | not checked | ranges include 1 | not checked | Match on the conclusion |
| A ROC AUC without staff, start or function counts (logistic) | 0.5567 | not checked | 0.5572 | not checked | Match |
| Target C cross-validated ROC AUC | 0.526 | not checked | 0.6046 (spread 0.42 to 0.74) | not checked | Match on the conclusion (weak, range reaches below 0.5). Different feature sets: the workbook uses the 7 readable signals, the data-scientist all day-90 signals. |
| Rule 2+ staff or second start: share flagged / capture | 34.6% / 90.3% | 34.6% (349/1,009) / 90.3% (65/72) | not checked | not checked | Match |
| Watch list clients / not yet at 5 | 249 / 227 | 249 / 227 | 249 / 227 | 249 / 227 | Match |

## Claims
- Data-scientist 'does not support': the model being more accurate than doing nothing; the multi-signal model beating staff at day 90; region, leavers, adds or 2+ functions as independent drivers; Target C prediction. The workbook makes none of these claims: the Summary sets accuracy against always-no, says the model is not clearly better than staff at day 90, names only second start as an adjusted driver, and calls Target C close to chance.
- Data-analyst findings (headcount at day 90 as the clearest signal; second start as a strong flag; no difference by region, quarter or leavers; reaching 5 is not continued expansion) agree with the Summary findings. Its recommendation (flag 2+ staff or a second start) is the workbook's first recommendation, with the rule's own backtest share and capture.

Cross-check: MATCHED
