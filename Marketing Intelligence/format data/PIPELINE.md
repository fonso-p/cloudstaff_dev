# Priority Score pipeline: technical guide

**Pipeline version:** 0.4 (prototype) · **Code:** [`format_priority_data.ipynb`](format_priority_data.ipynb) (part 1) and
[`../build_dashboard/`](../build_dashboard/README.md) (part 2)

This guide explains how the code is built and how to run it. **What the pipeline decides, and why** (mappings, thresholds,
matching, scoring, routing, assumptions) is in [`BUSINESS_RULES.md`](BUSINESS_RULES.md). Rule section numbers (§) below refer to that file.

---

## 1. Overview

```
PART 1: format data/format_priority_data.ipynb
  EXTRACT → STANDARDIZE → MATCH → MERGE → CONFORM → DQ → SIGNALS → SCORE → ROUTE → DQ → DASHBOARD DATA → LOAD
  raw exports (local)                                                                    processed data (local)
                                                                                                │
PART 2: build_dashboard/build_dashboard.py                                                      ▼
  newest account_priority_dashboard_data*.json  ───────────────────►  <date>_Account_Priority_Dashboard[_MOCK_SIGNALS].html (local)
```

* **Part 1** merges, formats, scores and routes HubSpot and MyStaff accounts, and saves the **processed data** locally.
* **Part 2** only builds the dashboard page from that data. It doesn't touch the raw data or the scoring.
* **Raw data, processed data and the built dashboard stay local** (`~/Desktop/Projects/Marketing Intelligence Priority/Data`), never in the repo.

## 2. Files

| Path | What it is |
|---|---|
| `format data/format_priority_data.ipynb` | Part 1: the whole pipeline, one stage per notebook section. Committed without outputs |
| `format data/BUSINESS_RULES.md` | Business rules, assumptions, data catalogue |
| `format data/PIPELINE.md` | This guide |
| `build_dashboard/build_dashboard.py` | Part 2: validates the processed JSON and builds the page |
| `build_dashboard/dashboard_template.html`, `assets/` | The dashboard page, Cloudstaff tokens and logo |
| `reference materials/data/accounts.csv` | 400 mock accounts scored with the original settings: **golden test 1** (read only) |
| `data/account_priority_dashboard.json` | 800 accounts scored by the mock dashboard's `prep.py`: **golden test 2** (read only) |

The two golden-test files must stay where they are, because the notebook reads them by relative path
(`../reference materials/…` and `../data/…`, from the `format data` folder).

## 3. How to run

**Requirements:** the repo's `.venv` (Python 3.12) with `pandas`, `numpy`, `openpyxl`, `nbformat` and Jupyter.
The raw files must be in the local data folder: the HubSpot report (`hubspot-core-report-*.xlsx`, newest is used) and
`CONFIDENTIAL Mystaff 11092026 - Copy.xlsx`.

**Part 1: format and score**

1. Open `format data/format_priority_data.ipynb`, with the repo's `.venv` as the kernel.
2. Run the cells in order. Cells marked `# INSPECT` show data, and cells marked `# TEST` check it. The pipeline doesn't need either.
3. To save the processed data, set `SAVE_OUTPUT = True` in §0a **before** running section 12. It writes to the local data folder:
   * `priority_company_info_combined[_MOCK_SIGNALS].xlsx`
   * `account_priority_dashboard_data[_MOCK_SIGNALS].json`

Or run everything in one call (how a scheduled job would): set `RUN_END_TO_END = True` in the last section, or call
`run_pipeline(save=True)`. It returns `(output, dq, recon, dashboard_data)`.

The MyStaff sheet has about 1 million formatted-but-empty rows, so its extract takes about a minute.

**Part 2: build the dashboard**, from the `Marketing Intelligence` folder:

```bash
../.venv/Scripts/python.exe build_dashboard/build_dashboard.py
```

It uses the newest `account_priority_dashboard_data*.json` in the local data folder and writes
`<today>_Account_Priority_Dashboard.html` to the same local folder. Options: `--data <json>`, `--out <html>` (`{date}` = today).
Optional page check (each page should print `errors: []`):
`../.venv/Scripts/python.exe ../.claude/skills/cs-dashboard/scripts/check_page.py "<local data folder>/<file>.html"`

**Switches** (in §0a / §0b of the notebook, except `RUN_END_TO_END`, which is in the last section):

