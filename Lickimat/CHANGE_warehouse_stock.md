# Change: limit Amazon restock by warehouse stock and other-channel demand

For the developer who built the replenishment list. This is the next change to it, on top of the current rules (including corrections C1–C4). Status: **mock data**. The client has not shared warehouse stock or wholesale / brick-and-mortar demand yet, so both input files here are made up, keyed on the real SKUs from the latest Amazon exports. Build to the file layout below and the real files can replace the mock ones later.

---

## 1. Why

Amazon is a small part of Lickimat's business. Brick-and-mortar and wholesale come first. Today the list recommends what Amazon needs without checking whether the warehouse has it to give. After this change:

1. Each store's warehouse stock is checked before recommending.
2. Units already promised to other channels are set aside first.
3. Amazon gets at most what is left.

**Example:** Amazon needs 50 units. The warehouse has 100, other channels need 70. Free stock is 100 − 70 = 30, so the recommendation is **30**, flagged as short by 20.

## 2. Warehouses

One warehouse per Amazon store. Stores do not share stock.

| Store | Warehouse |
|---|---|
| Amazon UK | Trilanco |
| Amazon US | Extensiv |
| Amazon AU | Wattle 3PL (a made-up name; the real AU warehouse is not known yet) |

Make the warehouse a per-store setting (Admin → Stores, next to lead time), not a hard-coded value.

## 3. New input files

Two files, one row per store × warehouse item. Both are UTF-8 CSV. The `as_of` date in the mock files equals that store's latest Amazon snapshot date (UK 2026-10-30, US 2026-10-29, AU 2026-10-30).

**`warehouse_stock.csv`**: units physically in the warehouse.

| Column | Type | Meaning |
|---|---|---|
| as_of | date | Date of the stock count |
| warehouse | text | Trilanco, Extensiv, Wattle 3PL (made up) |
| store | text | UK, US, AU: the Amazon store this warehouse supplies |
| item | text | Warehouse item code (section 4) |
| on_hand | integer | Units in the warehouse |

**`other_demand.csv`**: units to set aside for brick-and-mortar and wholesale. It is one total per item, with no channel split and no due dates. In the mock it stands for the other channels' next 4 weeks of orders. The rule takes it as given, whatever window the real file uses.

| Column | Type | Meaning |
|---|---|---|
| as_of, warehouse, store, item | | as above |
| other_demand | integer | Units reserved for other channels |

Join both files to the list on `store` + `item`. The mock has 844 items (UK 298, US 269, AU 277). Three items that Amazon needs are left out on purpose, to test a missing record (scenario S8).

## 4. Warehouse item code

**There is no warehouse item mapping in the data we have.** The Amazon exports carry only Amazon SKUs, and the client's product master (ITF file) is confidential. So the mock defines the item code, and it must be confirmed against the real warehouse files when they arrive.

Rule used: **item = base code + the variant code that follows it, when there is one.**

- Base code: as today (the leading LM product code, regex in HANDOFF section 4 step 3).
- Variant code: the first segment after the base code (split on `-` or space), if it is one of `DR`, `CR`, `DE`, `CE`, `DA`, `R`, `E`. Otherwise there is no variant.
- Our reading of the codes (not confirmed): D/C = dog/cat; R/E/A = pack version (retail, e-commerce, other). Different packs are different physical items, so each is its own warehouse item.

| Amazon SKU | Item |
|---|---|
| LM9003TQ-CR-UK-FBA | LM9003TQ-CR |
| LM9001GN-DE-FBM | LM9001GN-DE |
| LM5201PU-R-FBA-UK | LM5201PU-R |
| LM9962GN-FBA-US | LM9962GN |
| LMDB2-FBA-CA | LMDB2 |
| bundles, `TESTING …` listings (unmapped SKUs) | none |

Several Amazon SKUs in one store can map to the same item (old and new SKU names, FBA and FBM listings). In the latest snapshot 45 items have 2–4 SKUs. They draw on the same free stock (section 5).

## 5. Rule

