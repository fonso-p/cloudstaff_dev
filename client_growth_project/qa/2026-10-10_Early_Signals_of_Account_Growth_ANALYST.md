# Business cross-check (data-analyst, blind): Early Signals of Account Growth
Analysed: 2026-10-10 | Source: SC Engagement List 2026-09-29 (first sheet) | Rows in scope: 12,469 of 30,703 (1,870 clients)

Scope: 1 exact duplicate removed; only the 1,870 in-scope shortcodes from data/client_profile.csv (used only for shortcode, start date and region). First-start dates match for all 1,870. Daily count: a stint counts on its start and end dates; day k = first start + k days; extract 2026-09-29.

## Independent numbers
| Metric | Value | n | Method |
|---|---|---|---|
| Target A eligible / positives / rate | 106 / 7.45% | 1,422 | aged 365+ days and peak below 5 on days 0-90; positive = 5 on the same day by day 365 |
| A by start year 2020 / 2021 / 2022 | 11.03% / 6.72% / 5.00% | 145 / 268 / 280 | positives 16 / 18 / 14 |
| A by start year 2023 / 2024 / 2025 | 5.86% / 8.73% / 9.50% | 256 / 252 / 221 | positives 15 / 22 / 21 |
| A by staff at day 90: 0 / 1 / 2 | 0.00% / 1.48% / 13.99% | 172 / 876 / 243 | positives 0 / 13 / 34 |
| A by staff at day 90: 3 / 4 | 40.00% / 56.10% | 90 / 41 | positives 36 / 23 |
| A, any add in days 31-90: yes / no | 24.41% / 3.77% | 254 / 1,168 | chi-square p < 0.001 |
| A, second start by day 90: yes / no | 19.87% / 1.26% | 473 / 949 | p < 0.001 |
| A, any leaver by day 90: yes / no | 5.21% / 8.07% | 307 / 1,115 | p = 0.117 |
| A, any RTG start by day 90: yes / no | 9.18% / 6.42% | 534 / 888 | p = 0.070 |
| A by region: AMER / APAC / OPTI | 8.31% / 7.82% / 4.86% | 421 / 754 / 247 | p = 0.222 |
| Target B eligible / positives | 1,205 / 57 (4.73%) | 1,205 | aged 730+ days, peak below 10 on days 0-90; positive = 10 by day 730 |
| Target C eligible / positives | 178 / 68 (38.20%) | 178 | reached 5 by day 365, aged 730+ days; day 730 staff above day 365 |
| Out-of-time top 20% capture (2022-2025, pooled), staff at day 90 | 76.25% (54.9 of 72) | 1,009 | top 20% per start year, ties split at random (expected value); lift 3.81x |
| Staff at day 90 as a ranker, AUC | 0.884 pooled (0.876 / 0.887 / 0.897 / 0.880) | 1,009 | 2022-2025, ties count half |
| Simple rule: 3+ at day 90 or any add in days 31-90 | precision 25.47%, recall 75.00% | 212 flagged of 1,009 | 54 true positives |
| Watch list | 249 (236 below 5 at day 90; 13 already at 5) | 249 | aged 90 to 364 days |

## Answer to the business question
- Best early sign: momentum in the first 90 days (more than one staff at day 90, a second start, or a new start in days 31-90).
- Of 1,048 clients with 0 or 1 staff at day 90, 13 reached 5 (1.24%); of 131 with 3 or 4, 59 did (45.04%).
- Region, an early leaver and RTG starts show no clear difference on their own (every p > 0.05).
- Staff at day 90 alone scores AUC 0.884 in later cohorts; any model should be judged against that.

## Findings
- Second start by day 90: 19.87% reach 5 (n=473) against 1.26% without (n=949).
- Rate rises with each seat at day 90: 1.48% (1), 13.99% (2), 40.00% (3), 56.10% (4).
- Ranking only by staff at day 90 puts 76.25% of later positives in the top 20% of each year; stable 2022-2025 (AUC 0.876 to 0.897).
- Reaching 5 is not continuing to expand: 38.20% of year-1 5-seat clients were larger at day 730 than day 365 (n=178); 62 were smaller.
- Base rate moves by start year (5.00% in 2022 to 11.03% in 2020).

## Questions a leader will ask next
- Of the 236 scored watch-list clients, 52 have 2 to 4 staff at day 90 and 46 meet the simple rule. Who owns them?
- What separates the 38% of 5-seat clients that kept growing from the 35% that shrank in year 2?
- Does any model beat staff at day 90 by enough to justify the extra complexity?

