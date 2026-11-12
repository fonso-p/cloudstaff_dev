# Client Propensity

This project answers three questions:

- **New clients and prospects:** which client profiles are likely to grow from their first staff to 5 seats within a
  year, and to 10 seats within two years?
- **Existing clients:** which active clients are likely to keep adding seats over the next 12 months, and to branch
  into a department they have never had (and which one)?
- **Combined:** for a brand-new client, how likely is seat growth, and how likely is it to add a second department?

The results are line items: one row per client profile, or one row per active client. They come out as an Excel
workbook and in the notebook.

Full business rules, a code guide and the handoff for the Account Priority Dashboard are in
[DOCUMENTATION.md](DOCUMENTATION.md).

## How to run

From the repo root:

```
uv sync
uv run python "Client Propensity/run_pipeline.py"
```

This writes two separate outputs to the local data folder (`config.OUTPUT_DIR`, the same folder as the raw files):

- `<date>_Client_Propensity_Scorecards.xlsx`: the line items for Sales and Account Managers.
- `<date>_Propensity_Extract.xlsx` (plus two CSVs): the same scores, laid out to line up with the
  Account Priority Dashboard's data (see [Dashboard extract](#dashboard-extract)).

To browse the results with charts, open `Client Propensity.ipynb` with the repo's `.venv` kernel and run
all cells. Close the output files in Excel before rerunning: Excel locks them.

The first run reads the Excel files, which takes about 45 seconds. Later runs use a cache and are faster. The cache
refreshes itself when a raw file changes.

## Pipeline

| Step | File | Input → output |
|---|---|---|
| 1 Format raw data | `mi_pipeline/step1_format.py` | 4 raw Excel files → cleaned tables (IDs, text, dates). Only the needed columns are read. |
| 2 Merge | `mi_pipeline/step2_merge.py` | Adds seat churn exit reasons and StaffCentral departments to each engagement, and industry groups to MyStaff |
| 3 Data engineering | `mi_pipeline/step3_features.py` | Builds the headcount timeline, the account summary (lifecycle, churn, held milestones, attrition, exit reasons, launch size), the client list, each client's department history and the snapshots |
| 4a Analysis: branching | `mi_pipeline/step4_branching.py` | Start → next department, time to branch, related departments, branching vs growth, and a check on the department join |
| 4b Analysis: propensity | `mi_pipeline/step4_propensity.py` | New-client models (5 seats in 1 year, 10 seats in 2 years, a department in year 1), scorecard and prospect profiles; existing-client models (seat growth, new department) and client list |
| 5 Output | `mi_pipeline/step5_output.py` | Excel workbook and notebook charts |
| 5b Dashboard extract | `mi_pipeline/step5_extract.py` | The extract keyed like the Account Priority Dashboard |

- `run_pipeline.py` runs the steps in order. `run_all()` returns every table.
- `config.py` holds every setting: paths, windows, thresholds and model settings.
- `mi_pipeline/mappings.py` holds the industry and region mappings. They are the Account Priority Dashboard's own
  (18 industry groups under 6 sectors, and region codes such as `AU-NSW`), so both describe a client the same way.

## Data

The raw files are confidential and stay **outside the repo**, in the folder set by `config.DATA_DIR` (or the
`MIA_DATA_DIR` environment variable).

| Key | File | Used for |
|---|---|---|
| engagement | SC Engagement List | one row per placement: staffer × client, start and end dates |
| seat_churn | Seats Churn (OPERATIONAL) | exit reasons |
| mystaff | CONFIDENTIAL Mystaff (sheet MyStaff) | industry, office address (region and country), Active and Internal flags, CRM Company ID |
| staffcentral | StaffCentral | each staffer's department, JP Category and designation |

The local data folder is `Desktop\Projects\Client Propensity\Data`.

To refresh the data, drop the new exports into the data folder, update the file names in `config.RAW_FILES`, and
rerun.

## Key definitions

