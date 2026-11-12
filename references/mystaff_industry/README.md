# Industry taxonomy: 18 industry groups under 6 sectors

The shared industry bucketing for every project in this repo. It turns the raw industry labels in HubSpot and MyStaff into
**18 industry groups**, each under one of **6 sectors**.

| File | What it is |
|---|---|
| [`industry_mapping.csv`](industry_mapping.csv) | **The single source of truth.** One row per raw value: which group and sector it goes to, or why it stays blank. Edit this file to change the bucketing |
| [`mystaff_industry.py`](mystaff_industry.py) | Loads the CSV, checks it, and applies the rules below (`classify`, `classify_frame`). Exposes the same constants the projects use today (`INDUSTRY_GROUPS`, `INDUSTRY_SECTOR`, `INDUSTRY_MAP`, `ROLLUP_MAP`, `UNCLASSIFIED_INDUSTRY`, `PLACEHOLDER_ROLLUP`) |
| `README.md` (this file) | What the bucketing does, and why |

It has no client data, so it's safe to keep in git.

## Who uses it

The same rules are currently written out by hand in two places. Both match this file exactly (checked 2026-11-12: every constant identical, and `classify()` gives the same group on all 2,874 MyStaff rows of the Analysis pipeline and on 1,326 of 1,327 Account Priority Dashboard rows; see *Known gaps*):

* `Marketing Intelligence/format data/format_priority_data.ipynb` §0b (Account Priority Dashboard), rules in `BUSINESS_RULES.md` §6
* `Client Propensity/mi_pipeline/mappings.py`

Neither imports this file yet. Until they do, a change here must be copied to both.

## How to use it

Python, from any file in the repo. Add this folder to the import path, then import `mystaff_industry`:

```python
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]   # repo root; adjust the depth to where your file sits
sys.path.insert(0, str(REPO / "references" / "mystaff_industry"))

from mystaff_industry import classify, classify_frame, INDUSTRY_SECTOR

classify("Computer Software")                    # ('Technology', 'Technology & Media', 'Industry Hubspot')
classify("-", rollup="Accounting Services")      # ('Accounting', 'Financial & Professional Services', 'Industry Roll Up')

clients = classify_frame(mystaff, hubspot_col="Industry Hubspot", rollup_col="Industry Roll Up")
prospects = classify_frame(hubspot_report, hubspot_col="Industry", rollup_col=None)
# adds industry_group, industry_sector, industry_source
```

Anything else (Excel, Power BI, SQL): load `industry_mapping.csv` as a lookup table on `source_field` + `raw_value`.

## The rules

1. **HubSpot's industry label first.** HubSpot `Industry` (prospects) or MyStaff `Industry Hubspot` (clients) is looked up in the rows with `source_field = Industry Hubspot`. Both use HubSpot's own industry list.
2. **Cloudstaff's roll-up as a fallback.** If the HubSpot label is blank, unclassified or not in the file, MyStaff `Industry Roll Up` is looked up in the rows with `source_field = Industry Roll Up`. HubSpot records have no roll-up, so they stop at step 1.
3. **Otherwise blank.** Unclassified values, placeholder roll-ups and values not in the file give no group.
4. **Sector** is the parent of the group (fixed per group).
5. Values are trimmed and `&amp;` is read as `&` before the lookup. Matching is case-sensitive.

`industry_source` (from `classify_frame`) records which field supplied the group.

**Small groups.** Energy & Environment and Non-profit & Public Sector have few clients. Models should use the **sector** for groups below a minimum size (the propensity models use 30 client accounts).

## Columns in `industry_mapping.csv`

| Column | Meaning |
|---|---|
| `source_field` | `Industry Hubspot` (HubSpot's list, used first) or `Industry Roll Up` (Cloudstaff's roll-up, fallback only) |
| `raw_value` | The label exactly as the source writes it |
| `status` | `mapped` (has a group), `unclassified` (HubSpot label that means "unknown") or `placeholder` (roll-up that carries no industry) |
| `industry_group` | One of the 18 groups; blank unless `mapped` |
| `industry_sector` | The group's sector; must be the same on every row of a group |
| `borderline_alternative` | Another group that was considered (see *Borderline assignments*) |
| `note` | Why a value is unclassified or a placeholder, or "Fallback only" for roll-ups |

Today: 104 HubSpot labels mapped, 3 unclassified, 59 roll-ups mapped, 6 placeholders (172 rows).

## The 18 groups