## Recommendations for account management
- At day 90, flag clients with 2+ staff or an add in days 31-90 for an expansion review; 3 or 4 staff = top priority.
- Make a second hire within 90 days an explicit onboarding goal and track it as a lead indicator.
- After a client reaches 5, plan for year-2 retention and growth.

## Definition questions
- Eligibility: used the change-log rule (never 5 or 10 at once by day 90). The older rule gives A 118 of 1,434 and B 62 of 1,210; plan section 3 still shows the older counts. Asks to confirm the workbook applies the tightened rule to B as well.
- Day 90 = first start + 90 days (first start + 89 gives the same Target A result).
- Ties in the top 20%: expected share with ties split at random (76.25%). Whole tied group at the cut-off: 65 of 72 (90.28%) using 27.45% of clients; strictly above the cut-off: 40 of 72 in 9.22% of clients.
- Second start = second-earliest engagement row (two starts on day 0 count as yes).

---
# Round 2 (plan changed: Category/RTG removed)
Analysed: 2026-10-10 | Rows in scope 12,469 of 30,703 (1,870 clients); Category not used; first start dates match the profile for all 1,870.

| Metric | Value | n | Method |
|---|---|---|---|
| Target A eligible / positives / rate | 106 of 1,422, 7.45% | 1,422 | aged 365+, daily peak under 5 over days 0-90 (120 already at 5); positive = peak 5+ within days 0-365 |
| Target A by start year | 2020 16/145; 2021 18/268; 2022 14/280; 2023 15/256; 2024 22/252; 2025 21/221 | | chi-square across years p=0.144 |
| Staff at day 90 | 0: 0/172; 1: 13/876; 2: 34/243; 3: 36/90; 4: 23/41 | 1,422 | p=3.98e-75 |
| Any staff added days 31-90 | Yes 62/254 (24.41%); No 44/1,168 (3.77%) | | p=3.25e-29 |
| Second start within 90 days | Yes 94/473 (19.87%); No 12/949 (1.26%) | | p=9.53e-36 |
| Any leaver by day 90 | Yes 16/307 (5.21%); No 90/1,115 (8.07%) | | end date at or before day 90; p=0.117 (strictly before: p=0.0725) |
| 2+ functions by day 90 | not computed | | functions not mapped |
| Region | AMER 35/421 (8.31%); APAC 59/754 (7.82%); OPTI 12/247 (4.86%) | | p=0.222 |
| Start quarter | Q1 28/407; Q2 24/384; Q3 35/366; Q4 19/265 | | p=0.335 |
| Target B eligible / positives | 57 of 1,205 (4.73%) | | |
| Target C eligible / positives | 68 of 178 (38.20%) | | includes 99 clients already at 5 by day 90 (35 positives) |
| Out-of-time top 20% capture, staff at day 90 (2022-2025 pooled) | 76.25% (54.90 of 72) | 1,009 | top 20% per year (fractional), boundary ties pro rata; by year 73.86 / 76.58 / 77.00 / 76.83% |
| Watch list aged 90-364 days | 249; 227 never reached 5 | | 13 at 5 by day 90, 9 after; of 227: APAC 134, AMER 61, OPTI 32 |
| Rule 3+ staff at day 90 | precision 45.04%, recall 55.66% | 131 flagged | |
| Rule 2+ staff at day 90 | precision 24.87%, recall 87.74% | 374 flagged | |

## Answer and findings
- Headcount at day 90 is the clearest early signal (0% at 0 staff to 56.10% at 4); ranking later cohorts on it puts about three quarters of next year's 5-seat clients in the top fifth, every test year 2022-2025.
- Region, start quarter and early leavers show no difference (all p > 0.1).
- A second start within 90 days is a strong yes/no flag (19.87% vs 1.26%).
- Adds in days 31-90 tell little once day-90 staff is known (3+ staff: 45.0% with and without adds; 2 staff: 16.5% vs 11.5%).
- Reaching 10 is rare (4.73%); 38.20% of year-1 5-seat clients were larger at month 24 than month 12.

## Questions a leader will ask next
- Which of the 227 watch-list clients have 2+ staff today? Call those first.
- Does any signal beyond headcount add anything once day-90 staff is known?
- What separates the 38% of 5-seat clients that keep growing?

## Definition questions
- Day 0 = first start (day 1 = start gives the same A counts).
- Leaver: end date at or before day 90 (strictly before gives p=0.0725).
- Second start: two starts on the same day count (473 yes); only days 1-90 gives 64/343 vs 42/1,079.
- Target C includes clients already at 5 by day 90 (plan does not exclude them).