The current rules are unchanged and produce **Amazon need** (today's restock recommendation: target cover × demand − stock, keep-alive, slow-seller top-up, C1–C4). The new step runs after them, per store:

```
free stock (item)  = max(0, on_hand − other_demand)

for each item, take its Amazon SKUs with Amazon need > 0 in list order
(status, then lowest cover, then highest weekly demand):
    can send (SKU)  = min(Amazon need, free stock still left on the item)
    free stock left = free stock left − can send

item not in the warehouse files, or SKU has no item:  can send = 0
units short = Amazon need − can send
```

- **Restock recommendation = can send.** This is the number to act on. Amazon need is shown beside it so the gap stays visible.
- Status and list order do **not** change. They still describe the SKU's cover at Amazon. An Urgent SKU stays Urgent even when the warehouse can't supply it, and that's exactly what Ramin needs to see.
- Other demand always wins. Amazon gets nothing until other demand is covered in full, including keep-alive units.
- SKUs with Amazon need = 0 are untouched, however short the warehouse is (scenario S7).
- No carton rounding, as today.
- Only the latest Amazon snapshot is checked against the warehouse. Older snapshots keep can send = Amazon need and blank warehouse columns.

### Requirement R1, restated

R1 (every SKU under 4 weeks of cover gets a recommendation above 0) now applies to **Amazon need**. The warehouse can still be empty. When can send is below Amazon need, the row must carry one of the two flags below. A SKU under 4 weeks of cover is therefore never silently 0.

### New flags

| Flag | Condition | Meaning shown to users |
|---|---|---|
| Short at warehouse | item found, can send < Amazon need | Not enough free stock after other channels: send what is free and check with the warehouse. |
| No warehouse record | Amazon need > 0 and the item is missing from the warehouse files, or the SKU has no item (bundle, test listing) | Not found in the warehouse files, so nothing is recommended. Check the item code. |

### Why column

Append one sentence to the current reason when Amazon need > 0:

- Enough: `Trilanco: 720 on hand, 324 set aside for other channels, 396 free. Send 134.`
- Short: `Trilanco: 100 on hand, 70 set aside for other channels, 30 free. Send 30 of the 53 needed.`
- Shared item: `Extensiv: 91 on hand, 66 set aside for other channels, 25 free (7 left after other SKUs on this item). Send 7 of the 14 needed.`
- Missing: `No warehouse record for this item, so nothing can be sent.` / `Not a warehouse item (bundle or test listing), so nothing can be sent.`

`expected_results.csv` has this text for every row (column `why_warehouse`).

## 6. Dashboard changes

**List columns.** Put these next to the highlighted Restock recommendation, which now shows can send: **Amazon need**, **Warehouse on hand**, **Other demand**, **Free stock** (item level), **Short** (units). The CSV export gets the same columns.

**Tiles.** "SKUs needing a restock" counts and sums can send. Add a tile **Short at warehouse**: SKUs flagged Short at warehouse or No warehouse record, plus the units short. Clicking it filters the list.

**Flag filter.** Add the two new flags.

**Rules page.**

- **Settings:** add the warehouse per store.
- **How it's calculated:** add a step: *Free stock = warehouse on hand − units set aside for other channels. Amazon gets the smaller of what it needs and what is free. When several Amazon SKUs share one item, the most urgent SKU in the list gets the stock first.*
- **Statuses and flags:** add the two flags.
- **Requirements:** add R1's new wording.
- **To confirm:** add the items in section 8.

**Worked example** (add it to the Rules page under the current one): Amazon needs 53. Trilanco has 100, other channels need 70, so 30 are free. Send 30, short by 23.

**QA page:**

- Warehouse items loaded per store.
- Amazon SKUs with no warehouse item.
- Items in the warehouse files with no Amazon SKU (fine, since other channels sell them).
- Items where other demand exceeds on hand.

## 7. Mock data and acceptance

Folder `Warehouse change (mock)/data/`. It holds client SKU codes, so it is shared separately and never put in source control.

| File | Rows | What it is |
|---|---|---|
| `warehouse_stock.csv` | 844 | Input: mock on-hand per store × item |
| `other_demand.csv` | 844 | Input: mock other-channel demand per store × item |
| `expected_results.csv` | 906 | Expected output for every Amazon SKU in the latest snapshot: Amazon need, warehouse columns, can send, flag, why text, test scenario, kind of item |
| `test_cases.csv` | 37 | The planted scenarios only (below), for unit tests |

The generator is `mock_warehouse.py` (seeded, so it is repeatable). There is no real other-channel data to calibrate against, so the values are made plausible rather than real:

- **Products Amazon sells** (371 items): each product gets its own Amazon share of total demand (median about 14%, 10th–90th percentile 4–32%), so some products are wholesale-heavy and others Amazon-heavy. Other demand = the other channels' next 4 weeks. On hand = 2–20 weeks of total demand (median 9), independent of Amazon need. About 1 in 5 of these come up short on their own.
- **Products with no Amazon sales** (473 items), in three kinds: leftovers (a few units, little other demand), wholesale-only lines (real volume, other channels only) and discontinued (0 on hand, 0 demand).
- On hand is counted in full cartons (12–72 depending on the store) above one carton. Other demand is in cases of 6.
- Column `item_kind` in `expected_results.csv` says which kind each item is (seller, leftover, wholesale only, discontinued).

On top of that, the scenarios below are planted, so that each branch of the rule appears in every store. The rows not planted are labelled `Generated`. Shortages among them are real outcomes of the mock values, not test cases.

| Scenario | What is set | Expected |
|---|---|---|
| S0 Brief example | on hand 100, other 70 (UK LM9003TQ-CR-UK-FBA, need 53; US LM9081PU-CE, need 55) | send 30, Short at warehouse |
| S2 Partly short | free = about half of the need (3 per store) | send = free, Short at warehouse |
| S3 Other channels take it all | on hand < other demand (3 per store) | free 0, send 0, Short at warehouse |
| S4 Warehouse empty | on hand 0 (2 per store) | send 0, Short at warehouse |
| S5 Several SKUs share one item | free covers the first SKU in list order and part of the second (US LM9001GN-DE, LM9001OR-DE) | first SKU gets its full need, second gets the rest, flagged |
| S6 Keep-alive, no free stock | on hand 5, other 5 (AU LM2102GN-DR) | send 0 of 1, Short at warehouse |
| S7 Amazon needs nothing | on hand 10, other 200, on a product Amazon sells | send 0, no flag |
| S8 Not in warehouse files | item left out of both files (1 per store) | send 0, No warehouse record |

**Acceptance numbers** (latest snapshot, SKUs with Amazon need > 0):

| Store | SKUs | Amazon need | Can send | Units short | Short at warehouse | No warehouse record | Can send = 0 |
|---|---|---|---|---|---|---|---|
| UK | 58 | 2,810 | 2,136 | 674 | 18 | 1 | 8 |
| US | 27 | 880 | 590 | 290 | 13 | 1 | 7 |
| AU | 62 | 430 | 332 | 98 | 21 | 1 | 10 |
| **All** | **147** | **4,120** | **3,058** | **1,062** | **52** | **3** | **25** |

**About Amazon need.** The mock recomputes it from the raw exports with the current rules and C1–C4 as we understand them. That gives these status counts in the latest snapshot: Out of stock 68, Urgent 28, Below target 94, OK 184, Excess 57, Keep listing alive 4, No recent sales 471 (906 SKUs). If your system's counts differ, the totals above will differ too. In that case, test the new step with `test_cases.csv`: feed it the `amazon_need` column given there, and `can_send` and `flag` must match.

**Checks to automate** (all pass on the mock):

1. can send ≤ Amazon need, and ≥ 0, for every SKU.
2. For every item, the sum of can send over its SKUs ≤ free stock.
3. R1: every SKU with cover < 4 weeks has Amazon need > 0.
4. can send < Amazon need ⇔ the row has Short at warehouse or No warehouse record.

## 8. To confirm (add to the Rules page)

| Item | What is assumed | Who to ask |
|---|---|---|
| Warehouse per store | Trilanco → UK, Extensiv → US, AU warehouse unknown (mock name) | Ramin |
| Warehouse item code | Base code + variant code (DR, CR, DE, CE, DA, R, E). D/C = dog/cat and R/E/A = pack version is our guess | Mich / Trilanco (check against the item master) |
| Other demand | One total per item, all of it reserved ahead of Amazon. The mock uses the other channels' next 4 weeks. Real data may come as dated orders; then the window has to be agreed (4 weeks? the 8-week Amazon target?) | Ramin |
| Amazon always second | No minimum for Amazon, not even keep-alive units, when other channels need everything | Ramin |
| Missing warehouse record | Treated as 0 free stock (nothing sent) rather than unlimited | Ramin |
| Shared items | Free stock goes to the most urgent SKU first (list order) | Ramin |
| Stock in transit to the warehouse | Not counted: on hand only. Purchase orders arriving at the warehouse are ignored | Ramin |
| Warehouse data freshness | Assumes the warehouse files are dated the same day as the Amazon snapshot | Ramin / warehouse |

## 9. Out of scope

- Real warehouse and demand feeds (format unknown). Keep loading separate from the rule, as with the Amazon exports.
- Moving stock between warehouses or stores.
- Telling Ramin what to reorder from the supplier when the warehouse is short.
- Rounding recommendations to cartons or case packs, and Amazon capacity limits (unchanged open items). The mock's warehouse stock is in cartons, but the rule does not round.
