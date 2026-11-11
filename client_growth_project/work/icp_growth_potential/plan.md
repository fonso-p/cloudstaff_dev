# Analysis plan: High-Growth-Potential Accounts (ICP from client history)

- Topic folder: `work/icp_growth_potential/`
- Requested by: ICP / Marketing lead (via Jo Bert (Jobs) Olinares)
- Prepared by: Jo Bert (Jobs) Olinares
- Status: APPROVED
- Date: 2026-10-08

## 1. Question and decision
- Business question: What can we observe early in a client relationship that predicts whether an account reaches 5 seats, how fast it gets there, whether it keeps expanding and whether it stays?
- Who reads it: Marketing / ICP owner and Cloudstaff leadership.
- Decision it supports: an evidence-based ICP (which regions, industries, starting shapes and first roles to target), and a shortlist of clients per group for primary research interviews.
- Questions the requester asked, word for word:
  1. "compare accounts that: reached 5+ seats quickly, reached 5+ seats more slowly, never reached 5 seats, churned"
  2. "what predicts whether an account gets there, how quickly they get there, and then what tends to happen after that"
  3. Fields: "region, with APAC and AMER analyzed separately; industry / vertical; company size, if we have it; starting seat count; initial function / role type; seat growth over time; time to 5 seats; time to a second function / department; expansion within the original function vs. expansion into new functions; tenure / retention / churn; current and peak seat count; gross margin or account economics, if appropriate"
  4. "what can we observe early in a client relationship that predicts whether an account will reach five seats, continue expanding, and become a meaningfully larger Cloudstaff customer?"

## 2. Data
| File (read in place, never modified) | Rows | Columns | Period covered | SHA-256 (first 16) |
|---|---|---|---|---|
| `Marketing/SC Engagement List2026-10-07 07_48_09.xlsx` (sheet "Sheet") | 30,837 | 14 | Engagement dates 1995 (bad) / 2009 to 2026-10-08 | 675935ef891ef2c7 |
| `data/raw/manager_movements/mystaff client list.xlsx` (sheet "MyStaff") | 2,855 | 374 | Snapshot 2026-09-27 | 21016ff51dfe4f15 |
| `data/raw/monika_incremental_seats/2026 New Monthly Billed Report.xlsx` (role tabs: All Billed New Staff 2.0, 2023/2024 Closed Seats, Gross 2025, Jan-Sep 2026) | about 21,100 rows with a role | 25-45 | New seats 2019-01 to 2026-09 | 579a612ad281c9e4 |

- Note: the engagement list sits in `Marketing/` (as provided). Creating a copy under `data/raw/` is blocked by a workspace permission rule, so it is read in place, as the organic growth analysis did with its file.
- Grain: engagement list = one row per staff stint on a client shortcode. MyStaff = one row per shortcode. Billed report = one row per new billed seat (role title).
- Join key: Shortcode (engagement list, MyStaff). Role joins to engagements on normalised staff name + kick-off date within 60 days of the Engagement Date (Engagement ID where present).
- Fields available: seat history (all), Region and Industry (MyStaff), role title per new seat (billed report, mainly 2021 onward).
- Fields NOT available in any file: company size (employees / revenue), gross margin. Cloudstaff Fee per seat exists only for 2019, 2020 and 2024 new seats (2,654 rows) and is revenue, not margin.

## 3. Metric definitions (proposed)
| Metric | Definition in plain words | Formula / rule | Agreed? |
|---|---|---|---|
| Seat | One active staff stint on the client (headcount), all categories on external clients (Engaged, RTG and the few Hub rows the 2026-09-30 internal-unit rule keeps) | Engagement Date <= day <= Disengagement Date (blank = still active) | |
| Client start | First staff Engagement Date on the shortcode | MIN(Engagement Date) | |
| Starting seats | Active seats on day 30 after client start | | |
| Seats at day 90 | Active seats on day 90 | | |
| Reached 5 | 5 or more concurrent active seats on any day | running headcount from start / end events | |
| Time to 5 | Months from client start to first day with 5 concurrent seats | | |
| Fast / Slow | Fast = reached 5 within 6 months (183 days) of start; Slow = reached 5 after month 6 | | Yes (requester, 2026-10-08) |
| Churned | No active seat on the extract date (2026-10-07) | | |
| Outcome group | 1 Fast 5+, 2 Slow 5+, 3 Not reached 5, still active, 4 Churned without reaching 5. Churn after reaching 5 is reported inside groups 1-2 as post-5 retention. Group 3 carries a tenure band (under 12, 12-23, 24+ months) because young clients may still get there | | Yes (requester, 2026-10-08) |
| Censoring rule | Rates are only computed on clients old enough to be judged: "reach 5 within 6 months" uses clients observed 6+ months; "reach 5 within 12 / 24 months" uses clients observed 12 / 24+ months. Cumulative probability of reaching 5 by month uses a Kaplan-Meier curve | | Analyst (follows from period choice) |
| Peak / current seats | Max concurrent seats ever; active seats on extract date | | |
| Function | Role title mapped to a function family by keyword rules (Admin and EA, Accounting and Finance, Customer Service, Sales and Lead Gen, Software and IT, Creative and Marketing, Property and Real Estate, Engineering and Drafting, HR and Recruitment, Operations and Projects, Executive Services (generic), Other) | mapping table in workbook | |
| Initial function | Most common function among seats started in the first 30 days | | |
| Time to second function | Months from start to the first seat in a different function family | | |
| Within vs new function expansion | Each seat added after day 30 is "same as initial" or "new function" | | |
| Early signals (predictors) | Region, industry roll-up, start year, starting seats, seats at day 90, adds in days 31-180, early leavers in first 180 days, initial function, number of functions by day 180, RTG share at start | | |

