# Client growth dashboard

A single HTML page showing where and when clients grow, by net seats (staff starts minus staff churn). It covers clients whose first staff started from January 2020 onwards. The page is split by region (APAC, AMER with EMEA folded in, OPTI), Custom Division, industry roll-up, size and lifecycle stage, and has seasonality, account profile, statistics and QA pages.

- Output: `outputs/html/<YYYY-MM-DD>_Client_Growth_Dashboard.html`. It opens by double-click and the data is embedded in the page.
- The fonts, icons and Chart.js load from public CDNs (Google Fonts, cdnjs). No data is sent anywhere.
- The page and the files in `data/` hold confidential client data. Do not upload or email them outside Cloudstaff.

## Files in this folder

| File | What it does |
|---|---|
| `prep.py` | Reads the source files, applies the exclusions, builds the monthly per-client table, client profile and QA lists, and prints a summary. |
| `build_dashboard.py` | Puts the data, the design tokens and the logo into `dashboard_template.html` and writes the dashboard. |
| `dashboard_template.html` | The page itself (layout, charts, filters, statistics). Edit this to change the dashboard. |
| `verify_stats.py` | Checks the dashboard's statistics (Kruskal-Wallis, chi-square) against scipy for several filter settings. |
| `check_page.py` | Opens the dashboard in headless Chrome and lists any JavaScript errors. It can also save a screenshot. |
| `page_guide.html`, `build_page_guide.py` | One-page guide to the pages and filters. `python work/client_growth_dashboard/build_page_guide.py` writes it to `outputs/html/` and `outputs/pdf/` and stops if it no longer fits on one A4 page. |
| `qa_full.py` | Full QA: re-derives every file from the raw engagement list and MyStaff, then checks every number on every page against an independent recount at 3 filter settings. It must end with OVERALL: PASS. |
| `phase4_checks.py` | Traces 5 clients from the raw rows to the monthly table to the dashboard, and ties the dashboard totals to the prep outputs. |

## Path to 5 seats page (the research question)

Compares accounts that reached 5+ seats quickly, reached 5 more slowly, never reached 5 and churned. The four groups match the High-Growth Account Profile:
- **Fast to 5:** 5 staff at the same time within 183 days of the first start.
- **Slow to 5:** reached 5 later than that.
- **Not yet at 5, still active:** never reached 5 and still has staff.
- **Churned without reaching 5:** never reached 5 and has no staff today.

The page shows:
- **Groups:** group sizes by region (APAC and AMER separately).
- **Profile of each group:** starting seats, seats at day 90, time to 5, peak and current seats, retention, tenure, client age, second function, and same / new / unknown function adds.
- **What predicts reaching 5 within 12 months:** by region, starting seats, initial function, industry and custom division, each tested with chi-square.
- **How quickly:** time-to-5 bands, with a test across regions.
- **What happens after 5:** still with staff, still at 5+, went on to 10, and staff 12 / 24 / 36 months after reaching 5. Retention is compared with clients that never reached 5, among clients aged 24+ months.
- **Seat path:** median staff at months 1 to 36 for each group.

The "Path to 5 seats" filter applies the group to every page and to the client list. That list is the interview shortlist.

Not available in the source files: company size, and gross margin or account economics.

## Headcount reconciliation

The QA page lists every stint on the books on the extract date, by where it sits in the analysis and by Category. The dashboard covers only clients whose first staff started from January 2020. Clients that started earlier, Stafflink (MyStaff Region = "VAR"), the disengaged staff pool and internal units are shown there, so the total ties back to the engagement list.

## Insights page

Plain-English findings that are recalculated whenever a filter changes:
- how many clients grow
- where in the client's life growth happens
- differences by region, size, custom division and industry
- hiring seasons, including divisions with their own season
- churn against hiring
- starting seats and reaching 5

Rules built into the page:
- A finding says "differs", "highest" or "lowest" only when a test gives p < 0.05.
- Groups under 20 are left out of tests, and only groups of 30+ are named.
- Every card shows its evidence (test, p-value, n) and links to the page with the detail.

The tests behind the cards are listed on the Stats page and checked against scipy by `verify_stats.py`.

## Tables on every page

- **Numbers behind this chart:** under every chart, a table of the exact values plotted, with a CSV button. It follows the filters.
- **Client movement: added, churned and net:** under every analysis page, every client in the current filters, sortable, searchable and exportable to CSV.
  - By lifecycle stage: launch (month 1) added, churned and staff, then added, churned, net and staff at the end of each stage (months 1-3 after launch, 4-6, 7-12, 13-24, 25-36, 37+), with totals and segment movement.
  - By window: for the chosen window length, each window's staff at start, added, churned, net (green = hit the threshold) and staff at end.

## Refresh with new data

1. Save the new files in `data/` as received. Do not edit or re-save the originals:
   - the SC Engagement List export (StaffCentral)
   - the MyStaff client list (the sheet with Region, Custom_Division (Hubspot), Industry Roll Up, Internal (Yes / No), Active, Total Staff)
