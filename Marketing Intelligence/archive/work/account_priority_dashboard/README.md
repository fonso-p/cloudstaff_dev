# Account priority dashboard (Cloudstaff format)

This is the mock Account Priority Dashboard (`reference materials/mock/Account_Priority_Dashboard_Mock.html`) rebuilt in the Cloudstaff Data & Analytics dashboard format (the `cs-dashboard` skill). The content is the same, but the layout is new:

- a sidebar nav
- a filter bar
- KPI tiles
- blue-header cards
- Chart.js charts, each with a "Numbers behind this chart" table
- a QA page

All data is **fictional mock data**. Do not mix it with real client data.

- Output: `outputs/html/<YYYY-MM-DD>_Account_Priority_Dashboard.html`. It opens by double-click and the data is embedded in the page.
- Inputs (read only, never edited):
  - `reference materials/data/accounts.csv` (400 accounts)
  - `reference materials/data/scoring_settings.json`
- Work-side mock inputs, made by `make_mock_data.py` (all fictional):
  - `accounts_extra.csv`: 400 more accounts made with the same rules and workbook formulas, doubling the dataset to 800
  - `account_roles.csv`: one owner role per account (Marketing, SDR or BDM). SDR owns New Logo only.
  - `seat_growth.csv`: seats added in the last 6 months, for every Organic Growth account

## Change from the workbook: Act now bonus

Accounts with an Act now trigger get **+15 points**. The bonus is added after the industry nudge, and the score is capped at 100. Tier and list order are then recalculated from the new score.

- The bonus is set in `score_adjustments.json`. Set it to 0 to get the workbook's scores back.
- **Points are round numbers** (multiples of 5, set in `score_adjustments.json`): Website 40 and News and jobs 40 on both lists; Diamond referral and Competitor client 10 each (New Logo); Seat growth 20 (Organic Growth). Unknown signals use 25% of the maximum. `prep.py` first checks that the workbook's own settings reproduce `accounts.csv` exactly, then rescores every account from the raw columns with these values.
- **Seat growth (Organic Growth only)** reads `seat_growth.csv` (`account_id`, `seats_added_6m`; blank = unknown). The values are mock. Replace the file with the real extract and re-run `prep.py`. Bands: 0 seats = 0%, 1-5 = 25%, 6-10 = 50%, 11 or more = 100% of the 20 points.
- The workbook's original score and tier are kept: they appear in the worked example, the CSV export and the QA page.
- **Lists follow the owner role.** The filter bar has Role (Marketing, SDR, BDM) and List (New Logo, Organic Growth); SDR has New Logo only, so there are five lists. The workbook's BDM / SDR / AM routing is still computed and checked, but no longer decides the list.

## Files

| File | What it does |
|---|---|
| `prep.py` | Reads the scored accounts and settings, applies the Act now bonus, recalculates tier and order, and adds the display fields: Why chips, profile line and filter labels. It writes `data/account_priority_dashboard.json`. Triggers and routing come unchanged from the workbook. |
| `score_adjustments.json` | Settings that replace or add to the workbook's: round point values, the 25% baseline, seat growth bands, `hot_bonus` (15) and `hot_bonus_diamond` (7.5). |
| `make_mock_data.py` | Makes `accounts_extra.csv`, `account_roles.csv` and `seat_growth.csv` (fixed seeds, so the output is the same every run). |
| `dashboard_template.html` | The page: layout, charts, filters and text. All weights and thresholds shown are read from the settings, not typed in. |
| `verify.py` | Opens the built page in headless Chrome or Edge and checks the KPIs, score spread, Act now reasons and list order at 9 role, list and filter settings against an independent pandas rescore of `accounts.csv` + `accounts_extra.csv`. It must end with `OVERALL: PASS`. |

## Pages

| Page | Contents | Same as the mock's |
|---|---|---|
| Priorities | Takeaway line, 4 KPIs, score spread by tier, Act now reasons, priority list with chips, and CSV export | Priorities tab |
| Data glossary | 6 indicator cards and 4 "what you will see" cards, with the "Unknown today" shares calculated from the data | Data glossary tab |
| How the score works | Formula, five steps, points per signal, news strength and recency tables, worked example | How the score works tab |
| QA & data checks | Where the 800 accounts go (five role lists), unknown data by indicator, tiers by list | New (part of the house format) |

The filters (list, industry, employee band, search) work as in the mock:

- Changing the list resets industry and employee band.
- The search filters the priority list.
- Pages can be linked directly with `#glossary`, `#method` or `#qa`.

## Build (run from the `Marketing Intelligence` folder)

```bash
../.venv/Scripts/python.exe work/account_priority_dashboard/prep.py
../.venv/Scripts/python.exe ../.claude/skills/cs-dashboard/scripts/build_dashboard.py --template work/account_priority_dashboard/dashboard_template.html --data data/account_priority_dashboard.json --out "outputs/html/{date}_Account_Priority_Dashboard.html"
../.venv/Scripts/python.exe ../.claude/skills/cs-dashboard/scripts/check_page.py outputs/html/<date>_Account_Priority_Dashboard.html   # every page: errors: []
../.venv/Scripts/python.exe work/account_priority_dashboard/verify.py                                                                  # OVERALL: PASS
```

## When the scoring or data changes

1. Regenerate the workbook and export `accounts.csv` as described in `reference materials/CLAUDE.md`. If the settings changed, update `scoring_settings.json` too.
2. If the as-of date changed, update `AS_OF` at the top of `prep.py`. It is the workbook's as-of date for news recency.
3. Run the four commands above.

The display rules live at the top of `prep.py`:

- strength dots: ●●● at 66% or more, ●●○ at 33% or more
- "Growing industry" at a trend of 0.7 or more
- the employee band order
