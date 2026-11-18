# Churn outlook dashboard

A single HTML page that turns the churn models into portfolio-level views for management:

- **Seats at risk:** expected seats lost in the next 3 months, with a forecast-vs-actual track record and breakdowns by region, client type and client age.
- **Where risk comes from:** which groups of factors push the forecast up, measured after allowing for the others.
- **Retention capacity:** how much of the seats lost a monthly review list of the top N clients would have reached.
- **Client scores:** each client's seat-churn score on the holdout months (outcome known) and today, with every factor's contribution to the score (SHAP, in percentage points).
- **Method & QA:** definitions, backtest accuracy, every group, and row counts.

The first three pages are totals and shares, because a single client's score is noisy (AUC 0.6–0.7) but totals across many clients are steady. The **Client scores** page lists individual clients, but only as anonymised IDs (`C-` plus a salted hash of the shortcode, the same every month).

The numbers come from `Churn Analysis/churn_analysis_raw.ipynb`, sections 2.12 and 2.13 and the "Export: outlook dashboard" cell.

- Output: `Desktop/Projects/Churn Analysis/Dashboards/<YYYY-MM-DD>_Churn_Outlook.html`, saved **locally, never in the repo** (the repo's `Churn Analysis/outputs/` and `data/` are gitignored). It opens by double-click, and the data is embedded in the page.
- The page has no client names or shortcodes, but it is still internal. Do not share it outside Cloudstaff.
- **The ID key stays local.** Section 2.13 writes to the MI data folder (`Desktop/Projects/Churn Analysis/Data`), never to the repo:
  - `client_id_salt.txt`: the salt behind the IDs. Keep it, or every ID changes on the next run.
  - `client_scores_holdout.csv` and `client_scores_today.csv`: every scored client, with shortcode, ID, score, top 3 reasons and outcome.

## How to refresh

1. **Run the whole notebook** `Churn Analysis/churn_analysis_raw.ipynb` from its own folder. Section 2.12 refits the models month by month for the backtest, which takes a minute or two. The export cell writes `churn_outlook.json` to `Desktop/Projects/Churn Analysis/Dashboards/data/`.
2. **From the repo root:**
   ```
   .venv/Scripts/python.exe "Churn Analysis/work/build_dashboards.py"
   ```
   It verifies the data (`verify_outlook.py` must end with `OVERALL: PASS`), builds the page into the local dashboards folder, checks every page for errors, and builds the local copy with shortcodes. It does the same for the warning-signs page, and stops at the first failure.

## Settings (notebook, section 2.12)

| Setting | Effect |
|---|---|
| `BACKTEST_FROM` | First month of the out-of-time backtest. Each month is scored by models trained on snapshots whose outcome was known by then. |
| `REVIEW_N` | List sizes compared on the capacity page. |
| `DRIVER_MONTHS` (12) | How many recent months of snapshots the driver breakdown uses. Today's snapshot alone would miss attendance, because the absence log ends in Feb 2026. |
| `SCORE_TOP_N` (100, section 2.13) | Clients listed on the Client scores page per size band per month. The tiles and the tenths chart use every holdout client-month. |
| `MIN_GROUP` (export cell) | Groups with fewer clients are shown in grey as too small to compare. |

## Known limits

- **The forecast runs about 9% low** across the backtest, so treat it as a floor.
- **Attendance data is incomplete for recent months:** absences end in Feb 2026, and NCNS and tardiness in Sep 2026. Today's forecast leans on the other factors.
- **Driver shares describe what the model leans on, not causes.**

## Local copy with real shortcodes

The repo page shows clients only as anonymised IDs. For your own use, a copy that also shows each client's shortcode can be built **outside the repo**:

```
.venv/Scripts/python.exe "Churn Analysis/work/churn_outlook/add_shortcodes.py"
```

It reads the ID → shortcode key files that section 2.13 writes to the MI data folder, and writes `Desktop/Projects/Churn Analysis/Dashboards/<date>_Churn_Outlook_with_shortcodes.html` (its data file goes in `data/`). `build_dashboards.py` runs it automatically. The page says it shows real shortcodes. Keep it local: do not share it or copy it into the repo. Run it after the notebook and `verify_outlook.py`, so the IDs match.
