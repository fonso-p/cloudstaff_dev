# Lickimat replenishment: handoff

For a developer rebuilding this in a new system. This file is the spec. The Python in this folder is a working reference implementation; you do not need to keep it, but your rebuild should produce the same numbers on the same inputs (see [Acceptance numbers](#9-acceptance-numbers)).

The future data feed is not known yet (Excel today, maybe the Amazon SP-API later). So the handoff includes the **processed data** too: the exact tables that populate the dashboard ([section 14](#14-processed-data-what-populates-the-dashboard)). You can build and test the dashboard on those tables first, then build the pipeline to produce the same tables from whatever feed arrives.

Status: **mock / proof of concept**, built 18–20 Nov 2026 on four Amazon exports. Rules are simple on purpose: the client's real rules are not known yet, so almost every setting is an assumption waiting for confirmation ([Open items](#10-open-items)).

---

## 1. What it is for

Lickimat sells on Amazon FBA in the UK, US and AU. Ramin (client owner) decides what to ship into Amazon. Mich (Amazon VA) currently sends him recommendations by hand, starting from Amazon's own "recommended units" number and adjusting it.

The tool answers, per SKU: **how many units to send to Amazon now, and which SKUs to deal with first.** It shows our recommendation beside Amazon's and Mich's so they can be compared.

Out of scope for now: warehouse (Trilanco / 3PL) stock, carton or pack sizes, purchase orders, forecasting, DE inventory (DE has economics only).

## 2. Requirements and decisions

| # | Requirement | From |
|---|---|---|
| R1 | Every SKU with **less than 4 weeks of stock cover** must get a recommended replenishment quantity above 0. | Ramin, via Mich (19 Nov 2026) |
| R2 | Markets UK, US, AU. | Internal decision |
| R3 | Read-only. Nobody edits recommendations in the tool. | Internal decision |
| R4 | Rules must be simple and visible to users in plain words (a Rules page), because they are still assumptions. | Internal decision |
| R5 | Every record dropped or fixed in loading is counted and shown (a QA page). | Internal decision |
| R6 | Client data is confidential. Raw files stay out of source control. The client's ITF master file is confidential and was not shared. | Client |

## 3. Source data

Two Excel workbooks from the client, plus two context documents. All arrive by hand today; the plan is to replace them with the Amazon SP-API later, so keep loading separate from the logic.

### 3.1 `INVENTORY_RECOMMENDATION2.xlsx`

**`<M> RAW DATA` (M = UK, US, AU).** Amazon's FBA inventory / restock report. Several exports are stacked in one sheet, separated by `snapshot-date`. Grain: one row per snapshot × SKU (no duplicates exist; drop them if they appear). Snapshots in the current file:

| Market | Snapshots |
|---|---|
| UK | 2026-09-10, 2026-10-13, 2026-10-18, 2026-10-30 |
| US | 2026-09-09, 2026-10-13, 2026-10-16, 2026-10-29 |
| AU | 2026-09-10, 2026-10-13, 2026-10-16, 2026-10-30 |

Column names differ by market. Map them to one schema (first column found wins):

| Field | Source column(s) | Notes |
|---|---|---|
| snap | `snapshot-date` | date |
| sku, asin, name | `sku`, `asin`, `product-name` | SKU kept exactly as given (case matters for joins) |
| avail | `available` | blank = 0 |
| inb | `inbound-quantity` | blank = 0; equals working + shipped + receiving |
| inb_ship | `inbound-shipped` | blank = 0 |
| unf | `unfulfillable-quantity` | blank = 0 |
| s7 / s30 / s90 | `units-shipped-t7/t30/t90` (UK, US); `units-shipped-last-7/30/90-days` (AU) | units sold; blank = 0 |
| price, sale_price, featured | `your-price`, `sales-price`, `featuredoffer-price` | used by the Price check flag |
| alert | `alert` | Amazon's Low traffic / Low conversion text |
| amz | `Recommended ship-in quantity` (UK, US); `recommended-order-quantity` (AU) | **Amazon recommendation** |
| aged | sum of `inv-age-181-to-270-days`, `inv-age-271-to-365-days`, `inv-age-366-to-455-days`, `inv-age-456-plus-days` (UK, US) or `inventory-age-181-to-270-days`, `inventory-age-271-to-365-days`, `inventory-age-365-plus-days` (AU) | units over 180 days |

The US export also contains Canada SKUs (ending `-CA`, 13 in the latest snapshot). They are kept under US.

**`<M> RECO`.** Mich's dated recommendation log. Header is on the second row. Columns used: `Date`, `SKU`, and the quantity in `Recommendation` (column K). Typed by hand, so:
- some dates have day and month swapped (e.g. 2026-10-09 meant 10 Sep). If a date matches no snapshot, swap day and month and retry; 70 UK rows are fixed this way.
- rows with no date, SKU or quantity are dropped; several rows for the same date + SKU are summed.
- rows whose SKU is not in that day's export are dropped and listed on the QA page (5 rows across markets).

Ignore the `UK`, `US`, `AU`, `AU1` working sheets: they repeat the RECO sheets without dates.

### 3.2 `LICKIMAT TABLE .xlsx`

**`<M> Report` (M = UK, US, AU, DE).** SKU economics per marketplace (Mich confirmed this is what it is). One row per SKU, no duplicates. Columns used (match names case-insensitively): `sku`, `asin`, `net sales revenue`, `net proceed total`, `net margin %`, `net units sold`. Window: 12 months (UK, AU, DE), 15 months (US), as stated in each `<M> Table` sheet title. Currency: the market's own (GBP, USD, AUD, EUR).

### 3.3 Context documents (read, not loaded)

`Amazon FBA Replenishment AI POC General Plan.docx` (11 Nov 2026) and `Lickimat Ecommerce - Mich.docx` (interview with Mich, 12 Nov 2026).

## 4. Pipeline

One run produces one dataset. Steps, in order:

1. **Load** the three sources per market.
2. **Harmonise** to the schema above. Blank unit counts = 0. Number each market's snapshots so 0 = latest (field `sr`).
3. **SKU map.** Base code = the leading LM product code: regex `^(LM[A-Z]*-[A-Z0-9]+|LM[A-Z]*\d[A-Z0-9]*)`, case-insensitive, on the upper-cased SKU. `LM3001GN-DR-FBA-UK → LM3001GN`, `LM-BTT-FBA-UK → LM-BTT`. No match = "unmapped" (bundles, `TESTING …` listings, new-item codes; 9 in the latest snapshot). Unmapped SKUs are kept.
4. **Join** (per market):
   - Economics on SKU; if no match, on ASIN, but only when that ASIN appears once in the report.
   - Mich's reco on snapshot date + SKU (after the date fix).
   - Previous snapshot of the same SKU, for `prev_inb`, `prev_ship`, `prev_snap`.
5. **Rules** (section 5) per row: weekly demand, cover, status, recommendation, reason text.
6. **Flags** (section 6) per row.
7. **Profit** (section 7) per row.
8. **QA counts** (section 8).
9. **Write** the output (one JSON file in the mock; a table or API in your system).

Known data quirks, all handled above: market-specific column names, stacked snapshots, day/month-swapped dates in Mich's log, blank `available` cells (148 in AU, mostly inactive listings), the same ASIN under several SKUs (labels or old vs new codes), and dog (`-DR`) and cat (`-CR`) versions sharing a base code.

## 5. Replenishment rules

Settings (all assumed except where noted):

| Setting | Value |
|---|---|
| Lead time | 4 weeks, every market |
| Buffer | 4 weeks, every market |
| Target cover | lead + buffer = 8 weeks |
| Cap | 26 weeks (Amazon aged-inventory fees start at 181 days) |
| Slow seller | under 1 unit a week |
| Slow seller reorder point / top-up | below 5 units → top up to 10 |
| Keep listing alive | 2 units |
| FX to GBP (ordering and charts only) | UK 1.0, US 0.8, AU 0.5 |

Per row:

```
weekly demand  = s30 / (30/7)
                 if avail <= 0: max(that, s90 / (90/7))        # an empty shelf must not look like no demand
stock          = avail + inb
cover (weeks)  = stock / weekly demand; NULL when demand is 0   # NULL is not 0: there is nothing to divide by

A. no sales in 90 days (s90 <= 0 and s30 <= 0):
     reco = max(0, ceil(2 - stock))
     status = "Keep listing alive" if reco > 0 else "No recent sales"

B. slow seller (weekly demand < 1):
     reco = 10 - stock if stock < 5 else 0
     status = "Out of stock"  if avail <= 0 and s90 > 0
              "Below target"  elif stock < 5
              "Excess"        elif cover > 26 and stock > 10
              "OK"            otherwise

C. everyone else:
     reco = max(0, ceil(8 × weekly demand − stock))
     status = "Out of stock"  if avail <= 0
              "Urgent"        elif cover < 4 (lead time)
              "Below target"  elif cover < 8 (target)
              "Excess"        elif cover > 26
              "OK"            otherwise
```

Notes:
- **R1 holds by construction:** cover < 4 means stock < 8 × demand in branch C, and stock < 4 units in branch B. Check it anyway (section 8).
- "Out of stock" ignores inbound. Two latest-snapshot SKUs are Out of stock with a recommendation of 0 because enough stock is already inbound. This is known issue K2.
- Loss-making SKUs are restocked like any other (brand presence keeps knockoffs off the listing); they are flagged, not demoted.
- Each row also carries a one-line reason, e.g. "Sells about 32 a week; 0 there = about 0 weeks. Target 8 weeks ≈ 252 units, so send 252."

Statuses, in priority order (the number is shown to users):

| # | Status | Meaning |
|---|---|---|
| 1 | Out of stock | none available, sold in the last 90 days |
| 2 | Urgent | cover under the lead time (4 weeks) |
| 3 | Below target | cover under the target (8 weeks) |
| 4 | OK | between target and cap |
| 5 | Excess | over the 26-week cap |
| 6 | Keep listing alive | no sales in 90 days, under 2 units: send up to 2 |
| 7 | No recent sales | no sales in 90 days, 2+ units there: no order |

Statuses 1–3 = "needs action".

**List order** (hidden; users see only the status number): status number ascending → profit at stake per week in GBP, with losses counted as 0, descending → cover ascending (NULL last) → weekly demand descending.

## 6. Exception flags

Shown as chips under the SKU. Exact conditions:

| Flag | Condition |
|---|---|
| Out of stock | status = Out of stock (not shown as a chip, the status already says it) |
| Unfulfillable units | unf > 0 |
| Aged stock | aged > 0 |
| Price check | featured present, price > 0, featured < price, and no sale price > 0 |
| Losing money | net proceeds < 0 and reco > 0 |
| Several SKUs on one ASIN | in the same snapshot, 2+ SKUs on the ASIN have avail + inb + s90 > 0 |
| Inbound not moving | inb_ship > 0, equal to the previous snapshot's inb_ship, and the snapshots are 10+ days apart |
| Amazon alert | alert text not blank |

## 7. Profit fields

Profit is used only to order SKUs and for two charts. It never changes a quantity.

```
profit per unit (ppu) = net proceeds / net units sold      (economics window)
                        if no economics match, or units <= 0: the market's median ppu, marked "est."
profit at stake /wk   = weekly demand × ppu                 (market currency)
pw_gbp                = profit at stake × FX_TO_GBP[market] (ordering and all-market charts only)
loss                  = net proceeds < 0
```

Money is otherwise never added across markets.

## 8. Checks (must pass on every refresh)

Reference implementation: `verify.py`, which re-reads the raw Excel independently of the pipeline. Rebuild these as automated tests:

1. Row count per market = raw rows.
2. Per market and snapshot: totals of avail, inb and s30 match the raw sheet.
3. Mich units: raw total = matched + dropped (dropped are listed in QA).
4. Every row's recommendation recomputed from the formulas in section 5.
5. Profit per unit = net proceeds ÷ units where matched; the market median where not.
6. Profit at stake = demand × ppu; pw_gbp = that × FX.
7. **R1:** every row with cover < 4 has reco > 0.

QA counts shown to users (per market): source rows, blanks set to 0, duplicates dropped, snapshots found, unmapped SKUs, economics matched by SKU / by ASIN / not matched, Mich rows (source, date fixed, dropped, matched, not in that day's export), median used for profit, loss-makers needing action, final row count.

## 9. Acceptance numbers

From the current input files, latest snapshot per market. Your rebuild should match these exactly.

| Status | UK | US | AU | All | Units recommended |
|---|---|---|---|---|---|
| 1 Out of stock | 22 | 39 | 7 | 68 | 2,322 |
| 2 Urgent | 17 | 13 | 7 | 37 | 2,181 |
| 3 Below target | 19 | 18 | 64 | 101 | 1,078 |
| 4 OK | 45 | 21 | 101 | 167 | 0 |
| 5 Excess | 26 | 16 | 16 | 58 | 0 |
| 6 Keep listing alive | 170 | 176 | 50 | 396 | 785 |
| 7 No recent sales | 15 | 22 | 42 | 79 | 0 |
| **Total** | **314** | **305** | **287** | **906** | **6,366** |

- All snapshots: 3,557 rows (UK 1,233, US 1,179, AU 1,145). Economics rows loaded: 695 (all four markets).
- Units recommended by market: UK 3,372, US 2,247, AU 747. SKUs with a recommendation: 600.
- Amazon recommendation total: 10,927 units. Mich (latest snapshot): 302 units.
- Flags: Amazon alert 217, Losing money 109, Several SKUs on one ASIN 90, Out of stock 68, Aged stock 64, Unfulfillable units 46, Price check 11, Inbound not moving 1.
- Unmapped SKUs: 9. Rows with cover < 4 weeks, all snapshots: 355 (all with reco > 0).
- Top of the list (all markets): LM5301GN-DR-FBA-UK, LM3001OR-DR-FBA-UK, LMD9022TQ-DE, LM3001GN-DR-UK-FBA, LMD9022GN-DE.

## 10. Open items

To be confirmed by Ramin or Mich. The current assumed values are in the code (`rules.py`, `TO_CONFIRM`) and on the dashboard's Rules page.

- Lead time and buffer per market (assumed 4 + 4 weeks everywhere).
- Cap on weeks of cover (26 weeks; Mich said "no more than a year").
- Slow-seller rule: Mich described it for AU only; applied to all markets.
- What Ramin actually restocked: estimated as the rise in inbound units since the previous snapshot. Replace with his pick lists or shipment records.
- SKU base-code rule: check against the master file. Known oddities: dog and cat versions share a base code; 11 ASINs map to two base codes (old letter codes vs new numeric codes); 23 SKUs end `-DE`.
- Canada SKUs in the US export: keep under US or split out?
- Keep every listing alive (2 units), and whether unmapped SKUs (bundles, test listings) should be excluded.
- Restock SKUs that lose money (yes for now, for brand presence).
- How to order SKUs that need action (status, then profit at stake).
- Exchange rates (fixed, rounded).
- Profit per unit when there is no economics match (market median).
- Why Mich skips or trims Amazon's number: she copies Amazon's quantity on about half the SKUs where both exist and sends about two-thirds of it on most others. Possible limits: warehouse capacity, the UK's flat 20 units in late October, US cartons of 72.

## 11. Known issues and limitations

- **K2. "Out of stock" ignores inbound.** Proposed fix: an "Out of stock, inbound" status, or rank these after SKUs with nothing on the way.
- Weekly demand comes from units shipped. A SKU that was out of stock for part of the 30-day window looks slower than it is.
- Most Canada SKUs have no economics row and use the US median profit per unit (USD); their prices may be in CAD (not checked).
- Mich's reco sheets cover only the SKUs she reviewed that day, so her totals are not comparable with ours or Amazon's.
- Only four snapshots, about a month apart: enough to show direction, not trends or seasonality.
- No warehouse stock: every recommendation assumes the warehouse can supply it.

## 12. Dashboard (what users saw in the mock)

A single offline HTML page, built for internal review (Lee, Marcial, Mich) before Ramin. Rebuild the behaviour, not the styling. Pages:

**Replenishment list** (the main view, latest snapshot only):
- Filters: Market; Status (All, 1–7); Status group (All, Needs a restock = reco > 0, Needs action = 1–3, Selling = 1–5, No sales in 90 days = 6–7); Exception flag. All filters stack and drive the tiles, charts and list. Defaults: all markets, all statuses.
- Tiles (clicking one filters the list): **SKUs needing a restock** (count, units to send; the main number), **Need action now** (statuses 1–3 with the split), **Excess**.
- Charts panel, collapsed by default: SKUs by status per market; units to send (ours vs Amazon vs Mich vs New inbound) per market; **profit lost to stockouts each week** (Out of stock SKUs, demand × ppu, losses as 0; total plus top 10); **top 20% of SKUs by profit per week** split by status. The two profit charts follow the Market filter only. Each chart has its numbers in a table below it.
- Status legend above the list: badge plus a short definition; clicking one filters by it.
- Columns: Status · SKU (base code bold, suffix, product name, flag chips) · Market · **Restock recommendation** (highlighted) · Amazon recommendation · Mich · Available · Inbound · Demand /wk · Cover (wks) ("no sales" when NULL) · Profit /unit · Profit at stake /wk · New inbound · Sold 30d / 90d · Net proceeds · Why. Numbers are rounded for reading; the CSV export keeps exact values.

**Rules & assumptions:** requirements from Ramin; settings tiles; "how the restock recommendation is calculated" in plain words with a live example; rules table; to-confirm table; flags; statuses; data-engineering assumptions. Generate this page from the same settings the code uses, so they cannot drift apart.

**QA & data checks:** the QA counts from section 8 and the list of unmapped SKUs.

## 13. Reference implementation (this folder)

| File | What it does |
|---|---|
| `rules.py` | All settings and rule logic, plus the text for the Rules page (rules, statuses, flags, requirements, to-confirm). |
| `prep.py` | Pipeline steps 1–9; writes `lickimat_replenishment.json`. |
| `verify.py` | Independent checks against the raw Excel (section 8). |
| `export_handoff.py` | Writes the processed-data CSVs in section 14 from the JSON. |
| `work/dashboard_template.html` | Page template; the JSON is injected by an internal Cloudstaff build script (`cs-dashboard` skill), which a rebuild does not need. |

Run with Python 3.12, pandas and openpyxl: `python prep.py --src <folder with the two workbooks> --out <output folder>`, then `python verify.py <same src> <same out>`. It must print only PASS lines. `python export_handoff.py <same out>` writes the CSVs.

## 14. Processed data: what populates the dashboard

Folder `handoff_data/` (client data, shared separately, never in source control), made from `lickimat_replenishment.json` (the same content as one JSON file). UTF-8 CSV. Generated from the 30 Oct 2026 exports.

| File | Rows | Grain | Feeds |
|---|---|---|---|
| `replenishment_rows.csv` | 3,557 | market × snapshot × SKU | everything; older snapshots feed New inbound and Inbound not moving |
| `replenishment_latest.csv` | 906 | market × SKU, latest snapshot (`sr = 0`) | tiles, charts, list, CSV export |
| `economics.csv` | 695 | market × SKU (UK, US, AU, DE) | profit per unit; kept for reference |
| `settings.csv` | 26 | one setting | rule settings, currencies, economics windows, snapshot dates |
| `qa_counts.csv` | 46 | market × QA step | QA page |
| `unmapped_skus.csv` | 14 | SKU | QA page (9 unmapped SKUs + 5 Mich rows not matched to an export) |
| `page_requirements.csv`, `page_rules.csv`, `page_statuses.csv`, `page_flags.csv`, `page_to_confirm.csv`, `page_data_assumptions.csv` | 1–16 | one line of text | Rules & assumptions page |

### Data dictionary: `replenishment_rows.csv`

**Source** = what the data feed must supply (directly or by a lookup). **Derived** = calculated by the rules in sections 4–7. If a new feed supplies every Source field, the Derived fields can be recalculated and should match this file.

| Column | Type | Kind | Meaning |
|---|---|---|---|
| m | text | Source | Market: UK, US, AU |
| snap | date | Source | Snapshot date of the Amazon export |
| sr | int | Derived | Snapshot rank within the market, 0 = latest |
| sku, asin, name | text | Source | Amazon SKU, ASIN, product name |
| base | text | Derived | Base code (section 4, step 3); the whole SKU when unmapped |
| base_ok | bool | Derived | False = unmapped (no LM product code) |
| avail | number | Source | Units available at Amazon |
| inb | number | Source | Units inbound (working + shipped + receiving) |
| unf | number | Source | Unfulfillable units |
| aged | number | Source | Units over 180 days old (sum of Amazon's age buckets) |
| s7, s30, s90 | number | Source | Units sold in the last 7 / 30 / 90 days |
| dem | number | Derived | Weekly demand |
| cover | number or blank | Derived | Weeks of cover; blank = no demand (not 0) |
| status | text | Derived | One of the 7 statuses |
| reco | number | Derived | **Restock recommendation** (units) |
| amz | number or blank | Source | Amazon recommendation (units) |
| mich | number or blank | Source | Mich's quantity for that date; blank = she did not review the SKU |
| sent | number or blank | Derived | New inbound: rise in inb since the previous snapshot (estimate of what Ramin restocked) |
| price, featured | number | Source | Our price; featured offer price |
| np | number or blank | Source (economics) | Net proceeds over the economics window, market currency |
| margin | number or blank | Source (economics) | Net margin % |
| econ | text or blank | Derived | How economics matched: SKU, ASIN, or blank |
| eunits | number or blank | Source (economics) | Net units sold over the economics window |
| ppu | number | Derived | Profit per unit, market currency |
| ppu_est | bool | Derived | True = ppu is the market median |
| pw | number | Derived | Profit at stake per week, market currency |
| pw_gbp | number | Derived | pw in GBP at the fixed rate (ordering only) |
| loss | bool | Derived | Net proceeds < 0 |
| flags | text | Derived | Exception flags, separated by `\|` |
| why | text | Derived | One-line reason shown in the list |

Four Source fields are used by the flags but are not in the file because the flags are already calculated: `inbound-shipped` (Inbound not moving), `sales-price` (Price check), `alert` (Amazon alert) and the previous snapshot's `inbound-shipped`. A new pipeline needs them in its feed.

Precision: decimals are rounded to 2 places in the file. Recalculate from the Source fields to compare exactly; allow for that rounding when comparing `dem`, `cover`, `ppu` and `pw`.

`economics.csv` columns: m, cur (currency), months (window), sku, asin, rev (net sales revenue), np (net proceeds), margin (net margin %), units (net units sold).

**Minimum feed for a new system** (per market, per snapshot, per SKU): sku, asin, product name, available, inbound, inbound shipped, unfulfillable, aged units over 180 days, units sold in 30 and 90 days, Amazon's recommended quantity, price, sale price, featured offer price, alert. Plus per SKU per market: net proceeds and net units sold over a stated window. Mich's quantities are optional (comparison only).
