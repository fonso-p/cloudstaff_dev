---
name: cs-dashboard
description: Build or restyle a Cloudstaff Data & Analytics HTML dashboard in the house format used by the Client Growth Dashboard. That format is a single offline HTML file with the data embedded, Cloudstaff design tokens and logo, a left sidebar nav, a shared filter bar, KPI tiles, blue-header chart cards, a "Numbers behind this chart" table under every chart, and Stats/QA pages. Use it whenever the user asks for a dashboard, an HTML report page, or a "page like the client growth dashboard" from analysis data such as a notebook, CSV or pandas output. Also use it to make an existing dashboard match that format. Do not use it for Excel workbooks, slide decks, or Power BI.
---

# Cloudstaff dashboard format

The reference implementation is `client_growth_project/work/client_growth_dashboard/` (`dashboard_template.html`, `build_dashboard.py`, `check_page.py`, and the README). This skill packages its layout, style and build pipeline so other analyses can produce dashboards that look and behave the same.

## Files

| File | Use |
|---|---|
| `assets/template.html` | Starter page: the full house CSS, shell, filter bar, KPI tiles, chart cards, insight cards, sortable list, Stats and QA pages, plus every helper (`draw`, `chartData`, `table`, `download`, `kpiTiles`, `fmt`, `pct`, `pfmt`, `wilson`, ...). Copy it into the project and edit the copy. |
| `assets/tokens.css` | Cloudstaff design tokens, inlined at build time. Never hard-code colours or spacing in CSS. Use `var(--...)`. |
| `assets/cloudstaff-logo-landscape.svg` | Logo, inlined at build time (full colour on a white sidebar; never the reversed logo). |
| `assets/example_data.json` | Example of the data shape the template expects. |
| `scripts/build_dashboard.py` | Inlines tokens, logo and JSON into the template and writes one HTML file. |
| `scripts/check_page.py` | Opens the built page in headless Chrome or Edge, visits every page, prints JS errors, and takes screenshots. |

Run the scripts with the repo's venv: `.venv/Scripts/python.exe` on Windows (`python` is not on PATH here).

## Workflow

1. **Prep in Python, not in the page.** Write a `prep.py` (or a notebook cell) that cleans the data and writes one JSON file:
   ```json
   {"meta": {"title": "...", "subtitle": "...", "source": "StaffCentral engagement list",
             "extract": "2026-09-29", "first_month": "2020-01", "last_month": "2026-09",
             "generated": "2026-11-06T10:00:00"},
    "qa":   [{"step": "Source rows", "rows": 12345}, ...],
    "rows": [{...one object per unit of analysis...}]}
   ```
   Convert NaN to `null` (the build refuses NaN). Store per-record arrays (e.g. monthly values) instead of pre-aggregated tables, so the page can recompute every number when a filter changes.
2. **Copy the template** to `work/<project>/dashboard_template.html`. Rename the nav pages, the filters (`fillSelect` + `filt` + `applyFilt`) and the renderers (`rOverview`, ...) to fit the analysis. Keep the helpers and CSS unchanged unless there is a reason.
3. **Build:**
   `python .claude/skills/cs-dashboard/scripts/build_dashboard.py --template work/<project>/dashboard_template.html --data data/<project>.json --out "outputs/html/{date}_<Name>_Dashboard.html"`
4. **Check:** `python .claude/skills/cs-dashboard/scripts/check_page.py <built.html>` must print `errors: []` for every page. Then take a screenshot of each new page (`--page <id> --screenshot x.png --height 1400`) and look at it before handing it over.
5. If numbers are computed in the page (tests, medians), check them against pandas or scipy in a `verify_*.py` script, as `verify_stats.py` does in the reference project.

## Layout anatomy (keep this structure)

- **`.shell`**: a 16rem sticky white sidebar and the main column. At 1100px and narrower it stacks into one column.
- **Sidebar (`.side`)**, top to bottom:
  - the logo with a one-line `<small>` subtitle
  - mono uppercase `.nav-label` sections: "Workspace" for the analysis pages, "Method" for Stats & method and QA & data checks
  - `.nav a[data-page]` links with Font Awesome 6 solid icons; the active link is soft blue
  - a `.side-box` of export buttons (`.btn-teal` / `.btn-blue`)
  - a `.side-foot` naming the data source, the extract date and the build date
- **Topbar**: breadcrumb `Title > Page`, a date chip ("Data to 29 Sept 2026"), and a search box that jumps to the list page.
- **Page head**: an `h1` with the page title, and a subline with the record count, the date range and the active filters, recalculated on every render.
- **Filter bar (`.filters`)**: one white panel holding one `.frow` per group of settings, each with a mono `.frow-label` ("Which clients", "How growth is measured"), plus a Reset button. Hide a row, or the whole bar, on pages it does not affect, and say so in `.frow-note`. Every page recalculates on any change.
- **Pages**: one `<section class="page" id="p-<id>">` per nav item. `go(id)` switches pages, and only the visible page draws.
- **Page content, in order**:
  - an optional `.info` line (what the page answers, which filters apply)
  - `.kpis` tiles
  - `.grid.g2` pairs of cards, or `.g3` for 3:2
  - full-width cards for tables
  - a `.note` under each chart

