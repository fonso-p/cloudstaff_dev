# Lickimat replenishment mock

A read-only dashboard that ranks Amazon FBA SKUs (UK, US, AU) for restocking. It shows our rule-based quantity next to Amazon's and Mich's recommendations, plus exceptions, trends across snapshots and SKU economics. This is a mock for internal review (Lee, Marcial, Mich) before it goes to Ramin. Every rule setting is an assumption until confirmed.

## Where things live

| What | Where |
|---|---|
| Raw client files (not in the repo) | `~/Desktop/Projects/Client/Lickimat/`: `INVENTORY_RECOMMENDATION2.xlsx`, `LICKIMAT TABLE .xlsx` |
| Built JSON and HTML (not in the repo) | `~/Desktop/Projects/Client/Lickimat/Dashboards/` |
| Rules and their settings | `rules.py`: change values here only |
| Data engineering (load, harmonise, SKU map, join, flags, QA counts) | `prep.py` |
| Independent check against the raw Excel | `verify.py` |
| Page template (Cloudstaff house format) | `work/dashboard_template.html` |

## Refresh

Drop new exports into the Desktop folder with the same file and sheet names. Then run these from the repo root, in order:

```
.venv/Scripts/python.exe Lickimat/prep.py
.venv/Scripts/python.exe Lickimat/verify.py
.venv/Scripts/python.exe .claude/skills/cs-dashboard/scripts/build_dashboard.py --template Lickimat/work/dashboard_template.html --data "%USERPROFILE%/Desktop/Projects/Client/Lickimat/Dashboards/lickimat_replenishment.json" --out "%USERPROFILE%/Desktop/Projects/Client/Lickimat/Dashboards/{date}_Lickimat_Replenishment_Dashboard.html"
.venv/Scripts/python.exe .claude/skills/cs-dashboard/scripts/check_page.py "<built html>"
```

`verify.py` must print only PASS lines, and `check_page.py` must print `errors: []` for every page.

## Pipeline steps (`prep.py`)

1. **Load** each market's Amazon inventory export, Mich's dated `<market> RECO` sheet and the `<market> Report` economics sheet.
2. **Harmonise** the market-specific column names to one schema. The output is one row per market × snapshot × SKU.
3. **SKU map**: the base code is the leading LM product code. SKUs without one are listed on the QA page.
4. **Join**: economics on SKU, then on ASIN when the ASIN appears only once in the report. Mich's reco on SKU and date, retrying with day and month swapped when a date matches no snapshot. The previous snapshot is joined in for the inbound and stuck-shipment checks.
5. **Rules and flags** from `rules.py`.
6. **QA counts**: every drop and fix is counted and shown on the QA page.
7. **Write** one JSON file.

When API access arrives, only the loaders in step 1 need to change.

## Known rule issues (noted, not yet fixed)

1. **Dead SKUs get topped up.** A SKU with no sales in 90 days and 1–4 units left goes through the slow-seller rule. It is marked Below target and topped up to 10. In the 30 Oct snapshot that was 36 SKUs and 273 units. Proposed fix: recommend 0 and give these SKUs a "No recent sales" status.
2. **"Out of stock" ignores inbound.** A SKU with nothing available but units inbound is still marked Out of stock (6 SKUs in the latest snapshot). The reason text mentions the inbound units. Proposed fix: an "Out of stock, inbound" status, or rank these below SKUs with nothing on the way.

## Open items to confirm

The current values are in `rules.TO_CONFIRM` and on the dashboard's Rules & assumptions page.
