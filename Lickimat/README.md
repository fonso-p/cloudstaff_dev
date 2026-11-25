# Lickimat replenishment mock

A read-only dashboard that ranks Amazon FBA SKUs (UK, US, AU) for restocking. It is one working view: summary tiles, a chart panel that is hidden by default, and the full list filtered by market, status and exception flag. The list shows our restock recommendation next to the Amazon recommendation and Mich's. The Rules and QA pages sit alongside it. This is a mock for internal review (Lee, Marcial, Mich) before it goes to Ramin. Every rule setting is an assumption until confirmed.

**Handing off or rebuilding?** Start with [HANDOFF.md](HANDOFF.md): the full spec (sources, pipeline, rules, flags, checks, acceptance numbers, open items). The code here is the reference implementation.

**Next change (warehouse stock and other-channel demand):** [CHANGE_warehouse_stock.md](CHANGE_warehouse_stock.md). Its mock data is made by `mock_warehouse.py` and written to the Desktop folder `Warehouse change (mock)/data/`, never to the repo.

## Where things live

| What | Where |
|---|---|
| Raw client files (not in the repo) | `~/Desktop/Projects/Client/Lickimat/`: `INVENTORY_RECOMMENDATION2.xlsx`, `LICKIMAT TABLE .xlsx` |
| Built JSON and HTML (not in the repo) | `~/Desktop/Projects/Client/Lickimat/Dashboards/` |
| Rules and their settings | `rules.py`: change values here only |
| Data engineering (load, harmonise, SKU map, join, flags, QA counts) | `prep.py` |
| Independent check against the raw Excel | `verify.py` |
| Mock warehouse stock and other demand for the next change (with expected results and test cases) | `mock_warehouse.py` |
| Processed data as CSVs for a handoff (written to `Dashboards/handoff_data/`) | `export_handoff.py` |
| Page template (Cloudstaff house format) | `work/dashboard_template.html` |

## Refresh

Drop new exports into the Desktop folder with the same file and sheet names. Then run these from the repo root, in order:

```
.venv/Scripts/python.exe Lickimat/prep.py
.venv/Scripts/python.exe Lickimat/verify.py            # optional: [SRC_DIR] [OUT_DIR]
.venv/Scripts/python.exe Lickimat/export_handoff.py    # optional: processed-data CSVs for a handoff
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

## Known issues and open items

See [HANDOFF.md](HANDOFF.md) sections 10 and 11. The open items are also in `rules.TO_CONFIRM` and on the dashboard's Rules & assumptions page.
