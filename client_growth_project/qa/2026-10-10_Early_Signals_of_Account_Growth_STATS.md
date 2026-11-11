# Statistics cross-check (data-scientist, blind): Early Signals of Account Growth
Analysed: 2026-10-10 | Source: SC Engagement List 2026-09-29 (scope from data/client_profile.csv: shortcode, start_date, region only) | Rows in scope: 12,469 of 30,703 (1 exact duplicate dropped). 1,870 clients; first start dates match the profile (0 mismatches).

## Independent numbers
| Metric | Value | n | Method |
|---|---|---|---|
| Target A eligible / positives | 1,422 / 106 (7.45%, Wilson 6.20 to 8.94) | 1,422 | aged 365+ days, never 5 on any day 0-90, 5+ on any day 0-365; stint counts on start and end dates |
| Target A by start year 2020/21/22/23/24/25 | 145/16, 268/18, 280/14, 256/15, 252/22, 221/21 | | |
| Excluded from A | 120 already at 5 by day 90; 328 under 12 months old | | |
| Target B eligible / positives | 1,205 / 57 (4.73%) | 1,205 | aged 730+, peak under 10 by day 90, 10+ by day 730 |
| Target C eligible / positives | 178 / 68 (38.20%) | 178 | by year 2020 33/13, 2021 51/19, 2022 38/8, 2023 32/17, 2024 24/11 |
| A backtest, LR pooled ROC / PR AUC | 0.8700 [0.822, 0.912] / 0.3968 [0.290, 0.526] | 1,009 (72 positive) | L2 LR, balanced weights, 15 day-90 signals (no function signals), expanding window, 2,000 bootstrap |
| A backtest, staff at day 90 alone | ROC 0.8842 [0.844, 0.920] / PR 0.3605 | 1,009 | raw count as score |
| A per-year LR ROC AUC 2022/23/24/25 | 0.8191 / 0.9072 / 0.9119 / 0.8438 | positives 14/15/22/21 | |
| A per-year staff-at-day-90 ROC AUC | 0.8755 / 0.8869 / 0.8970 / 0.8804 | | |
| A LR top 20% per year | 55 of 72 in 204 clients; precision 26.96%; lift 3.78 | 1,009 | |
| B backtest, LR pooled ROC AUC (2022-2024) | 0.8817 [0.813, 0.940]; PR AUC 0.3603 | 762 (28 positive) | staff at day 90 alone: ROC 0.9318 |
| A odds ratios (n=1,422) | staff at day 90 3.74 [2.65, 5.28] p<0.001; second start 2.83 [1.20, 6.69] p=0.018; any RTG 0.56 [0.33, 0.94] p=0.029; adds 31-90 1.33 [0.77, 2.27] p=0.30; leaver 0.80 [0.41, 1.56] p=0.51; AMER 0.74 [0.44, 1.24] p=0.25; OPTI 0.77 [0.37, 1.58] p=0.47 | | unpenalised Logit, 7 terms |
| Target C repeated CV ROC AUC | 0.5620 (fold range 0.38 to 0.73) | 178 | 5-fold x 20; full set 0.558; staff at day 90 alone 0.525 |
| Watch list | 249 (208 with staff today; 236 under 5 at day 90) | 249 | age 90-364 days |

## Statistical tests
| Comparison | Test | Statistic | Conclusion |
|---|---|---|---|
| RF minus LR, A ROC AUC | paired bootstrap | +0.005 [-0.019, +0.033] | no clear difference |
| Gradient boosting minus LR, A | paired bootstrap | -0.028 [-0.063, +0.001] | no clear difference |
| Staff at day 90 minus LR, A | paired bootstrap | +0.014 [-0.010, +0.042] | no clear difference |
| Staff at day 90 minus LR, B | paired bootstrap | +0.050 [+0.002, +0.114] | count alone ranks better than the LR |
| LR without staff counts minus full LR, A | paired bootstrap | ROC -0.083 [-0.106, -0.060]; PR 0.180 vs 0.397 | lower |
| Extra signals over staff at day 90, A (in sample) | likelihood ratio | chi2 16.16, df 6, p 0.013 | add a little in sample |
| Region vs A | chi-square 3x2 | p 0.22 | no clear difference |
| Second start within 90 days vs A | chi-square 2x2 | p < 0.001 | higher (19.9% vs 1.3%) |
| Target C LR overall fit | LR test | p 0.080 | no clear signal |

## What the data supports
- Target A predictable out of time well above the plan's bar (ROC AUC 0.87, PR AUC 0.40 vs base 7.14%).
- Staff at day 90 carries most of the signal (A 0.884, B 0.932 on its own; OR per extra staff 3.74).
- Adjusted: second start within 90 days higher odds (OR 2.83); any RTG start lower odds (OR 0.56).
- Signals other than staff counts carry some information on their own (out-of-time ROC 0.787 for A), clearly below the full model.

