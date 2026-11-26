# Marketing Intelligence

Two dashboards, built from the shared package (`src/cloudstaff_dev`). This folder holds what is specific to them: the
notebook, the hand-kept rule files and the documentation. Data and built pages live in
`OneDrive/Desktop/Projects/Marketing Intelligence Priority/` (see the root README).

`python` below = the repo's `.venv/Scripts/python.exe`; every command runs from any folder.

## EMEA Lead Grades (and any other lead list)

| What | Where |
|---|---|
| Run a list end to end (collect → grade → page → check) | `python -m cloudstaff_dev.leads run apollo_emea` (`--from STEP`, `--only a,b`, `--skip a,b`, `--download` monthly, `--dry-run`) |
| Grade only / page only | `python -m cloudstaff_dev.leads grade apollo_emea` · `python -m cloudstaff_dev.leads build apollo_emea` |
| Industry trends page data (monthly) | `python -m cloudstaff_dev.leads trends --download`, then `build` |
| Everything specific to the list | [`lead_lists/apollo_emea/`](lead_lists/apollo_emea/): [`list.toml`](lead_lists/apollo_emea/list.toml) (settings, steps, team, target markets: sub-sectors and pitch, service lines, target codes) and the hand-kept CSVs (name overrides, manual events, event corrections, register reviews) |
| Grading rules, decisions and method | [`lead_grading/README.md`](lead_grading/README.md), [`lead_grading/PLAN.md`](lead_grading/PLAN.md) |
| How the signals are collected | [`lead_lists/apollo_emea/COLLECTING.md`](lead_lists/apollo_emea/COLLECTING.md), [`../News Scraper/README.md`](../News%20Scraper/README.md) |
| Code (the same for every list) | `src/cloudstaff_dev/leads/` (rules.py = general settings, config.py = loads a list, apollo.py, internal.py, events.py, enrich.py, collected.py, grade.py, export.py, pipeline.py) |
| Outputs | `<MI>/outputs/lead_grades/apollo_emea/`, page in `<MI>/dashboards/EMEA_Lead_Grades/` |

**A new lead list** (another region or source): copy the folder `lead_lists/apollo_emea/` to `lead_lists/<name>/`,
edit its `list.toml` (`name`, `title`, `inputs`, steps, and the `[markets."..."]` sections for its target markets),
empty the hand-kept CSVs, put the export in `<MI>/inputs/<inputs>/`, then `python -m cloudstaff_dev.leads run <name>`.
No code changes. Each list gets its own work folder, collected folder, grades and page, so lists can't read each
other's files or rules. A list can also have its own page template: put it in its folder and name it in `template`.

## Account Priority Dashboard

| What | Where |
|---|---|
| Part 1: merge, format and score HubSpot + MyStaff | [`account_priority/format_priority_data.ipynb`](account_priority/format_priority_data.ipynb) (`SAVE_OUTPUT = True` to write `<MI>/outputs/account_priority/`) |
| Part 2: build the page | `python -m cloudstaff_dev.dashboards.build account_priority --check` → `<MI>/dashboards/Account_Priority/` |
| Scoring settings and formulas (shared with lead grading) | `src/cloudstaff_dev/scoring/priority.py` |
| Rules and pipeline docs | [`account_priority/BUSINESS_RULES.md`](account_priority/BUSINESS_RULES.md), [`PIPELINE.md`](account_priority/PIPELINE.md), [`FIT_CARD_GUIDE.md`](account_priority/FIT_CARD_GUIDE.md), [`BUILD_DASHBOARD.md`](account_priority/BUILD_DASHBOARD.md) |
| Golden-test fixtures (mock, fictional) | [`account_priority/fixtures/`](account_priority/fixtures/) |

## archive/

The first mock build of the Account Priority Dashboard (`work/`) and the original mock workbook, proposal and
generator (`reference materials/`). Nothing reads them; kept for reference.
