# Client growth project (code package)

This folder holds the code for three Cloudstaff Data & Analytics pieces of work:

- **Client growth dashboard:** a single HTML page showing where and when clients grow, by region, division, industry, size and lifecycle stage.
- **Early-signal prediction:** a machine-learning analysis of what in a client's first 90 days predicts reaching 5 seats, 10 seats, and continued growth. It is backtested year by year.
- **ICP growth potential:** a profile of the accounts that grow fastest.

Owner: Jo Bert (Jobs) Olinares, Data & Analytics.

The data is confidential, and none of it is in this package. The notebooks are included with their outputs cleared. To run anything you need the source files listed below, from Jobs or the system owners. Keep them on your own machine. Do not upload them or send them to any external service.

## What is inside

| Folder | What it is |
|---|---|
| `work/client_growth_dashboard/` | `prep.py` (cleans the data), `dashboard_template.html` (the dashboard), `build_dashboard.py` (writes the HTML), `build_page_guide.py` (one-page guide), QA scripts |
| `work/early_signal_prediction/` | `plan.md` (approved method), `esp_data.py` (features and targets), `esp_models.py` (models, backtest, metrics), `make_notebook.py`, `build_early_signal_prediction.py` (Excel workbook), `reconcile.py` |
| `work/icp_growth_potential/` | `icp_prep.py` (role matching, shared by all three), `build_icp_growth_potential.py`, `plan.md` |
| `notebooks/` | `early_signal_prediction.ipynb`, `icp_growth_potential.ipynb` |
| `.claude/skills/` | helper scripts the builds import (Excel builder, QA, statistics) and Cloudstaff design files (colours, logos). This folder is hidden on Mac: press Cmd+Shift+. in Finder to see it |
| `qa/` | QA, review and cross-check reports |
| `requirements.txt` | Python packages |

## 1. Add the data files

Put each file at exactly this path, with exactly this name, inside this folder:

| Path | Source |
|---|---|
| `data/Organic rate/SC Engagement List2026-09-29 11_25_26.xlsx` | StaffCentral engagement list |
| `data/Organic rate/mystaff 1005 v2.xlsx` | MyStaff client list (sheets "MyStaff (2)" and "Region Reference") |
| `data/raw/manager_movements/mystaff client list.xlsx` | older MyStaff client list (region fallback) |
| `data/raw/monika_incremental_seats/2026 New Monthly Billed Report.xlsx` | billed report (role titles) |
| `Marketing/SC Engagement List2026-10-07 07_48_09.xlsx` | engagement list used by the ICP analysis only |

For a newer extract, change the file names at the top of `work/client_growth_dashboard/prep.py` (`STAFF_SRC`, `CLIENT_SRC`) and `work/icp_growth_potential/icp_prep.py`.

## 2. Set up Python (once)

You need Python 3.11 or later. In a terminal opened in this folder:

```
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

You also need:

- **Mac only (LightGBM):** run `brew install libomp`. If you use conda instead: `conda install -c conda-forge llvm-openmp`.
- **For the Excel workbooks:** Microsoft Excel or LibreOffice. The build recalculates the formulas for its QA check, and without one of them the QA check fails.
- **For the dashboard QA scripts only:** Google Chrome (`qa_full.py` and `check_page.py`).

## 3. Run, in this order, from this folder

```
python work/client_growth_dashboard/prep.py               # cleans data, writes data/*.csv and .json
python work/client_growth_dashboard/build_dashboard.py    # writes outputs/html/..._Client_Growth_Dashboard.html
python work/client_growth_dashboard/build_page_guide.py   # one-page guide (HTML and PDF)
python work/client_growth_dashboard/qa_full.py            # optional: full dashboard QA
jupyter nbconvert --to notebook --execute --inplace notebooks/early_signal_prediction.ipynb
```

`prep.py` must run first, because the ML notebook reads the client list it writes. The ML notebook takes about 5 minutes. It writes charts to `outputs/charts/`, exports to `outputs/csv/`, and the workbook to `outputs/excel/`.

## 4. Open the notebooks in VS Code

1. Open this folder in VS Code (File > Open Folder). Install the Python and Jupyter extensions if asked.
2. Open the notebook from `notebooks/`.
3. Click Select Kernel (top right) and choose the `.venv` environment.
4. Click Run All. Each step has a short explanation above it.