| Switch | Default | Effect |
|---|---|---|
| `SAVE_OUTPUT` | `False` | Write the Excel output and dashboard JSON (stage 12) |
| `RUN_END_TO_END` | `False` | Run `run_pipeline()` in the last cell |
| `SOURCE_MODE` | `"excel"` | Where the raw data comes from (see §8) |
| `ENRICHMENT_MODE` | `"mock"` | `"mock"` = synthetic signals; `"live"` = not built yet, raises an error |
| `SCORING_PROFILE` | `"dashboard_v3"` | Which scoring settings are live: `"dashboard_v3"` (`dashboard_v2` plus Fit points, 2026-11-13), `"dashboard_v2"` (review of 2026-11-10, live in v0.3), `"dashboard"` (live until v0.2) or `"workbook"` (`"dashboard_reference"` exists only for golden test 2) |
| `ROUTING_MODE` | `"random"` | How teams are assigned: `"random"` (seeded draw, mock) or `"rules"` (deterministic) |
| `MOCK_SEED` | `42` | Seed for the mock signals (and the mock propensity values) |
| `PROPENSITY_MODE` | `"real"` | Fit scores from the Client Propensity extract: `"real"`, `"mock"` (synthetic) or `"off"` (§11.1b) |
| `SCORING_AS_OF` | run date | Date news recency is measured from |

## 4. Stages and functions

One stage per notebook section (§1–§12 in the notebook). Each stage is a function that takes DataFrames and returns DataFrames,
so stages can be rerun or tested one at a time.

| # | Stage | Function | Takes | Returns |
|---|---|---|---|---|
| 1 | Extract | `extract_hubspot()`, `extract_mystaff()` | source files | raw DataFrame in the source contract |
| 2 | Standardize | `standardize_hubspot()`, `standardize_mystaff()` | raw | staging DataFrame (`STAGING_COLS`) (+ MyStaff rejects) |
| 3 | Match | `match_sources()` | both staging tables | one row per HubSpot record with its match |
| 4 | Merge | `merge_sources()` | staging tables, matches | merged accounts + a reconciliation count |
| 5 | Conform | `conform_to_output()` | merged | output layout (`OUTPUT_COLS`), placeholders for signals and scoring |
| 6 | DQ: merge | `run_dq_checks()`, `assert_dq()` | output + staging | check table; stops on a failed `error` |
| 7 | Signals | `add_signals()` | output | + mock signals and `industry_trend` (`seats_added_6m` already real) |
| 7b | Propensity | `add_propensity()` (`extract_propensity()` for real, `generate_mock_propensity()` for mock), `run_propensity_checks()` | output | + the `5_propensity` columns, and `(out, info)`: `info` feeds the dashboard meta and `run_info` |
| 8 | Score | `score()` → `score_accounts()` (`known_mean_fill()` for unknowns, `percentile_tier()` for tiers) → `score_account()` (`_signals()`, `act_now_bonus()`) | output, settings profile | + points, score, tier, Act now triggers and bonus |
| 9 | Route | `route()` → `route_account()` → `trigger_team()` if there is an Act now trigger, else `route_account_random()` or `route_account_rules()` | scored output | + `assigned_team`, `rank_in_team_list` |
| 10 | DQ: scoring | `run_scoring_checks()` | output | check table; stops on a failed `error` |
| 11 | Dashboard data | `build_dashboard_data()`, `run_dashboard_checks()` | output, reconciliation | the dashboard's JSON object (§6 below) |
| 12 | Load | `load_output()`, `load_dashboard()` | output, matches, rejects, DQ, JSON | files in the local data folder |

`run_pipeline()` chains stages 1–12. The rules each stage applies are in BUSINESS_RULES.md: §5–§8 (stage 2), §9 (3), §10 (4),
§4 (5), §11.1 (7), §11.2 (8), §11.3 (9), §13 (6, 10, 11).

## 5. Where each rule lives in the code

All rules are data (dicts, lists, constants) in notebook §0a–§0b, not buried in functions. Only the dashboard display mapping
(`DASH_RENAME`, `DASH_ROW_FIELDS`, `SEAT_BAND_LABELS`) sits in §11, next to the code that uses it. To change a rule, change it
there and update BUSINESS_RULES.md.

