# Build the Account Priority Dashboard

Builds the **Account Priority Dashboard**, a single HTML file that opens by double-click, from the processed data.
The builder is `src/cloudstaff_dev/dashboards/build.py` (was `Marketing Intelligence/build_dashboard/build_dashboard.py`); it builds the EMEA Lead Grades page too.

## Where this sits in the pipeline

```
 1. account_priority/format_priority_data.ipynb            2. python -m cloudstaff_dev.dashboards.build account_priority
    HubSpot + MyStaff raw exports (<MI>/inputs/)              processed JSON (<MI>/outputs/account_priority/)
    → merge, format, score, route                             → Account Priority Dashboard
    → processed data, saved to <MI>/outputs/account_priority/: → <MI>/dashboards/Account_Priority/<date>_Account_Priority_Dashboard[_MOCK_SIGNALS].html
        priority_company_info_combined*.xlsx
        account_priority_dashboard_data*.json   ───────────►
```

Raw data, processed data and the built dashboard all stay outside the repo, under `<MI>` = OneDrive
`Desktop/Projects/Marketing Intelligence Priority` (folders from `cloudstaff_dev.common.paths`). Business rules and assumptions for part 1 are in [`BUSINESS_RULES.md`](BUSINESS_RULES.md).
The code guide for both parts, including the data contract below, is [`PIPELINE.md`](PIPELINE.md).

## Run

1. In `Marketing Intelligence/account_priority/format_priority_data.ipynb`, set `SAVE_OUTPUT = True` and run it (or call `run_pipeline(save=True)`).
   It writes `account_priority_dashboard_data[_MOCK_SIGNALS].json` to `<MI>/outputs/account_priority/`.
2. Build the page, from any folder (`python` = the repo's `.venv/Scripts/python.exe`):

```bash
python -m cloudstaff_dev.dashboards.build account_priority [--check]
```

By default it uses the newest `account_priority_dashboard_data*.json` in `<MI>/outputs/account_priority/` and writes
`<today>_Account_Priority_Dashboard.html` to `<MI>/dashboards/Account_Priority/`. While the signals are mock, the file name ends in `_MOCK_SIGNALS`.
Options: `--data <json>` and `--out <html>` (`{date}` = today).

`--check` (optional) opens the result in headless Chrome/Edge with the `cs-dashboard` skill's `check_page.py`; each page must print `errors: []`.

## Files

| File | What it is |
|---|---|
| `src/cloudstaff_dev/dashboards/build.py` | Checks the processed JSON has everything the page reads, embeds it with the tokens and logo, and writes the HTML |
| `src/cloudstaff_dev/dashboards/templates/account_priority.html` (was `build_dashboard/dashboard_template.html`) | The page: layout, charts, filters and text. Copied from `work/account_priority_dashboard/dashboard_template.html` (the mock dashboard, now `Marketing Intelligence/archive/work/account_priority_dashboard/`). Mock-only wording was replaced, and the warning banner now comes from the data (`meta.notice`) |
| `.claude/skills/cs-dashboard/assets/tokens.css`, `cloudstaff-logo-landscape.svg` | Cloudstaff design tokens and logo, read straight from the `cs-dashboard` skill (the old `build_dashboard/assets/` copies were identical and are gone) |

## Data contract

The page reads one JSON object: `meta`, `settings`, `qa` and `rows`, fully described in [`PIPELINE.md` §6](PIPELINE.md). It is produced by stage 11 (`build_dashboard_data()`) of the
notebook. `dashboards/build.py` checks the required `meta` keys, settings keys and row fields before building. It stops with a clear message if the
notebook's output and this template ever drift apart.

## Confidentiality

The built HTML embeds **every account row** (client names, scores, owners), so it is written to `<MI>/dashboards/Account_Priority/`,
outside the repo. Don't point `--out` inside the repo. As a safety net, the repo's root `.gitignore` still excludes
`Marketing Intelligence/outputs/html/*.html`.