| Sector | Industry group | HubSpot labels | Examples |
|---|---|---|---|
| Technology & Media | Technology | 10 | Information Technology and Services, Computer Software, Internet, Telecommunications |
| Technology & Media | Marketing, Media & Creative | 12 | Marketing and Advertising, Online Media, Publishing, Graphic Design |
| Property & Construction | Real Estate | 2 | Real Estate, Commercial Real Estate |
| Property & Construction | Construction & Engineering | 5 | Construction, Building Materials, Civil Engineering, Architecture & Planning |
| Financial & Professional Services | Accounting | 1 | Accounting |
| Financial & Professional Services | Financial Services | 6 | Financial Services, Banking, Investment Management, Mortgage Broker |
| Financial & Professional Services | Insurance | 1 | Insurance |
| Financial & Professional Services | Legal | 2 | Legal Services, Law Practice |
| Financial & Professional Services | Professional Services | 8 | Management Consulting, Human Resources, Staffing and Recruiting, Research |
| Consumer, Hospitality & Services | Retail & Consumer Goods | 14 | Retail, Ecommerce, Wholesale, Food & Beverages |
| Consumer, Hospitality & Services | Hospitality, Travel & Leisure | 5 | Hospitality, Leisure, Travel & Tourism, Restaurants, Sports |
| Consumer, Hospitality & Services | Business & Consumer Services | 4 | Facilities Services, Security and Investigations, Consumer Services |
| Consumer, Hospitality & Services | Non-profit & Public Sector | 3 | Non-Profit Organization Management, Civic & Social Organization, Public Safety |
| Health & Education | Healthcare & Wellness | 8 | Hospital & Health Care, Medical Practice, Pharmaceuticals, Veterinary |
| Health & Education | Education & Training | 5 | Education Management, E-Learning, Higher Education |
| Industrial, Logistics & Energy | Manufacturing & Industrial | 8 | Machinery, Automotive, Chemicals, Mining & Metals |
| Industrial, Logistics & Energy | Transport & Logistics | 6 | Logistics and Supply Chain, Transportation/Trucking/Railroad, Import and Export |
| Industrial, Logistics & Energy | Energy & Environment | 4 | Oil & Energy, Utilities, Renewables & Environment |

The full list of labels per group is in the CSV.

## Why this bucketing

* HubSpot's industry list is used by both sources: HubSpot `Industry` (84 values) and MyStaff `Industry Hubspot` (96 values), 106 distinct in total.
* The values are concentrated: six cover over half of tagged rows, and more than 60 have five rows or fewer, so they are grouped.
* Accounting, Insurance, Legal and Real Estate keep their own groups because they are distinct Cloudstaff verticals.
* Cloudstaff's `Industry Roll Up` (64 values) is **not** the taxonomy, only the fallback. It exists only in MyStaff, has near-duplicates, and has questionable assignments (e.g. Insurance → Comprehensive Financial Services, Legal Services → Professional Advisory).
* `Outsourcing/Offshoring` counts as unknown: 26 of the 27 MyStaff clients with it have the roll-up `CLOUDSTAFF`, i.e. Cloudstaff's own industry stamped on by default.
* Roll-ups `CLOUDSTAFF`, `Test Record - No Category` and `Cloudstaff Test Account` sit on real clients (some with 100+ staff). The clients are kept; only the label is ignored.

## Borderline assignments

Each is a one-cell change in the CSV (`industry_group`, and `industry_sector` if the sector changes).

| HubSpot label | Assigned to | Alternative |
|---|---|---|
| Mechanical or Industrial Engineering | Construction & Engineering | Manufacturing & Industrial |
| Health, Wellness and Fitness | Healthcare & Wellness | Hospitality, Travel & Leisure |
| Food & Beverages, Wine and Spirits | Retail & Consumer Goods | Hospitality, Travel & Leisure |
| Import and Export | Transport & Logistics | Retail & Consumer Goods (wholesale) |
| Professional Training & Coaching | Education & Training | Professional Services |
| Consumer Services | Business & Consumer Services | MyStaff's roll-up calls all 9 such clients Personal Care |
| Printing | Marketing, Media & Creative | Manufacturing & Industrial |

## Changing the bucketing

| To | Do |
|---|---|
| Map a new raw label | Add a row: `source_field`, `raw_value` exactly as the source writes it, `status = mapped`, group and sector |
| Move a label to another group | Change `industry_group` (and `industry_sector`) on its row |
| Treat a label as unknown | `status = unclassified` (HubSpot) or `placeholder` (roll-up), group and sector blank, with a `note` |
| Add, rename or merge a group | Change every row of that group. Models and dashboards that list the groups (e.g. the dashboard's `INDUSTRY_TREND`) need the same change |

`mystaff_industry.py` refuses to load the file (with a message) if a HubSpot label is in two groups, a group sits under two sectors, a roll-up points to a group that has no HubSpot labels, or a `mapped` row has no group. `unrecognised(values)` lists labels in your data that aren't in the file yet.

Record the change in the projects' rule docs, and rerun both pipelines so their outputs agree.

## Known gaps (2026-11-12)

**Labels not in the file.** They currently fall to blank. In the MyStaff 2026-10-05 extract (all clients, active and inactive), 237 clients have a label that isn't in the file. 113 of them end up with no industry (66 active), 73 of those only because the roll-up is `0`.

* HubSpot labels, mostly HubSpot's newer names for existing values: Business Supplies and Equipment (7), Business Consulting and Services (7), Recreational Facilities and Services (2), Furniture (2), and one each of Paper & Forest Products, SaaS, Medical Practices, Educational Services, Architecture and Planning, Public Relations and Communications, Warehousing, Oil and Gas, Writing and Editing, Music.
* Roll-ups: `0` (73, should probably be a placeholder), Industrials (12), Consumer Discretionary (3), Financials (3), Communication Services (2), and about 25 more with one client each.

Several are near-duplicates of mapped labels (`Architecture and Planning` vs `Architecture & Planning`, `Medical Practices` vs `Medical Practice`, `Oil and Gas`). Adding them is the quickest gain.

**One dashboard row differs.** A client whose `industry_raw` is the roll-up `Other` with `industry_source = MyStaff Industry Roll Up` shows `Technology` on the dashboard; `classify()` gives blank. `Other` isn't a mapped roll-up, so the dashboard's value probably came from its merged HubSpot record without `industry_raw` / `industry_source` being updated. Worth a look in the dashboard notebook.