| Setting | Controls | Rules § |
|---|---|---|
| `SOURCES`, `DATA_DIR`, `OUTPUT_PATH`, `DASHBOARD_JSON_PATH` | Input and output files | – |
| `HUBSPOT_CONTRACT`, `MYSTAFF_CONTRACT`, `SEAT_WINDOW` | Source fields used and their pipeline names; the months summed for seat growth | 3, 11.1 |
| `COMPANY_COLS`, `ENRICHMENT_COLS`, `SCORING_COLS`, `LINEAGE_COLS`, `COLUMN_GROUPS`, `DASHBOARD_EXTENSIONS` | Output columns and their groups | 4 |
| `TEST_ACCOUNT_PATTERN`, `PLACEHOLDER_ROLLUP` | MyStaff rows removed; placeholder industry labels | 5 |
| `INDUSTRY_GROUPS`, `INDUSTRY_SECTOR`, `UNCLASSIFIED_INDUSTRY`, `ROLLUP_MAP` | Industry taxonomy and fallback (`INDUSTRY_MAP` is derived from `INDUSTRY_GROUPS`) | 6 |
| `BAND_EDGES` | Employee bands | 7 |
| `COUNTRY_CODE`, `AU_STATE`, `TLD_COUNTRY`, `NAME_COUNTRY`, `REPORT_COUNTRY`, `REPORT_US`, `NAME_NON_US`, `ASSUMED_TLD` | Region rules | 8 |
| `MATCH_RANK`, `AMBIGUOUS` | Match priority and the ambiguous label | 9 |
| `GOALS` | Goal labels | 10 |
| `ENRICHMENT_MODE`, `MOCK_SEED`, `INDUSTRY_TREND`, `NEWS_STRENGTH`, `NEWS_UNMAPPED`, `RECENCY` | Signals and their lookups | 11.1 |
| `SCORING_PROFILES` (`SCORING_WORKBOOK`, `SCORING_DASHBOARD_REFERENCE`, `SCORING_DASHBOARD`, `SCORING_DASHBOARD_V2`, `SCORING_DASHBOARD_V3`), `SCORING_PROFILE` | Scoring settings | 11.2 |
| `FIT` (band values, part weights per goal, `chip_band`) and, in `SCORING_DASHBOARD_V3`, `max_points[...]["fit"]` (New Logo 20, Organic Growth 25) and `baseline["fit"]`. A profile without `fit` scores no fit. Code: `_fit_signal()` (stage 8), `fit_chips()` (stage 11) | Fit points and fit chips | 11.2b |
| In `SCORING_DASHBOARD_V2`: `unknown_fill` (`"known_mean"`), `act_now_bonus.stack_decay` (0.5), `tier` (`method: "percentile"`, `tier1_share` 0.10, `tier2_share` 0.30), `hot_first` (`False`). A profile without these keys keeps the old behaviour (flat `baseline`, first trigger only, fixed-score tiers, +1000 sort) | Unknown values, bonus stacking, tiers, list order | 11.2 |
| `TRIGGER_FAMILY` | Trigger → family (Website, News, Hiring, Referral): one bonus per family when bonuses stack | 11.2 |
| `ACT_NOW_TARGET_SHARE` (0.10) | DQ warning when more of a goal's accounts have an Act now trigger | 13 |
| `_HOT` (workbook / reference triggers), `_HOT_LIVE` (turns on `team_builder_prospect`, `hiring_spike` with `hiring_min_postings` 18, `heavy_visits_min` 10, and `campaign_news` restructuring / leadership change with `campaign_news_days` 60), `_HOT_V2` (the live triggers: `heavy_visits_min` 20, `campaign_news_days` 30), `act_now_bonus` in each profile | Act now triggers and their bonus | 11.2 |
| `_TIER`, `_MODIFIER` | Fixed-score tier thresholds (older profiles); industry multiplier range | 11.2 |
| `REF_BANDS`, `REF_REGIONS` | Allowed employee bands; reference region list (used by the DQ checks) | 7, 8, 13 |
| `TRIGGER_TEAM`, `ROUTING_MODE`, `ROUTING_PROBABILITIES`, `TEAM_GOALS`, `BDM_TOP_SHARE` (top 10% of a goal's accounts without a trigger = BDM candidates; `bdm_candidates()`, `bdm_cutoffs()`), `route_account_rules()`. `BDM_MIN_SCORE` (60) is used only by the workbook golden test | Routing: trigger → team, then the draw or rules | 11.3 |
| `DASH_ROLES`, `DASH_LISTS`, `CHIP_STRONG`, `CHIP_MODERATE`, `GROWING_INDUSTRY`, `MOCK_CHIP_TAG` | Dashboard lists and Why chips | 11.4 |
| `GOLDEN_PATH`, `DASHBOARD_GOLDEN_PATH`, `GOLDEN_AS_OF`, `GOLDEN_INDUSTRY_TREND` | Golden tests | – |

## 6. Dashboard data contract (stage 11 → part 2)

Stage 11 builds one JSON object, stage 12 saves it, and `build_dashboard.py` embeds it in the page. The page reads four keys:

| Key | Content |
|---|---|
| `rows` | One object per account (see below) |
| `settings` | `SCORING` (the live profile) as `{key, label, value, kind}` rows. Tiers come as `tier1_share` / `tier2_share` (percentile tiers) or `tier1` / `tier2` (fixed scores); `hot_bonus_stack` when bonuses stack; `base_*` are only the fallback when `unknown_fill` is `known_mean`. Plus plus `bdm_min` (`BDM_MIN_SCORE`), the news strengths `news_1…8` (`NEWS_STRENGTH`), the recency factors `rec_1…4` (`RECENCY`), and the trigger thresholds `hot_days`, `hiring_min_postings`, `heavy_visits_min` and `campaign_news_days`. The page shows every weight and threshold from here, so nothing is typed into the page |
| `meta` | `title`, `subtitle`, `source`, `extract` (as-of date), `generated`, `shown_teams` (the 5 lists), `roles`, `band_order`, `default_example` (worked-example account), `mock_signals`, `enrichment_mode`, `trigger_teams` (`{trigger, goal, team, family, bonus}` for each live trigger, shown on the Act now card; from `live_triggers()`, `TRIGGER_TEAM` and `TRIGGER_FAMILY`), `scoring_profile`, `hot_first` (whether Act now accounts sort first), `unknown_fill` (`{goal: {web, news, seat}}`: share of max used for an unknown component), `tier_cutoffs` (`{goal: {tier: lowest score}}`), `notice` (warning banner, HTML) |
| `qa` | `{step, rows}` counts for the QA page: HubSpot records, merged, moved to Organic Growth, MyStaff clients, accounts per goal and list, seat data known / unknown |

**Row fields.** Pipeline columns are renamed to the dashboard's names by `DASH_RENAME`:
`prior_bpo_flag` → `competitor_client`, `bpo_pts` → `competitor_pts`, `assigned_team` → `role`,
`score_before_bonus` → `workbook_score`, and the three `… (0-1)` signal columns without the suffix.
`DASH_ROW_FIELDS` lists every field written: those the page reads, plus fields kept for tracing and export that the page doesn't read
(`shortcode`, `crm_company_id`, `enrichment_source`, `raw_score`, `csv_team`, `data_coverage`, `sort_key`). Rows are written sorted by `sort_key`.

Fields built by stage 11 (not pipeline columns):

| Field | How |
|---|---|
| `team` | `role` + `\|` + `goal` (the list) |
| `chips` | `dashboard_chips()`: the "Why" reasons as `[text, kind]` (`signal`, `flag`, `est`) |
| `profile`, `industry_lbl`, `band_lbl` | Display text; "Unknown" for blanks |
| `estimated` | 1 if `estimated_fields` is not blank |
| `seat_band` | `0`, `1-5`, `6-10`, `11+` (Organic Growth only) |
| `raw_score` | Base points × industry modifier, before rounding (not shown on the page) |
| `workbook_tier` | Tier of `workbook_score` (before the Act now bonus), with the live tier rule (`tiers()`) |
| `csv_score`, `csv_tier`, `csv_team` | The same accounts scored with `SCORING_WORKBOOK`. `csv_score` and `csv_tier` feed the page's comparison charts; `csv_team` isn't shown |
| `act_now_bonus`, `act_now_triggers` | Pipeline columns, passed through. The list shows every trigger; the worked example uses the bonus (older JSON without it falls back to +15 / +7.5) |

The JSON must be strict (no NaN, dates or numpy types): `_json_value()` converts values, and `json.dump(…, allow_nan=False)` enforces it.

**Two layers of checking:** `run_dashboard_checks()` (stage 11) checks the object when it's built, and `build_dashboard.py` checks the
same `meta` keys, settings keys (`REQUIRED_SETTINGS`) and row fields again from the file before embedding, so a mismatch between the notebook and the template fails
with a clear message instead of a blank page.

**Part 2 internals.** `build_dashboard.py` replaces three markers in the template (`/*__TOKENS__*/`, `<!--__LOGO__-->`, `/*__DATA__*/`,
each must appear exactly once) and `__TITLE__`. It escapes `</` in the data so it can't close the `<script>` tag. The page name
gets `_MOCK_SIGNALS` when `meta.mock_signals` is true. The template's warning banner is filled from `meta.notice`.

## 7. Tests and checks

| Check | Where | Behaviour |
|---|---|---|
| **Golden test 1**: `SCORING_WORKBOOK` reproduces 400 accounts in `accounts.csv` (15 columns) | §8, `# TEST` cell | `assert`: stops on any mismatch |
| **Golden test 2**: `SCORING_DASHBOARD_REFERENCE` (the live profile without the new triggers) reproduces 800 accounts in `account_priority_dashboard.json` (10 columns) | §8, `# TEST` cell | `assert`: stops on any mismatch |
| Data quality checks (what each enforces: BUSINESS_RULES.md §13) | `run_dq_checks()`, `run_scoring_checks()`, `run_dashboard_checks()` | each returns a table of `check, level, passed, detail`; `assert_dq()` stops on a failed `error` |
| Page renders without JavaScript errors | `check_page.py` (optional) | manual |

A check's `level` is `error` (stops the run), `warn` (reported only) or `info`. The golden tests compare against files made by
the original scoring and the mock dashboard, so they prove the scoring code matches those, not that the settings are right.

## 8. Going to production

| Today | Production change | Where |
|---|---|---|
| Raw data from Excel exports (`SOURCE_MODE = "excel"`) | Add a DB / API branch that returns the same contract fields (`HUBSPOT_CONTRACT`, `MYSTAFF_CONTRACT`). Nothing downstream changes | `extract_hubspot()`, `extract_mystaff()` (they raise `NotImplementedError` for other modes) |
| Mock signals (`ENRICHMENT_MODE = "mock"`) | Real sources returning the same 9 columns, in a new `"live"` branch (sources and join keys: BUSINESS_RULES.md §11.1) | `add_signals()`, replacing `generate_mock_enrichment()` |
| `industry_trend` = mock lookup | Real industry-news scores | `INDUSTRY_TREND` |
| Run by hand in the notebook | Move the stage functions into a module, call `run_pipeline(save=True)` from a scheduler, then `build_dashboard.py` | – |
| Output to local Excel and JSON | The same files, or the same tables written to a database | `load_output()`, `load_dashboard()` |

## 9. Output files

All written to the local data folder. While signals are mock, every file name gets a `_MOCK_SIGNALS` suffix.

| File | Content |
|---|---|
| `priority_company_info_combined.xlsx` | Sheets: `priority_list` (all 55 columns, header colour = column group), `column_groups` (with a `dashboard_extension` flag), `hubspot_mystaff_matches`, `mystaff_rejects`, `dq_checks`, `scoring_settings`, `run_info` (version, run date, `enrichment_mode`, `scoring_profile`, `scoring_as_of`, source file names) |
| `account_priority_dashboard_data.json` | The dashboard's data (§6 above) |
| `<date>_Account_Priority_Dashboard.html` | The built page (part 2). **Contains every account row** |

## 10. Known quirks

* **Notebook paths are relative to the `format data` folder** (golden-test files). Open the notebook from there.
* **The `None` news category** means "checked, nothing found". Pandas reads the string `None` as missing by default, so the golden
  test 1 loads the CSV with `keep_default_na=False`. The mock dashboard's JSON lost it, so golden test 2 restores it where the dashboard
  treats news as known.
* **Excel rounding.** Scoring uses `xl_round()` (half away from zero), not Python's `round()`, to match the workbook.
* **Seeded mock signals and teams.** Each account's mock signals and its random team depend only on `MOCK_SEED` and `account_id`, so they don't change with row order.
* **The notebook is committed without outputs** (they contain client data). Clear outputs before committing.
