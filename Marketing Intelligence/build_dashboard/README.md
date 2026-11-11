# build_dashboard

Builds the **Account Priority Dashboard**, a single HTML file that opens by double-click, from the processed data.

## Where this sits in the pipeline

```
 1. format data/format_priority_data.ipynb                 2. build_dashboard/build_dashboard.py
    HubSpot + MyStaff raw exports (local)                     processed JSON (local)
    → merge, format, score, route                             → Account Priority Dashboard
    → processed data, saved LOCALLY:                          → <date>_Account_Priority_Dashboard[_MOCK_SIGNALS].html, saved LOCALLY
        priority_company_info_combined*.xlsx
        account_priority_dashboard_data*.json   ───────────►
```

Raw data, processed data and the built dashboard all stay in the local data folder
(`~/Desktop/Projects/Marketing Intelligence Priority/Data`), never in the repo. Business rules and assumptions for part 1 are in [`../format data/BUSINESS_RULES.md`](../format%20data/BUSINESS_RULES.md).
The code guide for both parts, including the data contract below, is [`../format data/PIPELINE.md`](../format%20data/PIPELINE.md).

## Run

1. In `format data/format_priority_data.ipynb`, set `SAVE_OUTPUT = True` and run it (or call `run_pipeline(save=True)`).
   It writes `account_priority_dashboard_data[_MOCK_SIGNALS].json` to the local data folder.
2. Build the page, from the `Marketing Intelligence` folder:

```bash
../.venv/Scripts/python.exe build_dashboard/build_dashboard.py
```

By default it uses the newest `account_priority_dashboard_data*.json` in the local data folder and writes
`<today>_Account_Priority_Dashboard.html` to the same local folder. While the signals are mock, the file name ends in `_MOCK_SIGNALS`.
Options: `--data <json>` and `--out <html>` (`{date}` = today).

Optional check (headless Chrome/Edge, each page must print `errors: []`):

```bash
../.venv/Scripts/python.exe ../.claude/skills/cs-dashboard/scripts/check_page.py "<local data folder>/<file>.html"
```

## Files

| File | What it is |
|---|---|
| `build_dashboard.py` | Checks the processed JSON has everything the page reads, embeds it with the tokens and logo, and writes the HTML |
| `dashboard_template.html` | The page: layout, charts, filters and text. Copied from `work/account_priority_dashboard/dashboard_template.html` (the mock dashboard). Mock-only wording was replaced, and the warning banner now comes from the data (`meta.notice`) |
| `assets/tokens.css`, `assets/cloudstaff-logo-landscape.svg` | Cloudstaff design tokens and logo, copied from the `cs-dashboard` skill |

## Data contract

The page reads one JSON object: `meta`, `settings`, `qa` and `rows`, fully described in [`PIPELINE.md` §6](../format%20data/PIPELINE.md). It is produced by stage 11 (`build_dashboard_data()`) of the
notebook. `build_dashboard.py` checks the required `meta` keys, settings keys and row fields before building. It stops with a clear message if the
notebook's output and this template ever drift apart.

## Confidentiality

The built HTML embeds **every account row** (client names, scores, owners), so it is written to the local data folder,
outside the repo. Don't point `--out` inside the repo. As a safety net, the repo's root `.gitignore` still excludes
`Marketing Intelligence/outputs/html/*.html`.
