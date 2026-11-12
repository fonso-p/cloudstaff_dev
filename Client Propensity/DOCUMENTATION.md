# Client Propensity: business rules, code guide and dashboard handoff

**Model version:** `propensity-v1 (dashboard 18-group taxonomy)` · **Code:** this folder · **Last updated:** 2026-11-12

This project estimates, from five years of real client history:

* **New clients and prospects:** how likely a client with a given profile is to reach 5 seats within a year and 10 seats within two years, and to add a second department in its first year.
* **Existing clients:** how likely each active client is to have more seats in 12 months, and to add a department it has never had. Each client also gets the department it is most likely to add next.

The scores measure **fit**: whether clients like this have tended to grow or expand. They complement the Account Priority Dashboard's `priority_score`, which measures **timing**: whether now is a good moment to engage.

Contents:
1. [Business rules](#part-1-business-rules)
2. [Code guide](#part-2-code-guide)
3. [Handoff: adding the scores to the Account Priority Dashboard](#part-3-handoff-adding-the-scores-to-the-account-priority-dashboard)

Counts below come from the run of 2026-11-12.

---

# Part 1: Business rules

All settings live in `config.py`. A rule change means changing `config.py` (or `mi_pipeline/mappings.py`) and this section.

## 1.1 Sources

| Key | File | Grain | Used for |
|---|---|---|---|
| `engagement` | SC Engagement List (extract 2026-10-07) | one row per placement (staffer × client) | start and end dates of every hire: the base of all headcount history |
| `seat_churn` | Seats Churn (OPERATIONAL) (2026-10-05) | one row per placement | exit reasons (voluntary / involuntary, customer / Cloudstaff initiated) |
| `mystaff` | CONFIDENTIAL Mystaff, sheet MyStaff (2026-10-05) | one row per client | industry, office address, Active flag, Internal flag, CRM Company ID (= HubSpot company Record ID) |
| `staffcentral` | StaffCentral (2026-09-14) | one row per staffer (current snapshot) | department, JP Category, designation |

The raw files are confidential and stay outside the repo (`config.DATA_DIR`, or the `MIA_DATA_DIR` environment variable). Only the columns listed in `config.RAW_FILES` are read, so personal fields such as addresses and birthdays are never loaded.

## 1.2 Cleaning

* **IDs** (Shortcode, CSID, Engagement ID) are trimmed text. `12345.0` becomes `12345`, and blanks become missing.
* **Dates** are plain calendar dates. A blank disengagement date means the staffer is still active and is filled with the as-of date.
* **Active staffer:** disengagement date blank, today or later, or the extract's fill date (`ACTIVE_FILL_DATE`).
* **Future starts** (engagement date after today) are left out of every count.
* **StaffCentral duplicates:** where a CSID appears more than once, the row currently engaged is kept, then the one with the latest engagement.
* **MyStaff** has about a million blank rows. They are dropped.

## 1.3 Departments (role groups)

| Rule | Detail |
|---|---|
| Department | StaffCentral `Department (All)`, joined to each engagement on **CSID** |
| Executive Services split | Executive Services is about 54% of staff, so it is split by `JP Category`, for example `Exec Services - BPO Voice` |
| Blank JP Category | Inferred from **Designation** when at least 5 staff with the same normalised designation have a known category and at least 60% of them share it. Generic titles such as "Executive Services Specialist I" are never used. Held-out accuracy is about 90%. This fills 2,169 of 4,893 blanks |
| Still blank | `Exec Services - Other` |
| Flags | `role_group_source` = Department / JP Category / Designation (inferred) / none. `dept_certain` = 1 where StaffCentral's current Engagement ID is this engagement |
| Assumption | StaffCentral shows each person's **current** department, assumed unchanged when they move between clients. A check that rebuilds the main table using only rows where the department is certain correlates 0.84 with the full table |

## 1.4 Industry and region (Account Priority Dashboard rules)

These copy `Marketing Intelligence/format data/format_priority_data.ipynb` §0b, so both projects describe a client the same way. The shared copy of the industry rules, with the reasoning behind each bucket, is `references/mystaff_industry/` at the repo root.

| Field | Rule |
|---|---|
| `industry` | 18 groups. MyStaff `Industry Hubspot` mapped by `INDUSTRY_MAP`; if it isn't in the taxonomy, `Industry Roll Up` mapped by `ROLLUP_MAP`. Placeholder roll-ups (`CLOUDSTAFF`, `-`, test values) and `-` / `Other` / `Outsourcing/Offshoring` stay blank |
| `industry_sector` | The group's parent, one of 6 sectors (`INDUSTRY_SECTOR`) |
| `industry_fit` | What the models use: the group, or its **sector** when the group has fewer than 30 client accounts (`INDUSTRY_SECTOR_FALLBACK_N`). Today that applies to Energy & Environment and Non-profit & Public Sector |
| `region` | Office country and state: `AU-NSW`, `AU-VIC`, …, `AU` (state unknown), `US`, `UK`, `NZ`, `CA`, `SG`, `HK`, `IE`, `AE`, `PH`, `Other` |
| `country` | What the models use: Australia, United States, United Kingdom, New Zealand, Canada, Other, Unknown |

Brand (Cloudstaff / OptiBPO) is deliberately **not** used anywhere.

## 1.5 Accounts and headcount

| Term | Rule |
|---|---|
| Headcount timeline | +1 per start and −1 per exit, summed per account per date (`timeline.active_staff`) |
| Launch team / `launch_size` | Seats on **day 30** after the first hire (`LAUNCH_DAYS`), so staggered onboarding counts as one launch. Buckets 1–2, 3–4, 5+. A client with 0 seats on day 14 has no launch bucket and isn't scored as a new client |
| Seat milestone | The first day of a run at N or more seats that lasted at least **30 days** (`MILESTONE_HOLD_DAYS`). Brief spikes, such as a replacement overlapping a leaver, don't count |
| Churn | A zero-headcount gap of **more than 30 days** (`CHURN_GRACE_DAYS`). Shorter gaps are backfills |
| Client accounts | Excludes `CSTREENGAGE`, `CLOUDSTAFF`, accounts where at least 50% of rows are Category "Hub" (internal teams), and MyStaff `Internal = Yes` |
| Ready To Go rows | **Kept**. On client accounts they are past staff now on the bench (Category is a current status) |

## 1.6 Branching (department history)

| Term | Rule |
|---|---|
| Starting department | The department with the most hires in the first 30 days. Ties go to whichever was hired first, then by name |
| Department entered | Its first hire (`BRANCH_MIN_HIRES = 1`; set it to 2 to ignore one-off hires) |
| Branch | Entering a department that was not in the launch team |
| Starting department in models | The 12 most common starting departments by name, the rest grouped as "Other", and "Unknown" |

## 1.7 Propensity models

**Shared rules**

* **Training window:** clients that started in the last **5 years** (`PS_TRAIN_YEARS`). Only facts known at the time are used, so a score never sees its own outcome.
* **Model:** regularised logistic regression (`PS_C = 0.5`). Category levels with fewer than 15 training rows are pooled.
* **Checking:** 5-fold cross-validation, grouped by client for the snapshot models. AUC and per-band actual rates come from the held-out predictions.
* **Bands:** Low / Medium / High = thirds of the cross-validated historical scores. A band is relative. "High" means top third of past clients, not a fixed probability.

**New clients and prospects** (inputs: `industry_fit`, `country`, starting department group, launch bucket)

| Score | Outcome | Training clients | Who gets scored | AUC | Actual rate Low / Med / High | Average |
|---|---|---|---|---|---|---|
| `p_growth` | Reach and hold **5 seats within 365 days** of the first hire | launched with 1–4 staff, observed 395+ days (1,030) | profiles that launch with 1–4 staff | 0.72 | 4% / 6% / 18% | 10% |
| `p_reach_10_730d` | Reach and hold **10 seats within 730 days** | launched below 10, observed 760+ days (773) | profiles that launch below 10 | **0.83** | 1% / 2% / 11% | 5% |
| (20 seats in 1,095 days) | – | only 12 reached it | not fitted (`PS_MIN_POSITIVES = 15`) | – | – | – |
| `p_branch` | Add a department not in the launch team **within 365 days**. Leaving earlier counts as "no" | known starting department, observed 365+ days (1,087) | all profiles | 0.62 (weak) | 22% / 26% / 38% | 29% |

**Existing clients:** a **snapshot** of every client every 90 days of account age, starting at day 90. Each snapshot records what the account looked like on that day (inputs: account age, log of seats, seat change in the last 180 days, hires in the last 180 days, departments so far, `industry_fit`, `country`, starting department group). Training uses snapshots in the training window with a full year of follow-up and at least one seat (11,231 snapshots).

| Score | Outcome over the next 365 days | AUC | Actual rate Low / Med / High | Average |
|---|---|---|---|---|
| `p_seat_growth_12m` | More seats 365 days later than on the snapshot day (**net**, so backfills don't count) | 0.69 | 13% / 20% / 41% | 25% |
| `p_new_dept_12m` | Enters a department it has **never** had | 0.70 | 9% / 20% / 36% | 22% |

Active clients (engagement active and at least one seat today) are scored on today's snapshot: 1,002 clients.

## 1.8 Explanations and suggestions

| Output | Rule |
|---|---|
| `*_why` | For each trait, how much the score changes if that trait is set to a typical client's value (the median, or the most common category). Shows the top two traits that raise the score by more than 0.05 on the log-odds scale. "Other", "Unknown" and non-positive seat changes are never shown. Blank means no trait stands out |
| `vs_peers` | The client's score ÷ the average score of active clients in the same seat band (1–2, 3–4, 5–9, 10–29, 30+) |
| Likely next department (existing clients) | Learned from snapshots where a department was added, each "client added X" counted once. For each department held, the share of additions that were X. Averaged over the departments the client holds, excluding those, and rescaled to 100%. Needs at least 10 events per held department, otherwise the overall pattern is used, marked "(overall)" |
| Lift | Share ÷ that department's share of all additions (over the same options). 1.0x is average |
| `likely_next_dept_by_lift` | Top two by lift, among departments with at least a 3% share (`PS_LIFT_MIN_SHARE`) |
| Likely first new department (new clients) | First new department of past clients with the same starting department (needs at least 10). Prospects have no starting department, so they get the overall pattern |
| `outlook` | Both growth and branching High → "Grow + expand". Growth High → "Likely to grow". Branching High → "Likely to expand". Both Low → "Low propensity". Otherwise "Moderate" |

## 1.9 Assumptions and limits

| # | Assumption | Effect |
|---|---|---|
| A1 | StaffCentral's current department applies to past engagements | The department-join check correlates 0.84; some older history may be mislabelled |
| A2 | Designation can stand in for a blank JP Category | About 10% of inferred categories may be wrong |
| A3 | Prospects launch with 1–2 staff, starting department unknown | Prospect scores use only industry and country, so they separate clients less well (growth AUC about 0.62) |
| A4 | Past five years reflect today's sales motion | Rerun when the offer changes |
| A5 | Scores show association, not cause | A High band means "clients like this did this before", not "this will happen" |
| A6 | Likely next department is spread thin | The top share is usually 8–11%. Treat it as a lead |
| A7 | "Unknown" industry raises the seat-growth score | Untagged clients are mostly recent, so this reflects timing, not a real effect of having no industry |
| A8 | Raw files have different extract dates (2026-09-14 to 2026-10-07) | Align them when refreshing |

---

# Part 2: Code guide

## 2.1 Layout

```
Client Propensity/
  config.py                    every setting (paths, windows, thresholds, model settings)
  run_pipeline.py              run_all(): runs every step; writes outputs when run as a script
  Client Propensity.ipynb   thin notebook: runs the pipeline, shows tables and charts
  mi_pipeline/
    mappings.py                industry (18 groups / 6 sectors) and region rules: the dashboard's
    step1_format.py            load (with cache) and clean the 4 raw files
    step2_merge.py             exit reasons, departments (+ designation inference), industry, region
    step3_features.py          timeline, account summary, client accounts, branching history,
                               propensity inputs, seat measures, snapshot features
    step4_branching.py         descriptive branching analysis (transitions, time to branch, related depts)
    step4_propensity.py        models, NewClientScorer, scorecard, organic client list, prospect profiles
    step5_output.py            Excel workbook + notebook charts
    step5_extract.py           extract keyed for the Account Priority Dashboard
  (outputs)                    saved to config.OUTPUT_DIR = the local data folder, outside the repo
```

## 2.2 Running

```
uv sync                                                       # once, from the repo root
uv run python "Client Propensity/run_pipeline.py"
```

This writes `<date>_Client_Propensity_Scorecards.xlsx` and `<date>_Propensity_Extract.xlsx` (+ two CSVs) to `config.OUTPUT_DIR`, which defaults to the local data folder (`config.DATA_DIR`, outside the repo; override with `MIA_OUTPUT_DIR`). The extract (xlsx + CSVs) is also copied to the dashboard's local data folder, `config.DASHBOARD_FEED_DIR` (§3.1). The first run reads the Excel sources (about 45 s). Later runs use pickles in `DATA_DIR/_pipeline_cache`, which refresh automatically when a source file changes. **Close the output files in Excel before rerunning**, because Excel locks them.

From Python or the notebook:

```python
from run_pipeline import run_all
res = run_all(write_excel=True, write_extract=True)
res["propensity"]["scorer"].score("Technology", region="US", start_dept="Software Development", launch_size=3)
```

## 2.3 Data flow

| Step | Function | Returns |
|---|---|---|
| 1 | `step1_format.run(today)` | `engagement`, `seat_churn`, `mystaff`, `staff` (cleaned) |
| 2 | `step2_merge.run(formatted)` | `engagement` (+ exit reasons, `role_group`, `dept_certain`), `mystaff` (+ `industry_group`, `industry_sector`, `region`, `country`), `staff` |
| 3 | `step3_features.run(merged, today)` | `src`, `ends`, `timeline`, `summary`, `spells`, `clients`, `excluded_accounts`, `branch`, `dept_entered`, `accounts`, `top_starts`, `industry_fit_map`, `mystaff` |
| 4a | `step4_branching.run(feat)` | `start_dept_summary`, `transitions`, `top_paths`, `branch_by_industry`, `time_to_branch`, `related_pairs`, `growth_by_branch`, `sensitivity` (+ chart data) |
| 4b | `step4_propensity.run(feat, today)` | `new_client_scorecard`, `scorer`, `organic_client_list`, `organic_rising`, `prospect_profiles`, model checks and AUCs, driver tables (`new_factors`, `organic_factors`, `seat_factors`) |
| 5 | `step5_output.write_workbook(res)` | workbook path |
| 5b | `step5_extract.write_extract(res)` | extract path + its sheets |

Every step is a set of functions that take DataFrames and return DataFrames, so a step can be rerun or tested on its own. `run_all()` returns everything in one dict: `res["features"]`, `res["branching"]`, `res["propensity"]` and so on.

## 2.4 Key functions

| Function | What it does |
|---|---|
| `step2_merge.designation_map / staff_role_groups` | Learn designation → JP Category; build `role_group` and `role_group_source` |
| `step3_features._first_held_date` | First day of the first run at N or more seats that lasted at least the hold period |
| `step3_features.build_branching(rows, clients)` | Starting department, entry order and timing of new departments. Also used by the sensitivity check |
| `step3_features.snapshot_features` | Point-in-time features for any (client, date) list, using as-of joins on the timeline and cumulative hires |
| `step3_features.seat_measures` | Seats now, gross adds and net change over 180 days |
| `step4_propensity.fit` | Fit plus cross-validation; returns model, band cut-offs, band check table, AUC |
| `step4_propensity.factors` | "Drivers" tables: average score if every row had a given trait value, versus the actual average |
| `step4_propensity.reasons` | The `*_why` text: the change in log-odds when each trait is set to a typical value |
| `NewClientScorer.score_profiles / score` | Scores profile rows, or a single new client from industry plus country or region |

## 2.5 Changing things

| To change | Edit |
|---|---|
| A threshold or window | `config.py` |
| Which industry a raw value maps to | `mappings.py`, the same change in the dashboard's notebook §0b, and both rule docs |
| Add a seat milestone | `PS_MILESTONES`, e.g. `(20, 1460)`. It is fitted only if at least 15 training clients reached it |
| Model inputs | `PROFILE` / `ORG_NUM` / `ORG_CAT` in `step4_propensity.py`. Then check the AUCs and band tables in the workbook's "Model checks" sheet |
| New raw extracts | Drop them in `DATA_DIR`, update the file names in `config.RAW_FILES` and the dates in `EXTRACT_SOURCE_DATES` |
| Pin a run date | `config.AS_OF_DATE = "2026-11-12"` |
| Where the dashboard extract is copied | `config.DASHBOARD_FEED_DIR` (or the `MIA_DASHBOARD_DIR` environment variable); `None` = no copy |

## 2.6 Checks built in

* **Joins:** the seat-churn join reports any rows it duplicates; the department join can't change the row count (asserted); the MyStaff join asserts unique Shortcodes and matching key types.
* **Reconciliation:** voluntary + involuntary exits = exits with a known reason; reactivated accounts must have churned first.
* **Model quality:** each model logs its AUC and band cut-offs. The workbook's "Model checks" sheet shows the actual rate per band.
* **Regression baseline:** when the pipeline was moved out of the notebook, with designation inference switched off it reproduced all 22 reference tables exactly.

## 2.7 Environment

The repo's shared `.venv` (Python 3.12, pandas 3, scikit-learn, lifelines, openpyxl, matplotlib), set up with `uv sync`. The notebook needs the `.venv` kernel and runs from its own folder. It loads `%autoreload 2`, so edits to `config.py` and `mi_pipeline/` apply without restarting the kernel.

---

# Part 3: Handoff: adding the scores to the Account Priority Dashboard

**Status: proof of concept.** The two pipelines read MyStaff extracts from different dates (§3.8). That's accepted for now.

## 3.1 What is ready

Step 5b writes `<date>_Propensity_Extract.xlsx` and two CSVs to `config.OUTPUT_DIR`, then copies all three to the dashboard's local data folder (`config.DASHBOARD_FEED_DIR`, default `Desktop\Projects\Marketing Intelligence Priority\Data`; override with `MIA_DASHBOARD_DIR`, or set it to `None` to skip the copy). The dashboard reads them from its own folder. The dashboard pipeline doesn't read them yet.

`propensity_accounts` is deliberately narrow: the dashboard's key (`account_id`), `shortcode`, and the seat and department metrics. It carries no other company identifiers or descriptive columns (no CRM ID, industry or region): the dashboard keeps its own. The model version and as-of date are in `run_info`.

| Sheet / CSV | Rows | Join to the dashboard's `priority_list` |
|---|---|---|
| `propensity_accounts` (+ `_propensity_accounts.csv`) | 1,428 active MyStaff clients (Active = Yes, not a test account): the dashboard's Organic Growth set. 22 columns: `account_id`, `shortcode`, seat metrics, department metrics, new-client growth scores, `fit_coverage` (§3.3) | `account_id` (`MS-<shortcode>`), see §3.2 |
| `prospect_profiles` (+ `_prospect_profiles.csv`) | 133 = 19 industries (18 + Unknown) × 7 countries | `profile_key` = `industry|country`, after mapping the dashboard's `region` to country with `region_to_country` (`AU-*` → Australia, `US` → United States, …) |
| `column_dictionary` | 1 per column | – |
| `run_info` | model version, as-of date, source files, AUCs, band cut-offs | – |

**Reading the files.** Read the CSV with `dtype={"shortcode": str}` so a shortcode is never parsed as a number.

Coverage in `propensity_accounts` (`fit_coverage`): scored 1,001 · no current seats 286 · internal / non-client 98 · no engagement history 28 · no known starting department 15.

## 3.2 Joining to the dashboard

| Key | Dashboard Organic Growth rows matched (of 1,110) | Use |
|---|---|---|
| `account_id` (= `MS-` + `shortcode`) | 1,086 | **The key.** Unique on both sides. Joining on `shortcode` gives the same result |

The CRM / HubSpot company ID isn't in the extract. It would be a weaker key (1,048 matches: some clients have none, a few IDs are shared by more than one client, and 30 differ between the two sides). For a HubSpot write-back, use the dashboard's own `crm_company_id`.

The 24 dashboard rows without a match get no `fit_*` values and should show as "not scored":

* 22 clients that aren't in this project's MyStaff extract (newer clients: the extracts are dated 2026-10-05 here and 2026-11-09 on the dashboard).
* 2 `HS-` rows (HubSpot records on a shared franchise domain, so no shortcode).

**Industry and region come from the dashboard.** The extract has no descriptive columns, so nothing collides on the join and the dashboard keeps its own `industry`, `industry_sector` and `region`.

**Same taxonomy on both sides.** `mappings.py` and the dashboard notebook §0b were compared value by value: the same 18 industry groups with the same raw HubSpot values, the same 6 sectors, the same 59 `Industry Roll Up` fallbacks, and the same unclassified and placeholder lists. So an industry label means the same thing on both sides.

**The values per client don't match today.** With the same taxonomy, industry still differs on 968 of the 1,086 joined clients (region matches on all of them). The cause is the source files. In the dashboard's `CONFIDENTIAL Mystaff 11092026 - Copy.xlsx`, the `Industry Hubspot` and `Industry Roll Up` columns are out of line with the client rows:

* Client names (99.5%) and office countries (92%) match this project's 2026-10-05 extract, but `Industry Hubspot` matches on only 4%.
* A check on client names shows which file is out of line:

| Name contains | Tagged as | 2026-10-05 extract (this project) | 2026-11-09 copy (dashboard) |
|---|---|---|---|
| account, tax, CPA, bookkeeping | Accounting | 82% | 9% |
| realty, real estate, property | Real Estate | 87% | 17% |
| dental, medical, health, clinic | Healthcare & Wellness | 42% | 8% |
| law, legal, attorney, solicitor | Legal | 100% | 0% |

Until the dashboard's MyStaff file is re-exported, the dashboard shows the wrong industry for most clients. That industry also isn't the one the `fit_*` scores were calculated with (this project's 10/05 values, shown in the scorecards workbook). The same problem affects the dashboard's own `industry_trend` and industry modifier.

## 3.3 Field mapping

| Extract column | Dashboard column | Notes |
|---|---|---|
| `account_id`, `shortcode` | same | Organic Growth only. Join key, see §3.2 |
| `seats_current` | `cs_staff_current` | Engagement-list headcount vs MyStaff Total Staff (correlation 0.99) |
| `seats_added_6m_gross` | `seats_added_6m` | Same idea, older source. Not needed on the dashboard (§3.4) |
| `seats_change_6m_net` | – | Net change, for reference (§3.4) |
| `fit_seat_growth_p` / `_band`, `fit_seat_vs_peers`, `fit_seat_why` | – (new) | Seat growth: more seats in 12 months (§1.7, §3.5) |
| `fit_dept_expand_p` / `_band`, `fit_dept_vs_peers`, `fit_dept_why` | – (new) | Department expansion: enters a department it has never had, in 12 months (§1.7, §3.5) |
| `likely_next_dept`, `likely_next_dept_by_lift` | – (new) | Which department is most likely next (§1.8) |
| `fit_growth_*`, `fit_reach_10_*` | – (new) | New clients only: 5 seats in 1 year, 10 seats in 2 years |
| `fit_coverage` | – (new) | Why a client has no score |

Add the new columns as a column group, e.g. `5_propensity`, flagged as a dashboard extension. **Keep them separate from `priority_score`**.

**Organic Growth rows:** every column above, from `propensity_accounts`.
**New Logo rows:** `fit_growth_*`, `fit_reach_10_*`, `fit_branch_1y_*`, `likely_first_new_dept` from `prospect_profiles`.

## 3.4 Seat growth: which figure to use

Four candidates, each covering about the last 6 months:

| Figure | Source | Counts |
|---|---|---|
| `seats_added_6m` (dashboard, live today) | MyStaff `Movement Add`, month to date + 5 months | gross adds (includes replacements) |
| MyStaff net (not loaded yet) | MyStaff `Movement Net`, same months | adds minus removes |
| `seats_added_6m_gross` (extract) | Engagement list: starts in the last 180 days | gross adds |
| `seats_change_6m_net` (extract) | Engagement list: seats today minus seats 180 days ago | net change |

**Source vs definition.** Across the 1,086 joined clients, the source barely matters. MyStaff gross and engagement-list gross fall in the same dashboard band (0 / 1–5 / 6–10 / 11+) for 96% of clients (correlation 0.93); the two net figures agree on 95%. Gross vs net matters more: 88 of the 340 clients with MyStaff adds had a net change of zero or less, because they only replaced leavers.

**Backtest.** On the 11,231 historical client snapshots (§1.7), how well each figure ranks clients by "more seats 365 days later" (AUC):

| Signal | AUC |
|---|---|
| Gross adds, raw count | 0.658 |
| Net change, raw count | 0.643 |
| Gross, banded as the dashboard does | 0.645 |
| Net, banded the same way | 0.635 |
| Gross band, halved when net ≤ 0 | 0.653 |
| `fit_seat_growth_p` (cross-validated, §1.7) | 0.69 |

Share that grew over the next year: adds and positive net change 40% · adds but net ≤ 0 26% · no adds 16% (average 25%).

**Recommendation**

1. **Keep the dashboard's `seats_added_6m` (MyStaff gross) as the scored seat signal.** Gross predicts slightly better than net. MyStaff is fresher than the engagement list and is already wired in. Don't replace it with `seats_added_6m_gross`: that measures the same thing (96% same band) from an older extract.
2. **Optional:** halve the seat signal when MyStaff net (`Movement Net`, same months) is zero or less. This discounts clients that only replaced leavers (88 today) and lifts the AUC from 0.645 to 0.653. It's a dashboard-side change (`SEAT_WINDOW`, `standardize_mystaff()`).
3. **Bring over `fit_seat_growth_*`** as the forward-looking companion. It combines size, recent adds, net change, tenure and profile, and is the best single predictor (0.69). It is a fit score, so keep it out of `priority_score` (§3.7).

Caveats: the backtest uses the engagement-list measures. MyStaff gross shares 96% of its bands with them, so the ranking should carry over. The engagement extract ends 2026-10-07 while the as-of date is 2026-11-12, so today's engagement-list figures miss the last five weeks.

## 3.5 The "why" columns

| Column | Explains |
|---|---|
| `fit_dept_why` | `fit_dept_expand_p` (department expansion): chance of entering a department the client has never had, in the next 12 months |
| `fit_seat_why` | `fit_seat_growth_p` (seat growth): chance of having more seats 12 months from now (net) |

Both are built the same way (`step4_propensity.reasons`, §1.8), each from its own model:

1. Both models use the same 8 inputs: seats now, net seat change in the last 180 days, hires in the last 180 days, departments so far, years since the first hire, industry, country and starting department.
2. For each input, the client's value is swapped for a typical client's value: the median of the historical snapshots for numbers, the most common value for categories. The drop in the score, on the log-odds scale, is that input's contribution.
3. The two inputs that raise the score most (each by more than 0.05 log-odds) are shown, largest first, separated by "; ".
4. Never shown: "Other" or "Unknown" categories, and a seat change of zero or less. **Blank** means no input raises the score above a typical client's.

Labels: `134 seats` · `+6 seats in last 6m` · `12 hires in last 6m` · `4 depts already` · `0.8 yrs with us` · `industry: Real Estate` · `country: United States` · `started in: Accounting Support Services`.

Today, across 1,001 scored clients: `fit_dept_why` is blank for 100 and `fit_seat_why` for 72, and the two are identical for 168. The most common reasons are seats and years with us (both columns), the starting department (`fit_dept_why`), and departments already and country (`fit_seat_why`). A reason explains the score, not the cause (A5).

## 3.6 Integration steps (in the dashboard pipeline)

1. **Extract:** add `extract_propensity()` to stage 1. It reads the newest `*_Propensity_Extract_propensity_accounts.csv` and `*_prospect_profiles.csv` from the dashboard's own data folder (with `dtype=str` for `shortcode`, §3.1), plus `run_info` from the xlsx for the model version and as-of date.
2. **Merge:** after stage 4 or 5, left-join `propensity_accounts` on `account_id` (§3.2). For New Logo, derive `country` from `region`, build `profile_key = industry + "|" + country`, and left-join `prospect_profiles`. Unknown industry or country falls back to the `Unknown` rows, which exist for every combination.
3. **Columns:** add a `5_propensity` group to `COLUMN_GROUPS` / `DASHBOARD_EXTENSIONS`, and copy the model version and as-of date from the extract's `run_info` into the dashboard's `run_info` (e.g. as `fit_model_version`, `fit_as_of`).
4. **DQ checks** (stage 6 or 10):
   * share of Organic Growth rows matched to the extract at least 95% (today 1,086 of 1,110): warn. Unmatched rows are expected (§3.2)
   * `fit_*_p` within 0–1: error
   * bands within Low / Medium / High: error
   * share of Organic Growth rows `scored` above a threshold, e.g. 70%: warn
   * the extract's as-of date (`run_info`) within 45 days of `SCORING_AS_OF`: warn
   * The same checks on the extract itself (unique `account_id`, ranges, bands, the MyStaff file used) are planned for step 5b on this side, but on hold (§3.9)
5. **Dashboard data** (stage 11): add the fields to `DASH_ROW_FIELDS`, and the model AUCs and band definitions to `meta` for a glossary card.
6. **Page** (part 2): a Fit column and filter on each list, a glossary card (what each score means, AUC, what each band delivered), and the chips in §3.7.

## 3.7 Ways to use the scores

| Idea | How | Why |
|---|---|---|
| **Fit × timing grid** | Fit band (rows) × priority tier (columns), per list | "Act now + High fit" first; "High fit, no trigger" as a nurture list for Marketing. The idea is in the dashboard's CLAUDE.md |
| **Fit multiplier** | Like the industry modifier, e.g. 0.95 / 1.00 / 1.05 for Low / Medium / High | Agreed later stage (dashboard open item §15.13: "a fit score as a multiplier") |
| **Replace mock `industry_trend`** | Use the learned industry effects (workbook drivers sheets) | Data-backed instead of mock values |
| **Why chips** | "Likely to add seats (High, 1.6× peers)", "Likely next: Sales (3.8×)", "Profile tends to grow" | Uses `fit_*_why` (§3.5), `likely_next_dept_by_lift`. Show the reason once when `fit_seat_why` equals `fit_dept_why` |
| **BDM talk track** | `likely_next_dept_by_lift` for clients, `likely_first_new_dept` for prospects | What to pitch next |
| **Routing** | "High fit, no trigger" → BDM instead of the random draw | Dashboard open item §15.7 / A9 |
| **Validating the dashboard's weights** | Use this project's outcomes (reached 5/10 seats, more seats in 12 months, new department) as labels | Dashboard open item §15.12 |

Combinations with `priority_score` can't be judged until the dashboard's signals are real. Today all except seat growth are mock.

## 3.8 Operating it

| Topic | Recommendation |
|---|---|
| Proof of concept | The extracts aren't aligned: here MyStaff 2026-10-05 and the engagement list 2026-10-07; on the dashboard MyStaff 2026-11-09. Accepted for the POC. Align them before going live |
| Refresh | Monthly, after new extracts land: rerun this pipeline (it copies the extract to the dashboard folder), then the dashboard pipeline |
| Same extracts | When going live, use the same MyStaff (and ideally engagement) extract on both sides. This project needs inactive clients too (training history), so it needs the full MyStaff export, not an active-only copy |
| Versioning | The model version (`run_info`) changes whenever inputs, windows or taxonomy change. Keep the previous extract until the new one is checked |
| Retraining check | After each refresh compare AUCs and band rates in `run_info` and "Model checks" with the last run. A drop of more than 0.05 AUC needs a look |
| Confidentiality | The extract lists clients and scores: it lives only in the two local data folders (`config.OUTPUT_DIR`, `config.DASHBOARD_FEED_DIR`), never in git |

## 3.9 Open decisions

1. Fit grid, multiplier, or both (§3.7)? This needs agreement with Sales and Marketing.
2. Should clients with no current seats (286) get a separate win-back score?
3. Score 20 seats with a longer window, e.g. 4 years, once more history exists?
4. Seat signal: keep MyStaff gross `seats_added_6m` (recommended, §3.4). Add the net discount?
5. Should prospect scores use more than industry and country (e.g. Team Builder role or requested headcount) once captured?
6. Re-export the dashboard's MyStaff file before showing industry on the page (§3.2).
7. Checks inside step 5b (unique `account_id`, `fit_*_p` within 0–1, valid bands, MyStaff file matching the dashboard's): planned, on hold.
