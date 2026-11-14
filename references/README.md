# References

Shared reference data and rules for every project in this repo. No client or staff data.

| Folder | What it is | Maintained by |
|---|---|---|
| [`mystaff_industry/`](mystaff_industry/README.md) | Industry taxonomy: HubSpot / MyStaff industry labels → 18 industry groups under 6 sectors, with a Python loader | Edit `industry_mapping.csv` by hand |
| [`staffcentral_jp_category/`](staffcentral_jp_category/README.md) | Departments: StaffCentral JP Category, the category merges, and how a blank category is imputed from JP Title, Designation and the old Department | Written by `Client Propensity/run_pipeline.py` on every full run; rules in its `config.py` |
