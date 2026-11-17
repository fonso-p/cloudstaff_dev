# Churn warning signs: exec one-pager

A single HTML page for executives with three parts:

- **Warning signs:** the one-pager. It shows which signs come before a client churns, ranked, and which pairs of signs are much stronger together. It is split into clients with 5+ staff and clients with 1–4 staff.
- **Data dictionary:** traces every code on the charts to its definition. Each indicator (A1, P2, L1, ...) is a test on a feature, each feature is built from timeline columns, and each column comes from a source file. Clicking a bar or a code jumps to its row.
- **Method & QA:** how each number is worked out, and a reconciliation from every exit to the seats counted as churn.

The numbers come from `Churn Analysis/churn_analysis_raw.ipynb`, Part 2: sections 2.4, 2.4b and 2.11, and the export cell at the end.

- Output: `Churn Analysis/outputs/html/<YYYY-MM-DD>_Churn_Warning_Signs.html`. It opens by double-click, and the data is embedded in the page.
- Fonts, icons and Chart.js load from public CDNs. No data is sent anywhere.
- The page holds results only: rates, ratios and counts, with no client names or shortcodes. It is still internal. Do not share it outside Cloudstaff.

## Files

| File | What it does |
|---|---|
| `dashboard_template.html` | The page: layout, charts, dictionary tables and method notes. Edit this to change the page. |
| `verify_onepager.py` | Checks the exported data before building. Every code traces to the dictionary, the ratios tie out, and the reconciliation adds up. It must end with `OVERALL: PASS`. |
| `../../data/churn_warning_signs.json` | The data the page is built from, written by the notebook's last cell. |

## How to refresh

1. **Update the source files** in `Desktop\Projects\Churn Analysis\Data\`: the Churn Analysis workbook, `PB-4108.xlsx`, `NCNS.xlsx`, `Tardiness.xlsx`, `Absences.xlsx` and `Late Payments.xlsx`.
2. **Run the whole notebook** `Churn Analysis/churn_analysis_raw.ipynb`, from its own folder. The last cell, "Export: exec one-pager", writes `Churn Analysis/data/churn_warning_signs.json`.
3. **From the repo root, check the data, then build and check the page:**
   ```
   .venv/Scripts/python.exe "Churn Analysis/work/churn_warning_signs/verify_onepager.py"
   .venv/Scripts/python.exe .claude/skills/cs-dashboard/scripts/build_dashboard.py --template "Churn Analysis/work/churn_warning_signs/dashboard_template.html" --data "Churn Analysis/data/churn_warning_signs.json" --out "Churn Analysis/outputs/html/{date}_Churn_Warning_Signs.html"
   .venv/Scripts/python.exe .claude/skills/cs-dashboard/scripts/check_page.py "Churn Analysis/outputs/html/<date>_Churn_Warning_Signs.html"
   ```
   The last command must print `errors: []` for every page.

## Settings that change the page

All of these are in the notebook:

| Setting | Where | Effect |
|---|---|---|
| `OUTCOME_EXCLUDE` | 2.0 | Exit reasons that are not counted as churn. Currently `exit_client_business_reasons`. |
| `HIGH_CHURN` | 2.0 | Churn threshold for clients with 5+ staff. Currently 20% of seats. |
| `MIN_EVENT_MONTHS`, `MIN_PAIR_MONTHS` | 2.4, 2.4b | Minimum client-months before a sign or a pair is rated. |
| `MAX_PREVALENCE` | 2.11 | A sign present in more than this share of client-months is the normal state, so it is left out of the two-signs charts. |
| `SIGNS` | 2.11 | Which signs appear on the ranked charts, with their plain names. |
| `INDICATORS`, `FEATURE_TRACE` | Export cell | Codes, plain definitions and the feature-to-column map shown on the dictionary page. |