## 4. Period and filters
- Period: clients whose first staff started 2021-01-01 to the extract date 2026-10-07 (requester, 2026-10-08). Clients that started before 2021 are out of the cohort even if still active.
- Region: APAC and AMER analysed separately. Cloudstaff clients use MyStaff Region. OPTI clients are assigned a region from the latest MyStaff client list (2026-09-27 snapshot, the newest available): office country first, then timezone, then billing currency. Australia, New Zealand and Asia = APAC; Americas, UK, Europe and other = AMER (matches Cloudstaff's "AMER and EMEA General" grouping, where UK clients already sit in AMER). A Brand column (Cloudstaff / OPTI) is kept so results can be read with and without OPTI (requester, 2026-10-08).
- Filters: internal units excluded with the rule approved on 2026-09-30 (Hub share >= 50%, named internal codes, CSTREENGAGE pool).
- Out of scope: company size and gross margin (not in the data; a data request to HubSpot and Finance is given instead), reasons for growth or churn.

## 5. Data issues and treatments
| # | Issue | Rows affected | Recommended treatment | Agreed treatment |
|---|---|---|---|---|
| 1 | Internal units and Hub rows | Hub 2,648 rows; MyStaff Internal = Yes 114 shortcodes | Same rule as organic growth (2026-09-30) plus MyStaff Internal = Yes | As recommended (requester, rule approved 2026-09-30) |
| 2 | Disengaged Staff Pool (CSTREENGAGE) | about 5,400 | Exclude as a client | As recommended (requester, rule approved 2026-09-30) |
| 3 | Blank shortcode | 7 | Exclude | As recommended (requester, rule approved 2026-09-30) |
| 4 | Exact duplicate row | 1 | Exclude second copy | As recommended (requester, rule approved 2026-09-30) |
| 5 | Disengagement before Engagement Date | 35 | Exclude from headcount | As recommended (requester, rule approved 2026-09-30) |
| 6 | Engagement dates after the extract date | a few (max 2026-10-08) | Keep, flagged | As recommended (requester, rule approved 2026-09-30) |
| 7 | Engagement ID reused | 6 | Keep both, flag | As recommended (requester, rule approved 2026-09-30) |
| 8 | Role match is partial (name + date) | about 10-20% of 2021+ seats unmatched | Unmatched seats shown as "Unknown function"; initial function = Unknown when no first-month seat matched; match rate reported per year | As recommended (requester delegated to analyst, 2026-10-08) |
| 9 | Generic "Executive Services Specialist" titles (about 2,500 seats) hide the real function | | Own family "Executive Services (generic)", flagged | As recommended (requester delegated to analyst, 2026-10-08) |
| 10 | Industry blank, "-" or "0" | about 330 of 2,477 shortcodes | Group as "Unknown industry"; Hubspot industry used where roll-up is blank | As recommended (requester delegated to analyst, 2026-10-08) |
| 11 | Industry roll-up has 92 values | | Top industries with n >= 30 per region shown; rest grouped "Other" | As recommended (requester delegated to analyst, 2026-10-08) |
| 12 | MyStaff Region "-" / "VAR" | 9 shortcodes | Exclude | As recommended (requester delegated to analyst, 2026-10-08) |
| 14 | Shortcode not in the MyStaff client list | 3 rows, 3 shortcodes | Exclude (no region or industry) | Exclude (requester delegated to analyst, 2026-10-08) |
| 13 | OPTI clients with no country, timezone or currency | a few | Exclude, listed on Scope tab | Exclude (requester delegated to analyst, 2026-10-08) |

## 6. Analysis design
| Tab | Question it answers | Table(s) | Chart |
|---|---|---|---|
| Summary | Headline: who reaches 5, how fast, what follows | KPI tiles per region; findings; recommendations | outcome mix by region |
| Outcome Groups | Size and profile of the 4 groups, APAC vs AMER | count, share, median starting / peak / current seats, tenure | stacked bar |
| Early Signals | What predicts reaching 5 | reach-5 rate (Wilson 95%) by starting seats, seats at day 90, early adds, early leavers, start year; chi-square | bar with ranges |
| Industry | Which verticals reach 5 and stay | reach-5 and churn rate by industry, n >= 30 | bar |
| Initial Function | Does the first role predict growth | reach-5 rate by initial function | bar |
| Expansion Path | Within vs new function, time to second function | share of adds same vs new function by group; time-to-2nd-function bands | stacked bar |
| Speed to 5 | How long it takes | time-to-5 distribution, months bands | column |
| After 5 | What happens after 5 seats | retention at 12/24/36 months after reaching 5 vs clients of the same age that never reached 5; peak vs current seats; reach 10 / 20 | line (survival) |
| Seat Trajectory | Seat growth over time by group | median seats at months 1, 3, 6, 12, 24, 36 | line |
| Predictive Model | Combined early-signal model (notebook) | logistic regression per region on day-90 signals for clients under 5 at day 90; odds ratios, AUC | |
| Research Shortlist | Clients to interview | example active and churned clients per group and region (shortcode, name, industry, seats) | |
| Data Request | Missing fields | what to pull for company size and margin | |
| QA & Data Quality, Raw Data | | | |

- Tests: Wilson 95% ranges on all rates; chi-square for categorical signals; Mann-Whitney for seat counts between groups; logistic regression with a hold-out AUC (notebook, statsmodels/sklearn).
- Small-group threshold: n >= 30; smaller groups shown greyed, not ranked.
- Note on leakage: clients already at 5 by day 90 are fast by construction, so the predictive model uses only clients under 5 at day 90.

## 7. Expected QA and review
- Target verdict: PASS.
- Control totals: in-scope + excluded rows = 30,837; four outcome groups sum to in-scope clients per region.

## 8. Open questions
None open. Company size and gross margin need new data (see Data Request tab).

## 9. Approvals
| Date | Item | Answer | By |
|---|---|---|---|
| 2026-10-08 | Fast vs slow cut-off | Within 6 months | Requester |
| 2026-10-08 | Outcome groups | 4 exclusive groups (Fast 5+, Slow 5+, Not reached 5 active, Churned without 5) | Requester |
| 2026-10-08 | Cohort | Client starts 2021 to 2026 | Requester |
| 2026-10-08 | OPTI | Assign APAC / AMER from the latest MyStaff client list | Requester |
| 2026-10-08 | Issues 1-13 | Analyst recommendations as listed (issues 1-7 follow the treatments approved for organic growth on 2026-09-30) | Requester (delegated to analyst) |

## 10. Change log
| Date | Change | Why |
|---|---|---|
| 2026-10-08 | Period changed from 2019-2024 to 2021-2026; censoring rule and tenure band added | Requester choice; young clients cannot yet be judged on reaching 5 |
| 2026-10-08 | Early-signal windows set to the first 90 days (adds days 31-90, leavers and functions by day 90) instead of 180 days | A 180-day window overlaps the 6-month Fast definition, so it would partly measure the outcome itself (leakage) |
| 2026-10-08 | Kaplan-Meier curve replaced by "reached 5 within N months among clients at least N months old" | Keeps every rate a live formula; the note on Speed to 5 explains that later rows rest on older clients |
| 2026-10-08 | Seat definition corrected to include the few Hub rows on external clients | Matches the internal-unit rule approved 2026-09-30 (keep real clients whole); the earlier wording "Engaged and RTG" was wrong |
| 2026-10-08 | Medians, model odds ratios, AUC, chi-square, Mann-Whitney and two-proportion p-values written as values computed in Python | Grouped medians and these tests need array formulas or functions outside the Excel-2007 set; each table says so in its note |
| 2026-10-08 | Added Path to 10+ tab (reach 10 within 24 months), 36-month post-5 retention, Wilson ranges, AMER vs APAC test, start year and RTG-at-start signals, tenure band for group 3, n per trajectory checkpoint | Reviewer round 1 |
| 2026-10-08 | After 5: the planned "same-age clients that never reached 5" retention comparison is covered by "still with staff today by peak seats, clients aged 24+ months" and the peak 5+ vs under 5 test, instead of a 12/24/36-month matched comparison | Never-5 clients have no reach date to anchor 12/24/36 months on; comparing at the same client age is the fair equivalent |
| 2026-10-08 | Churned interview candidates limited to clients at least 12 months old | Reviewer round 1: avoid very short-lived 2026 accounts |