- **Department / role group:** StaffCentral `Department (All)`, with Executive Services split by JP Category.
  - Where JP Category is blank, it is inferred from Designation when staff with the same designation mostly share
    one category. This was about 90% correct on held-out staff, and the inferred rows are flagged in
    `role_group_source`.
  - StaffCentral is a snapshot of each person's current department.
- **New-client growth:** reach and hold 5+ seats within 365 days (clients that launched with 1–4 staff), and 10+ seats
  within 730 days (launched below 10). A milestone counts only if it is held for 30 days. 20 seats isn't modelled:
  too few clients have reached it.
- **Seat growth (existing clients):** more seats 12 months from now than today (net, so backfills don't count).
- **Branching:** the first hire in a department that was not part of the launch team (the first 30 days).
- **Likely next department:** what clients with the same departments added next: share, and lift (share ÷ that
  department's usual share).
- **Why:** the traits that push a score up most compared with a typical client.
- **Bands:** Low, Medium and High are thirds of historical clients by cross-validated score. The workbook's
  "Model checks" sheet shows what actually happened in each band.
- **Client accounts:** `CSTREENGAGE`, `CLOUDSTAFF`, internal Hub teams and MyStaff `Internal = Yes` accounts are
  excluded.

## Dashboard extract

`<date>_Propensity_Extract.xlsx` is written by step 5b and lines this analysis up with the Account Priority Dashboard
(`Marketing Intelligence/`). The xlsx and its two CSVs are also copied to the dashboard's local data folder
(`config.DASHBOARD_FEED_DIR`), so the dashboard reads them from its own folder. The dashboard pipeline doesn't read them
yet (proof of concept). Read the CSV with `dtype={"shortcode": str}`.

| Sheet | One row per | Join to the dashboard on |
|---|---|---|
| `propensity_accounts` | active MyStaff client (the dashboard's Organic Growth set: Active = Yes, not a test account) | `account_id` = `MS-<shortcode>` |
| `prospect_profiles` | industry group × country, scored as a brand-new client (starting department unknown, launch 1–2 staff) | `profile_key` = `industry|country`. The dashboard's `region` maps to country via `region_to_country` |
| `industry_levels` | industry group: its sector, client count, and the level the models use (sector for groups under 30 clients) | `industry` |
| `region_to_country` | region code | `region` |
| `column_dictionary` | extract column: meaning and dashboard counterpart | – |
| `run_info` | model version, as-of date, source files and extract dates, AUCs, band cut-offs | – |

`propensity_accounts` is deliberately narrow: `account_id`, `shortcode`, and the seat and department metrics. No other
company identifiers or descriptive columns; the dashboard keeps its own (both sides use the same 18-group industry
taxonomy). The model version and as-of date are in `run_info`. The scores are separate `fit_*` columns, kept apart from
the dashboard's `priority_score`:

- seats: `seats_current` (≈ `cs_staff_current`), `seats_added_6m_gross` (≈ `seats_added_6m`), `seats_change_6m_net`,
  and `fit_seat_growth_*`, `fit_seat_vs_peers`, `fit_seat_why`
- departments: `fit_dept_expand_*`, `fit_dept_vs_peers`, `fit_dept_why`, `likely_next_dept` (share and lift),
  `likely_next_dept_by_lift`
- new clients only: `fit_growth_*` (5 seats in 1 year) and `fit_reach_10_*` (10 seats in 2 years), each with a `_why`
- `fit_coverage`: why a client has no score

Which seat growth figure to use, what the `*_why` columns mean, and a known industry mismatch in the dashboard's current MyStaff
file are in [DOCUMENTATION.md](DOCUMENTATION.md) Part 3.

The full column list is in the extract's `column_dictionary` sheet and in [DOCUMENTATION.md](DOCUMENTATION.md).

## Confidentiality

- The workbook and the extract list clients and scores, so they're saved in the local data folder
  (`config.OUTPUT_DIR`, which defaults to `config.DATA_DIR`; override with `MIA_OUTPUT_DIR`), outside the repo. The
  extract's copy goes to the dashboard's local data folder (`config.DASHBOARD_FEED_DIR`), also outside the repo.
- The notebook is saved with its outputs cleared. Clear them again (*Clear All Outputs*) before committing.