## What the data does not support
- That tree models beat logistic regression.
- That the multi-signal LR beats staff at day 90 alone out of time (A: no clear difference; B: count alone better). "Better than the simple rule in most test years" depends on the rule used; the binary 3+ rule scores 0.75 pooled and LR beats it every year.
- That continued expansion after 5 (Target C) is predictable (CV ROC 0.56, fold range includes 0.5).
- That region, adds in days 31-90 or a leaver change the odds of A once the other terms are in (all p > 0.25).
- Per-year B results (8 to 11 positives a year).

## Missing tests or checks
- Paired comparison of every model against staff at day 90 alone.
- Calibration check per test year (base rate moves 5.0% to 11.0%; class-weighted LR not calibrated).
- Collinearity: second start correlates 0.70 with staff at day 90 and 0.66 with any adds; ORs are conditional.
- Its LR leaves out function signals; the workbook's LR should be within a few hundredths, not identical.

## Definition questions
- Day 90 window 0-90 inclusive (0-89 gives the same A counts). B eligibility used the change-log rule (older reading 1,210 / 62). A under the older reading: 1,434. Watch list age 90-364 days = 249 (strict over 90 = 247; with staff today = 208). Target C LR: the 7 odds-ratio terms.

---
# Round 2 (plan changed: Category/RTG removed)
Rows in scope 12,469 of 30,703; 1,870 clients; first starts match the profile. Category not used.

| Metric | Value | n | Method |
|---|---|---|---|
| Target A eligible / positives | 1,422 / 106 (7.45%) | 1,422 | as plan |
| A by year 2020-2025 | 16/145, 18/268, 14/280, 15/256, 22/252, 21/221 | | Wilson ranges given |
| Target B / C | 1,205 / 57; 178 / 68 | | |
| A pooled out-of-time LR ROC / PR AUC | 0.8513 [0.798, 0.902] / 0.3773 | 1,009 (72) | L2 LR C=1 (not tuned), balanced, log1p counts; no Category |
| A staff at day 90 alone ROC / PR | 0.8842 [0.844, 0.920] / 0.3605 | 1,009 | raw count |
| A per-year LR vs staff day 90 | 2022 0.811 vs 0.876; 2023 0.846 vs 0.887; 2024 0.853 vs 0.897; 2025 0.883 vs 0.880 | | |
| A paired difference (LR minus staff day 90) | -0.033 [-0.078, +0.003] | | no clear difference |
| A threshold metrics (F1 on inner OOF) | precision 36.25%, recall 40.28%, accuracy 90.68%; 2023 threshold flagged 2 clients | | |
| A always-no accuracy | 92.86% | 1,009 | |
| A top 20% capture LR / staff day 90 | 2022 78.57/73.86; 2023 74.67/76.58; 2024 77.27/77.00; 2025 76.19/76.83 | | ties shared |
| A ROC, function + region + start quarter only | 0.5572 (with functions_d90: 0.630) | 1,009 | |
| B pooled ROC LR / staff day 90 | 0.8520 / 0.9318; difference -0.080 [-0.154, -0.016] | 762 (28) | LR lower |
| A odds ratios | staff day 90 3.37 [2.44, 4.66]; second start 3.02 [1.28, 7.13]; adds 1.43 [0.83, 2.45]; leaver 0.69 [0.36, 1.33]; 2+ functions 0.82 [0.47, 1.43]; AMER 0.75; OPTI 0.85 | 1,422 | Logit |
| C repeated CV ROC | 0.6046 (2.5th-97.5th 0.42 to 0.74) | 178 | staff day 90 alone 0.526 |
| Watch list | 249 / 227 never reached 5 | | 13 at 5 by day 90, 9 after |

## Supports
- Day-90 signals predict A out of time (ROC 0.85, PR 0.38, about 5x base rate); bar cleared.
- Staff at day 90 alone does at least as well as the LR on A, and better on B.
- Second start within 90 days keeps higher odds after adjusting for headcount (OR 3.02).
- Role mix, region and season alone carry almost no signal (ROC 0.56).

## Does not support
- "The model is more accurate than doing nothing" (accuracy below always-no, McNemar p=0.018).
- That the multi-signal model beats the staff-at-day-90 ranking.
- Region, leavers, adds 31-90 or 2+ functions as independent drivers.
- Target C prediction (weak and unstable).

## Missing checks
- Paired comparison against staff at day 90 as the headline benchmark for every model; report the 3+ rule (pooled ROC 0.750).
- Regularisation: tune C inside training years (C=0.1 gives 0.870).
- Threshold stability: report flag counts per year (2023 flagged 2).
- Brand not used (MyStaff load timed out).
