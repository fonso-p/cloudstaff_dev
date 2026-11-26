# cloudstaff_dev

Cloudstaff Data & Analytics projects. Code and documentation only: client and staff data never live in the repo.

## Layout

| Folder | What it is |
|---|---|
| [`src/cloudstaff_dev/`](src/cloudstaff_dev/) | The shared Python package (installed in the repo's `.venv`, so any notebook or script can `import cloudstaff_dev`) |
| ├ `common/` | Used by every project: `paths.py` (where every file lives), `company_keys.py` (company names, domains, Companies House numbers), `industry.py` (industry groups), `jp_titles.py`, `roles.py`, `env.py` (API keys) |
| ├ `signals/` | Collectors that work for any company list: news (`news/`), careers pages and Adzuna (`jobs/`), Companies House, PSC, CQC, Find a Tender, charities (`registers/`), sector news (`segments/`), article text (`reader/`). CLI: `python -m cloudstaff_dev.signals` |
| ├ `leads/` | Lead lists: prepare → collect → grade → page, the same code for every list. Each list is a folder, `Marketing Intelligence/lead_lists/<name>/` (`list.toml` + hand-kept CSVs). CLI: `python -m cloudstaff_dev.leads` |
| ├ `scoring/` | The Priority Score (`priority.py`), shared by the Account Priority notebook and lead grading |
| └ `dashboards/` | One builder for the Marketing Intelligence pages (`build.py`) and their templates |
| [`Marketing Intelligence/`](Marketing%20Intelligence/README.md) | Account Priority Dashboard (notebook, rules) and lead lists (per-list hand-kept CSVs, grading docs) |
| [`News Scraper/`](News%20Scraper/README.md) | Documentation and accuracy checks (`eval/`) for `cloudstaff_dev.signals` |
| `Client Propensity/`, `Churn Analysis/`, `client_growth_project/`, `Disengagement/`, `Lickimat/`, `Client Extraction (CS Jobs)/`, `Adhoc/` | Other projects (each has its own README / CLAUDE.md) |
| [`references/`](references/README.md) | Shared reference data (industry mapping, JP categories) |
| `reference_code/` | Notebooks and scripts kept for reference. `company_keys.py` and `JP_titles_cat_cleaning/jp_titles.py` are now shims that re-export `cloudstaff_dev.common` |
| `tests/` | Unit tests: `.venv/Scripts/python.exe -m unittest discover -s tests -t .` |

## Where data lives (`src/cloudstaff_dev/common/paths.py`)

| Root | Path | What |
|---|---|---|
| `PROJECTS` | OneDrive `Desktop/Projects` (override: `CS_PROJECTS_DIR`) | What people open and share: each project's inputs, outputs and built dashboards |
| `LOCAL` | `~/cloudstaff_data` (override: `CS_LOCAL_DIR`) | Not synced: public register downloads (`cache/registers`, ~3.6 GB), model caches, SQLite databases (`work/`) |

Marketing Intelligence's folder (`Projects/Marketing Intelligence Priority/`):

```
inputs/       written by people or other projects   apollo/<region>/, hubspot/, mystaff/, propensity/ (Client Propensity's extract)
outputs/      written only by MI code                 account_priority/, lead_grades/<list>/, collected/<list>/, segments/, industry_trends/
dashboards/   built HTML pages, dated                 EMEA_Lead_Grades/, Account_Priority/
archive/      kept for reference, read by nothing     experiments/, mock/
```

API keys go in the repo-root `.env` (git-ignored; see `.env.example`).

## Setup

`uv sync` installs every dependency group and the package itself (editable). Playwright's browser, once:
`.venv/Scripts/python -m playwright install chromium`.