2. Open `prep.py` and update the settings block near the top:
   - `STAFF_SRC`: path to the new engagement list
   - `CLIENT_SRC` and `CLIENT_SHEET`: path and sheet name of the new MyStaff list
   - `EXTRACT`: the engagement list extract date
   - `LAST_MONTH`: the month of the extract. It is shown as a part month.
3. Role titles (for initial function and second function) come from the monthly billed report, through the helper `work/icp_growth_potential/icp_prep.py`. Open it and update:
   - `BILLED_SRC`: path to the newest billed report
   - `ROLE_TABS`: add the new month's tab, for example `"October 2026"`. A tab that is missing from the list is not read, so new staff would show as Unknown function.
4. Run from the project root:
   ```bash
   python work/client_growth_dashboard/prep.py
   ```
   Read the printed summary and check:
   - the line `Reconciliation: ... True` with `recount mismatches: 0`
   - the exclusion counts, which must add up to the source row count
   - any new region, division or industry values (new internal or test codes may need adding to `EXCL_REGION`, `EXCL_DIVISION` or `NAMED_INTERNAL`)
   - `Unknown region`: clients in the engagement list but not in MyStaff. They are kept and listed on the QA page; ask for them to be added to MyStaff.
   - the role match rate (about 84% on the September 2026 data)
5. Build the page:
   ```bash
   python work/client_growth_dashboard/build_dashboard.py
   ```
6. Check it:
   ```bash
   python work/client_growth_dashboard/check_page.py      # must print: errors: []
   python work/client_growth_dashboard/verify_stats.py    # must end with PASS
   python work/client_growth_dashboard/phase4_checks.py   # must end with OVERALL: PASS
   python work/client_growth_dashboard/qa_full.py         # must end with OVERALL: PASS (about 10 minutes)
   ```
7. Open the new file in `outputs/html/` in a browser.

The page reads every date it shows from the data (first and last month, extract date, last complete calendar year), so nothing in `dashboard_template.html` needs editing for a refresh. A part year selected in the year filter is tested only on the months it has.

## Definitions used

- **Seat move:** every engagement row on a real client counts.
  - A start is the month of the Engagement Date.
  - A churn is the month of the Disengagement Date. A move to CSTREENGAGE counts as churn.
  - A return to the same client counts as a new start.
- **Active at month end:** the stint started on or before the month end and has no end date, or ends after the month end.
- **Client start month:** the month of the client's first valid Engagement Date in the engagement list. MyStaff dates are used only to flag differences.
- **Window k:** months (k-1)N+1 to kN of the client's own life, where N is 3, 5, 6 or 12. Only complete windows are used.
  - Window net = staff at the window end minus staff at the end of the month before.
  - Window 1 measures growth after launch: from staff at the end of month 1 to staff at the end of month N (agreed 2026-10-10). The seats a client launched with are not growth. The Lifecycle "Months 1-3" stage works the same way.
  - Starting segment = staff at the end of the month before the window, or at the end of month 1 for window 1.
- **Hit:** window net seats at or above the chosen threshold (3, 5, 10 or 20).
- **Peak seats (any day):** the highest number of staff on the books on any single day. A stint counts on both its start and end dates, as in the High-Growth Account Profile analysis, so a handover day can add one. Time to 5 and time to 10 seats use the same daily count.
- **Status:**
  - Active with staff
  - Active, 0 staff (MyStaff Active = Yes, no staff in the engagement list today)
  - Inactive
- **Region:** taken from MyStaff, with EMEA folded into AMER. OPTI is its own region, and any client in an OPTI division (OPAU, OPUS, OPEM, OPTI) is counted as OPTI. Timezone is not used.
- **Exclusions** (each one is listed on the QA page and in `data/qa_excluded.csv`):
  - blank shortcode
  - CSTREENGAGE
  - single-row CSS test records
  - named internal Cloudstaff units
  - shortcodes where 50% or more of rows are Hub
  - MyStaff Internal = Yes
  - Region Internal, Test, "-" or VAR
  - Custom Division HUB, CS - INTERNAL, TEST ACCOUNT or NEWLY REGISTERED
  - industry Cloudstaff or Test Record
  - exact duplicate rows
  - clients that started before 2020
- **Client whose only stints end before they start:** no valid start month, so it is counted with the MyStaff clients never staffed (agreed 2026-10-10). Its rows are listed on the QA page under that reason (1 client, 1 row on the September 2026 data).
- **Clients not in MyStaff:** kept, with region "Unknown", and listed on the QA page (none on the September 2026 data).
- **Same name, different shortcodes:** kept as separate clients and listed on the QA page and in `data/qa_name_pairs.csv`.
- **Segment tests:** Kruskal-Wallis and chi-square across starting segments use 1-4, 5-10 and 10+ only. Windows that start with 0 staff are left out.
- **Company size:** not in the source files, so it is shown as "not available".

## Statistics

The statistics are computed in the page (no libraries) and checked against scipy by `verify_stats.py`:
- Kruskal-Wallis with tie correction.
- Chi-square test of independence, with the Yates correction for 2x2 tables as scipy does.
- Chi-square goodness of fit.

A difference is called only when p < 0.05. Any group with fewer than 20 is flagged.