## Components

- **KPI tile**: `kpiTiles([[colourClass, faIcon, label, value, subline], ...])`.
  - Use the colours in this order: `k-blue`, `k-teal`, `k-yellow`, `k-pink`, `k-purple`, `k-indigo`.
  - The subline gives the context: the denominator, a 95% range from `wilson()`, or the definition.
- **Card**: `.card > .card-head (h3 + span) + .card-body`.
  - The blue header bar's `h3` says what the chart shows, in plain words.
  - The right-hand `span` says the unit or the split, e.g. "share of clients" or "by region · grey = under 20, do not rank".
- **Chart**: `<div class="chart"><canvas id="cX"></canvas></div>`, or `.chart.tall` (380px) for long category lists. Always draw it with `draw('cX', cfg)`, never `new Chart`. `draw` destroys the old chart and adds the **Numbers behind this chart** table with a CSV button. For share axes, use `scales: {y: pctAxis}` so the table shows %.
- **Table**: `table(el, cols, rows, {sortable, onSort})`.
  - `cols` entries are `{k, label, n: 1 for numeric (right-aligned mono), f: formatter}`.
  - `row._small = true` greys out the row.
  - Wrap the table in `.tbl-wrap`, which scrolls with sticky headers. Add `.sticky1` for a frozen first column and `.nowrap` for wide lists.
- **Callouts**: `.info` (soft blue, scope and definitions), `.warn` (soft yellow, caveats), and badges `.b-ok`, `.b-warn`, `.b-no`, `.b-blue`.
- **Insight card**: `insightCard(title, sentence, evidence, linkPage)`. Each card has one sentence built from the numbers, an evidence badge (test, p, n), and a link to the detail page.
- **Stats block**: `.stat` with an `h4` (test name), a `.reading` (plain-English result), and a `.note` (statistic, df, p via `pfmt`, n per group).
- **Record list**: a sortable, searchable table of every record in the current filters, with CSV export. The reference shows it under every analysis page; at minimum, give it its own page.

## Colour rules

- `PALETTE` is the brand order. Charts read in order use blue `#007AFF` (series 1), teal `#00AB9C` (series 2), yellow, pink, indigo, purple, orange, cyan, green, slate.
- Give a category the **same colour on every chart**. Fix the mapping by name, e.g. `REG_COLOUR = {APAC: '#007AFF', AMER: '#00AB9C', OPTI: '#AA67FD', Unknown: '#50505C'}`.
- For up / stay / down splits, use teal for up, `GREY` (`#C9D2E1`) for stayed, and pink for down. For starts vs churn, use blue for starts, pink for churn, and a teal line for net.
- Show small groups (n < 20) in `GREY` in charts and `_small` in tables, and say so in the card-head span.
- Chart.js defaults: Manrope font, axis text `#737C90`, grid lines `#DCE3EE`, 12px legend boxes, and `maintainAspectRatio: false`. All of these are set in the template.

## Content rules (these matter as much as the look)

- **Plain English.** Write titles and notes as a reader would say them: "Share of clients hitting the threshold, by custom division", not "hit_rate by div". Give every chart a `.note` saying what is counted and how to read it.
- **No hard-coded dates.** Read every date the page shows (extract date, first and last month, last complete year, partial-month warning) from `D.meta`, so a refresh needs no template edits.
- **Honest statistics.**
  - Say "differs", "highest" or "lowest" only when a test gives p < 0.05.
  - Leave groups under 20 out of tests (`MIN_TEST`), and name only groups of 30+ (`MIN_NAME`).
  - Prefer medians when a few large records skew the mean, and say so.
  - Call findings associations, not causes.
- **Traceability.**
  - The QA page reconciles source rows to analysis rows and lists every exclusion with its count.
  - The Stats & method page defines every term and test.
- **Confidential data.**
  - The data is embedded in the HTML, and only fonts, icons and Chart.js load from CDNs (Google Fonts, cdnjs).
  - Never add analytics or other external calls, and never upload the built file or the data to an external service.
  - Write outputs to `outputs/html/<YYYY-MM-DD>_<Name>_Dashboard.html`.

## Before handing over

- `check_page.py` prints `errors: []` on every page.
- You have looked at a screenshot of every page:
  - no overlapping labels
  - cards in a row aligned at the top
  - the right-hand header text doesn't wrap badly
- Every chart has its numbers table, and all filters change it (or the page says which filters don't apply).
- The headline numbers tie to the prep output (total records, totals), checked in a script.
- A README next to the template says how to refresh: which source files, which settings to change, and which commands to run in what order.
