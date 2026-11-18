# Churn warning signs: exec one-pager

A single HTML page for executives with three parts:

- **Warning signs:** the one-pager. It shows which signs come before a client churns, ranked, and which pairs of signs are much stronger together. It covers three segments (`SEGMENTS` in the notebook's 2.0):
  - clients with 5+ staff that churn by 20%+
  - clients with 5+ staff that churn to 0
  - clients with 1–4 staff that churn to 0

  The 5+ churn-to-0 segment has no model, because its exits are too few. Its pairs chart is replaced by a note when no pair is clearly stronger together.
- **Data dictionary:** traces every code on the charts to its definition. Each indicator (A1, P2, L1, ...) is a test on a feature, each feature is built from timeline columns, and each column comes from a source file. Clicking a bar or a code jumps to its row.
- **Method & QA:** how each number is worked out, and a reconciliation from every exit to the seats counted as churn.

The numbers come from `Churn Analysis/churn_analysis_raw.ipynb`, Part 2: sections 2.4, 2.4b and 2.11, and the export cell at the end.

- Output: `Desktop/Projects/Churn Analysis/Dashboards/<YYYY-MM-DD>_Churn_Warning_Signs.html`, saved **locally, never in the repo** (the repo's `Churn Analysis/outputs/` and `data/` are gitignored). It opens by double-click, and the data is embedded in the page.
- Fonts, icons and Chart.js load from public CDNs. No data is sent anywhere.
- The page holds results only: rates, ratios and counts, with no client names or shortcodes. It is still internal. Do not share it outside Cloudstaff.

## Files

| File | What it does |
|---|---|
| `dashboard_template.html` | The page: layout, charts, dictionary tables and method notes. Edit this to change the page. |
| `verify_onepager.py` | Checks the exported data before building. Every code traces to the dictionary, the ratios tie out, and the reconciliation adds up. It must end with `OVERALL: PASS`. |
| `Dashboards/data/churn_warning_signs.json` (local) | The data the page is built from, written by the notebook's export cell. |

## How to refresh

1. **Update the source files** in `Desktop\Projects\Churn Analysis\Data\`: the Churn Analysis workbook, `PB-4108.xlsx`, `NCNS.xlsx`, `Tardiness.xlsx`, `Absences.xlsx` and `Late Payments.xlsx`.
2. **Run the whole notebook** `Churn Analysis/churn_analysis_raw.ipynb`, from its own folder. The last cell, "Export: exec one-pager", writes `churn_warning_signs.json` to `Desktop/Projects/Churn Analysis/Dashboards/data/`.
3. **From the repo root, check the data, then build and check both pages (saved locally):**
   ```
   .venv/Scripts/python.exe "Churn Analysis/work/build_dashboards.py"
   ```
   It runs `verify_onepager.py` (must end with `OVERALL: PASS`), builds the page into `Desktop/Projects/Churn Analysis/Dashboards/`, checks every page for errors, then does the same for the outlook dashboard. It stops at the first failure.

## Settings that change the page

All of these are in the notebook:

| Setting | Where | Effect |
|---|---|---|
| `OUTCOME_EXCLUDE` | 2.0 | Exit reasons that are not counted as churn. Currently `exit_client_business_reasons`. |
| `HIGH_CHURN` | 2.0 | Churn threshold for clients with 5+ staff. Currently 20% of seats. |
| `SEGMENTS` | 2.0 | The segments shown: each is a size band plus an outcome (`high_churn` or `full_exit_next_3m`). |
| `MIN_EVENT_MONTHS`, `MIN_PAIR_MONTHS`, `MIN_EVENT_CHURNED` | 2.0, 2.4, 2.4b | Minimum client-months (and churned client-months) before a sign or a pair is rated; otherwise it shows as "too few to tell". |
| `MAX_PREVALENCE` | 2.11 | A sign present in more than this share of client-months is the normal state, so it is left out of the two-signs charts. |
| `SIGNS` | 2.11 | Which signs appear on the ranked charts, with their plain names. |
| `INDICATORS`, `FEATURE_TRACE` | Export cell | Codes, plain definitions and the feature-to-column map shown on the dictionary page. |
