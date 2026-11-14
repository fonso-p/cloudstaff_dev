# Priority Score company data pipeline: business rules and assumptions

**Pipeline version:** 0.4 (prototype) · **Implemented in:** [`format_priority_data.ipynb`](format_priority_data.ipynb) · **Last updated:** 2026-11-13

This document lists every rule and assumption the pipeline applies when it merges and formats HubSpot and MyStaff into the
`Priority List` layout used by the Priority Score model, scores the accounts and routes them to teams, plus a catalogue
of where each output column comes from (§4.1).

**How the code is built and run** (functions, files, settings map, dashboard data format, going to production) is in
[`PIPELINE.md`](PIPELINE.md). The notebook keeps every rule here as data in sections **0a–0b**, so a rule change should update
both places; [`PIPELINE.md` §5](PIPELINE.md) maps each rule to its setting.

Counts quoted below come from the run of 2026-11-10 (HubSpot export dated 2026-11-09, MyStaff export dated 11-09-2026).

---

## 1. Scope

| In scope (v0.4) | Out of scope (later stages) |
|---|---|
| Company / client identity: `account_id`, `company_name`, `goal`, `industry`, `employee_band`, `region` | **Real** sources for website, news, job postings, referrals, Competitor client, industry trend |
| Matching and merging HubSpot with MyStaff | Contact-level data |
| Signals: **real seat growth** (MyStaff); everything else **mock (synthetic)** (§11.1) | Write-back to HubSpot |
| Scoring with the `dashboard_v3` settings (`dashboard_v2`'s stacked Act now bonus, average-filled unknowns and percentile tiers, plus Fit points from the Client Propensity scores), team routing and ranking (§11.2–11.3) | Building the dashboard page (part 2: `../build_dashboard/`); fit in routing; negative signals (later) |
| Saving the processed data the dashboard reads (§11.4) | |
| Lineage columns for audit | |

## 2. Pipeline stages

```
EXTRACT → STANDARDIZE → MATCH → MERGE → CONFORM → DQ → SIGNALS → SCORE → ROUTE → DQ → DASHBOARD DATA → LOAD (local)
                                                                                                  │
                                                          then, as a separate step:               ▼
                                                          processed data → Account Priority Dashboard
```

| # | Stage | What it decides | Rules |
|---|---|---|---|
| 1 | Extract | Which source fields are used (today Excel exports; production will use DB/API) | §3 |
| 2 | Standardize | Which rows are dropped, and how industry, employee band, region and seat growth are derived | §5–§8, §11.1 |
| 3 | Match | Which HubSpot records are already MyStaff clients | §9 |
| 4 | Merge | Goal assignment (New Logo / Organic Growth) and which source wins for each field | §10 |
| 5 | Conform | The output columns and their groups | §4 |
| 6 | DQ: merge | What must hold after the merge | §13 |
| 7 | Signals | Which signals are real and which are mock | §11.1 |
| 7b | Propensity | Fit scores from the Client Propensity project: real, mock or off (they feed the Fit points in stage 8) | §11.1b, §11.2b |
| 8 | Score | Priority score, Act now bonus, tier | §11.2 |
| 9 | Route | Which team owns each account, and the order within each list | §11.3 |
| 10 | DQ: scoring | What must hold after scoring and routing | §13 |
| 11 | Dashboard data | What the dashboard shows for each account | §11.4 |
| 12 | Load | Where the processed data is saved (locally, outside the git repo) | §14 |

Functions, files, how to run it, and the dashboard data format are in [`PIPELINE.md`](PIPELINE.md).

## 3. Sources and contracts

| Source | Represents | Goal label | Fields used (source → pipeline) |
|---|---|---|---|
| **HubSpot** (company report) | Prospects | `New Logo` | Record ID → `hs_record_id` · Company name · Website URL · Number of Employees · Industry · Annual Revenue · Financial Reports (free text, used only as region evidence) |
| **MyStaff** (sheet `MyStaff`) | Active clients | `Organic Growth` | Shortcode · Client · Active · CRM Company ID · Website URL · Office Address State / Country · Industry Hubspot · Industry Roll Up · Total Staff · Month to Date / Last Month / Month-2…Month-5 Movement Add (seat growth) |

* MyStaff `CRM Company ID` **is** the HubSpot company `Record ID`. This is the primary join key.
* MyStaff `Total Staff` counts Cloudstaff seats, **not** company size. It is kept as `cs_staff_current` and never used for `employee_band`.
* A production extractor only has to return the same contract fields. No downstream stage changes.

## 4. Output column groups

| Group | Columns | Populated by |
|---|---|---|
| `1_company` | `account_id`, `company_name`, `goal`, `industry`, `employee_band`, `region` | **This pipeline** |
| `2_enrichment` | `web_visits_30d`, `team_builder_visit`, `form_fill_30d`, `news_signal`, `news_signal_date`, `job_postings_30d`, `hiring_spike`, `diamond_referral`, `prior_bpo_flag` (= Competitor client), `industry_trend`, **`seats_added_6m`** | Stage 7. **Synthetic (mock)** while `ENRICHMENT_MODE = "mock"`, except `seats_added_6m` (real, MyStaff) (§11.1) |
| `3_scoring` | `industry_modifier` … `sort_key` (the mock's 16 columns, including `tier`, `assigned_team`, `rank_in_team_list`), plus **`seat_signal (0-1)`, `seat_pts`, `score_before_bonus`, `act_now_bonus`, `act_now_triggers`** | Stages 8–9: scoring with the live settings profile, plus team routing (§11.2–11.3) |
| `4_lineage` | `source`, `shortcode`, `hubspot_record_id`, `crm_company_id`, `match_type`, `hs_company_name`, `website_domain`, `industry_sector`, `industry_raw`, `industry_source`, `employee_count`, `employee_source`, `region_source`, `annual_revenue`, `cs_staff_current`, `name_match_review`, `note`, `enrichment_source` | This pipeline; not part of the mock |

Groups 1–3 follow the Priority List column order of the scoring model. The 6 **dashboard extensions** (bold above, `DASHBOARD_EXTENSIONS`)
are appended at the end of their group. `industry` uses the pipeline's own taxonomy (§6). `industry_sector`, the parent of `industry`,
sits in group 4 so groups 1–3 keep that order. In the Excel output, header colours
show the group, and a `column_groups` sheet lists each column.

**`account_id`:** `MS-<shortcode>` for any row that is a MyStaff client (including merged rows), otherwise `HS-<record id>`.

### 4.1 Data catalogue

Where every output column comes from. **Origin** is one of:

| Origin | Meaning | Trust |
|---|---|---|
| 🟦 **Raw** | Copied from a source file, with light cleaning only (trimmed, `&amp;` fixed, `0` → blank) | Real |
| 🟩 **Derived** | Calculated by a pipeline rule from raw fields | Real (as good as its inputs) |
| 🟥 **Mock: random** | Generated by the mock signal generator (§11.1), seeded per `account_id`. **Fictional** | Not real |
| 🟧 **Mock: fixed** | A hand-set placeholder value from a lookup table, not from data. **Fictional** | Not real |
| 🟪 **Derived from mock** | Calculated by a rule, but at least one input is mock, so the result is not real either | Not real |

Source files: **HS** = HubSpot company report (`hubspot-core-report-*.xlsx`); **MS** = MyStaff export
(`CONFIDENTIAL Mystaff … .xlsx`, sheet `MyStaff`).

**Group 1: company**

| Column | Origin | Source / rule | § |
|---|---|---|---|
| `account_id` | 🟩 Derived | `MS-` + MS `Shortcode`, or `HS-` + HS `Record ID` | 4 |
| `company_name` | 🟦 Raw | MS `Client`; HS `Company name` for HubSpot-only rows | 10 |
| `goal` | 🟩 Derived | MyStaff client or matched → Organic Growth; unmatched HubSpot → New Logo | 10 |
| `industry` | 🟩 Derived | HS `Industry` / MS `Industry Hubspot` mapped to 18 groups; MS `Industry Roll Up` as fallback | 6 |
| `employee_band` | 🟩 Derived | HS `Number of Employees` banded (merged clients get it from their HubSpot record) | 7 |
| `region` | 🟩 Derived | MS `Office Address Country` + `State`; for HubSpot-only rows, website domain → company name → `Financial Reports` text → `.com` = US (**assumption A1**) | 8 |

**Group 2: enrichment (signals)**

| Column | Origin | Source / rule | § |
|---|---|---|---|
| `web_visits_30d` | 🟥 Mock: random | Mock generator | 11.1 |
| `team_builder_visit` | 🟥 Mock: random | Mock generator | 11.1 |
| `form_fill_30d` | 🟥 Mock: random | Mock generator | 11.1 |
| `news_signal` | 🟥 Mock: random | Mock generator (category names from `NEWS_STRENGTH`) | 11.1 |
| `news_signal_date` | 🟥 Mock: random | Mock generator, relative to the run date | 11.1 |
| `job_postings_30d` | 🟥 Mock: random | Mock generator | 11.1 |
| `hiring_spike` | 🟥 Mock: random | Mock generator | 11.1 |
| `diamond_referral` | 🟥 Mock: random | Mock generator (New Logo). Organic Growth = `N/A` by rule | 11.1 |
| `prior_bpo_flag` (Competitor client) | 🟥 Mock: random | Mock generator (New Logo). Organic Growth = `N/A` by rule | 11.1 |
| `industry_trend` | 🟧 Mock: fixed | `INDUSTRY_TREND` lookup on `industry`: the workbook's placeholder values (**A8**) | 11.1 |
| `seats_added_6m` | 🟩 Derived | Sum of MS `Month to Date`, `Last Month`, `Month-2` … `Month-5 Movement Add` (gross adds, **A11**). Organic Growth only | 11.1 |

**Group 3: scoring and routing.** All are calculated, but almost every one depends on mock signals:

| Column | Origin | Source / rule | § |
|---|---|---|---|
| `industry_modifier` | 🟪 Derived from mock | 0.9 + 0.2 × `industry_trend` | 11.2 |
| `web_signal (0-1)` | 🟪 Derived from mock | Team Builder visit, form fill, visits | 11.2 |
| `news_jobs_signal (0-1)` | 🟪 Derived from mock | News strength × recency, hiring | 11.2 |
| `web_pts` | 🟪 Derived from mock | Signal × max (or baseline) | 11.2 |
| `news_jobs_pts` | 🟪 Derived from mock | Signal × max (or baseline) | 11.2 |
| `diamond_pts` | 🟪 Derived from mock | `diamond_referral` | 11.2 |
| `bpo_pts` (Competitor points) | 🟪 Derived from mock | `prior_bpo_flag` | 11.2 |
| `base_points` | 🟪 Derived from mock | Sum of points | 11.2 |
| `priority_score` | 🟪 Derived from mock | Base × modifier + Act now bonus (stacked), capped at 100 | 11.2 |
| `estimated_fields` | 🟪 Derived from mock | Which components were unknown (scored at the average of the accounts that have them) | 11.2 |
| `data_coverage` | 🟪 Derived from mock | Share of max points backed by data | 11.2 |
| `hot_trigger` | 🟪 Derived from mock | First Act now trigger that applies (decides the team) | 11.2 |
| `tier` | 🟪 Derived from mock | Rank of `priority_score` within the goal: top 10% / next 30% / rest | 11.2 |
| `assigned_team` | 🟥 Mock: random | The trigger's team where there is an Act now trigger; otherwise a seeded random draw with the mock dashboard's probabilities (**A9**) | 11.3 |
| `rank_in_team_list` | 🟪 Derived from mock | Position within team × goal list | 11.3 |
| `sort_key` | 🟪 Derived from mock | The final score (older profiles: score + 1000 if hot) | 11.2 |
| `seat_signal (0-1)` | 🟩 Derived | `seats_added_6m` banded (0 / 1–5 / 6–10 / 11+) | 11.2 |
| `seat_pts` | 🟩 Derived | Seat signal × 20 (if unknown: the average seat signal of the clients that have it) | 11.2 |
| `score_before_bonus` | 🟪 Derived from mock | Score before the Act now bonus | 11.2 |
| `act_now_bonus` | 🟪 Derived from mock | +15 per trigger family (+7.5 Diamond), the 2nd family × 0.5, the 3rd × 0.25 | 11.2 |
| `act_now_triggers` | 🟪 Derived from mock | Every Act now trigger that applies, in priority order | 11.2 |

**Group 4: lineage**

| Column | Origin | Source / rule | § |
|---|---|---|---|
| `source` | 🟩 Derived | `HubSpot`, `MyStaff` or `MyStaff + HubSpot` | 10 |
| `shortcode` | 🟦 Raw | MS `Shortcode` | 3 |
| `hubspot_record_id` | 🟦 Raw | HS `Record ID` (merged rows can list several) | 10 |
| `crm_company_id` | 🟦 Raw | MS `CRM Company ID`; HS `Record ID` for HubSpot-only rows | 9 |
| `match_type` | 🟩 Derived | How a HubSpot record matched a client | 9 |
| `hs_company_name` | 🟦 Raw | HS `Company name` of the merged HubSpot record | 10 |
| `website_domain` | 🟩 Derived | Normalised from MS / HS `Website URL` | 9 |
| `industry_sector` | 🟩 Derived | Parent sector of `industry` | 6 |
| `industry_raw` | 🟦 Raw | HS `Industry`; MS `Industry Hubspot` (or `Industry Roll Up` when that is `-`) | 6 |
| `industry_source` | 🟩 Derived | Which field supplied `industry` | 6 |
| `employee_count` | 🟦 Raw | HS `Number of Employees` (`0` → blank) | 7 |
| `employee_source` | 🟩 Derived | Which record supplied the count | 7 |
| `region_source` | 🟩 Derived | Which rule set `region` | 8 |
| `annual_revenue` | 🟦 Raw | HS `Annual Revenue` | 3 |
| `cs_staff_current` | 🟦 Raw | MS `Total Staff` (Cloudstaff seats, not company size) | 3 |
| `name_match_review` | 🟩 Derived | Client with the same name but no ID / domain match (review only) | 9 |
| `note` | 🟩 Derived | Free-text note (e.g. ambiguous domain candidates) | 10 |
| `enrichment_source` | 🟩 Derived | Label saying which signals are mock and which are real | 11.1 |

**Raw fields used as inputs only** (not output as columns):

| Field | File | Used for | § |
|---|---|---|---|
| `Active` | MS | Keep active clients only | 5 |
| `Office Address State`, `Office Address Country` | MS | `region` | 8 |
| `Industry Roll Up` | MS | `industry` fallback | 6 |
| `Month to Date` … `Month-5 Movement Add` | MS | `seats_added_6m` | 11.1 |
| `Financial Reports` | HS | Region evidence (country keywords) | 8 |
| `Website URL` | HS, MS | `website_domain` (matching, region) | 8–9 |

**Summary:** of the 56 output columns, 9 are raw, 18 are derived from real data, 10 are mock-random (the 9 signals and `assigned_team`),
1 is a mock-fixed placeholder, and 18 are derived from mock inputs. Until real signal sources are connected, **only groups 1 and 4, plus
`seats_added_6m`, `seat_signal (0-1)` and `seat_pts`, are real data.**

## 5. Row filters

| Rule | Applies to | Current effect |
|---|---|---|
| Keep only `Active = Yes` | MyStaff | 0 removed (the export is already active-only) |
| Drop QA / test accounts: client name matches `^test` or the word `qa` | MyStaff | 4 removed (TestTrace Corp, TestTrack Services, Customer Portal - QA Test v5, ReadyToGo-QA) |
| Drop empty spreadsheet rows (no shortcode) | MyStaff (Excel only) | ~1.05M formatting-only rows |
| **Not** filtered: rows whose `Industry Roll Up` is `CLOUDSTAFF` / `Test Record - No Category` / `Cloudstaff Test Account` | MyStaff | 56 rows kept. They are real clients (some have 100+ staff); only the industry label is a placeholder, so it's treated as unknown |

Rejected rows are written to the `mystaff_rejects` sheet with a reason.

## 6. Industry

The pipeline uses its **own two-level taxonomy**, built from the values actually present in the data. It does **not**
use the mock's 12 industries. Code: `INDUSTRY_GROUPS`, `INDUSTRY_SECTOR`, `UNCLASSIFIED_INDUSTRY` and `ROLLUP_MAP` in notebook §0b.

| Column | Content |
|---|---|
| `industry_raw` | Original source value |
| `industry` | **Industry group**: 18 groups (below) |
| `industry_sector` | Parent **sector** of the group: 6 sectors. Use it where a group has too few rows to score reliably. |

### 6.1 Why this taxonomy
* Both sources use HubSpot's industry list: HubSpot `Industry` has 84 values and MyStaff `Industry Hubspot` has 96. Together that is
  106 distinct values (74 shared, 10 HubSpot-only, 22 MyStaff-only).
* The values are heavily concentrated. Six values cover 53% of tagged rows, and more than 60 values have 5 rows or fewer, so they must be grouped.
* Accounting, Insurance, Legal and Real Estate stay as their own groups because they are distinct Cloudstaff verticals.
* The Cloudstaff `Industry Roll Up` (64 values) was **not** adopted as the taxonomy. It exists only in MyStaff, has
  near-duplicates, and has questionable assignments (e.g. Insurance → Comprehensive Financial Services, Legal Services → Professional Advisory).
  It is used only as a fallback (§6.3).

### 6.2 Industry groups → raw values

| Sector | Industry group | Raw values (HubSpot industry list) |
|---|---|---|
| Technology & Media | **Technology** | Information Technology and Services, Computer Software, Software Development, Information Services, Information Technology, Internet, Computer Networking, Computer & Network Security, Computer Hardware, Telecommunications |
| Technology & Media | **Marketing, Media & Creative** | Marketing and Advertising, Online Media, Media Production, Publishing, Printing, Graphic Design, Design, Photography, Broadcast Media, Entertainment, Performing Arts, Arts and Crafts |
| Property & Construction | **Real Estate** | Real Estate, Commercial Real Estate |
| Property & Construction | **Construction & Engineering** | Construction, Building Materials, Civil Engineering, Architecture & Planning, Mechanical or Industrial Engineering |
| Financial & Professional Services | **Accounting** | Accounting |
| Financial & Professional Services | **Financial Services** | Financial Services, Banking, Capital Markets, Investment Management, Venture Capital & Private Equity, Mortgage Broker |
| Financial & Professional Services | **Insurance** | Insurance |
| Financial & Professional Services | **Legal** | Legal Services, Law Practice |
| Financial & Professional Services | **Professional Services** | Management Consulting, Human Resources, Staffing and Recruiting, Executive Office, Translation and Localization, Market Research, Research, Think Tanks |
| Consumer, Hospitality & Services | **Retail & Consumer Goods** | Retail, Ecommerce, Wholesale, Apparel & Fashion, Textiles, Consumer Goods, Consumer Electronics, Cosmetics, Luxury Goods & Jewelry, Sporting Goods, Food & Beverages, Wine and Spirits, Food Production, Ranching |
| Consumer, Hospitality & Services | **Hospitality, Travel & Leisure** | Hospitality, Leisure, Travel & Tourism, Restaurants, Events Services, Sports |
| Consumer, Hospitality & Services | **Business & Consumer Services** | Facilities Services, Security and Investigations, Consumer Services, Individual & Family Services |
| Consumer, Hospitality & Services | **Non-profit & Public Sector** | Non-Profit Organization Management, Civic & Social Organization, Public Safety |
| Health & Education | **Healthcare & Wellness** | Hospital & Health Care, Medical Practice, Medical Devices, Mental Health Care, Pharmaceuticals, Alternative Medicine, Veterinary, Health, Wellness and Fitness |
| Health & Education | **Education & Training** | Education Management, E-Learning, Higher Education, Primary/Secondary Education, Professional Training & Coaching |
| Industrial, Logistics & Energy | **Manufacturing & Industrial** | Machinery, Industrial Automation, Electrical/Electronic Manufacturing, Motor Vehicle Manufacturing, Automotive, Chemicals, Packaging and Containers, Mining & Metals |
| Industrial, Logistics & Energy | **Transport & Logistics** | Logistics and Supply Chain, Transportation/Trucking/Railroad, Package/Freight Delivery, Maritime, Airlines/Aviation, Import and Export |
| Industrial, Logistics & Energy | **Energy & Environment** | Oil & Energy, Utilities, Renewables & Environment, Environmental Services |
| – | *(blank = unclassified)* | `-`, `Other`, `Outsourcing/Offshoring` |

**Unclassified values** are left blank:
* `-` and `Other` carry no information.
* `Outsourcing/Offshoring` is treated as unknown because 26 of the 27 MyStaff clients with this value have
  Roll Up = `CLOUDSTAFF`. That suggests Cloudstaff's own industry was stamped on the client by default.

### 6.3 Which value is used, per source

| Source | Rule |
|---|---|
| HubSpot | `Industry` → group |
| MyStaff | `Industry Hubspot` → group. If that is `-` / unclassified, fall back to `Industry Roll Up` → group via `ROLLUP_MAP`. Placeholder roll-ups (`CLOUDSTAFF`, `Test Record - No Category`, `Cloudstaff Test Account`, `-`, `No Info Available`, `Others`) stay blank. |
| Merged rows | MyStaff value; HubSpot value only if MyStaff is blank (§10) |

`industry_source` records which field supplied the value. In the current run:

| industry_source | Rows |
|---|---|
| MyStaff Industry Hubspot | 799 |
| MyStaff Industry Roll Up (fallback) | 240 |
| HubSpot Industry | 219 |
| HubSpot Industry (merged into a client) | 35 |
| Blank | 34 (all Organic Growth, 3.1%; New Logo 0%) |

A raw value that isn't in the taxonomy (e.g. a new HubSpot industry) stays blank and is flagged by a DQ warning (§13).
To handle it, add the value to `INDUSTRY_GROUPS` (or `ROLLUP_MAP`) and to the table above.

### 6.4 Result

| Industry group | New Logo | Organic Growth | Total |
|---|---|---|---|
| Technology | 35 | 209 | 244 |
| Real Estate | 21 | 173 | 194 |
| Construction & Engineering | 38 | 83 | 121 |
| Accounting | 18 | 82 | 100 |
| Financial Services | 15 | 76 | 91 |
| Retail & Consumer Goods | 24 | 65 | 89 |
| Professional Services | 2 | 64 | 66 |
| Marketing, Media & Creative | 4 | 61 | 65 |
| Manufacturing & Industrial | 10 | 55 | 65 |
| Healthcare & Wellness | 14 | 41 | 55 |
| Education & Training | 5 | 32 | 37 |
| Hospitality, Travel & Leisure | 8 | 28 | 36 |
| Legal | 6 | 24 | 30 |
| Business & Consumer Services | 6 | 20 | 26 |
| Transport & Logistics | 3 | 20 | 23 |
| Insurance | 2 | 21 | 23 |
| Energy & Environment | 5 | 16 | 21 |
| Non-profit & Public Sector | 1 | 6 | 7 |
| *(blank)* | 0 | 34 | 34 |

By sector: Property & Construction 315 · Financial & Professional Services 310 · Technology & Media 309 ·
Consumer, Hospitality & Services 158 · Industrial, Logistics & Energy 109 · Health & Education 92.

### 6.5 Borderline assignments (open to change)
These raw values could reasonably sit in another group. Each is a one-line change in `INDUSTRY_GROUPS`.

| Raw value | Assigned to | Alternative |
|---|---|---|
| Mechanical or Industrial Engineering | Construction & Engineering | Manufacturing & Industrial |
| Health, Wellness and Fitness | Healthcare & Wellness | Hospitality, Travel & Leisure |
| Food & Beverages, Wine and Spirits | Retail & Consumer Goods | Hospitality, Travel & Leisure |
| Import and Export | Transport & Logistics | Retail & Consumer Goods (wholesale) |
| Professional Training & Coaching | Education & Training | Professional Services |
| Consumer Services | Business & Consumer Services | (MyStaff Roll Up calls all 9 "Personal Care") |
| Printing | Marketing, Media & Creative | Manufacturing & Industrial |

## 7. Employee band

* Bands: `1-10`, `11-50`, `51-200`, `201-500`, `500+` (upper bounds inclusive).
* **Only real source data is used. Nothing is imputed.**
  * HubSpot `Number of Employees`, where `0` means unknown and is left blank.
  * MyStaff has no company headcount. A client gets a band only by merging with its HubSpot record (§10).
* HubSpot values look like range midpoints (10, 50, 250, 25, 200 and 1000 make up about 75% of rows), so treat the band as approximate.

## 8. Region

Output format follows the mock: `AU-<state>`, `NZ`, `UK`, `US`. The pipeline can also emit values the mock doesn't use (§12, A5).

**MyStaff:** office address country + state.
* Country names are normalised (e.g. `UNITED STATES OF AMERICA` → `US`, `Jersey` → `UK`).
* Australian states map to `AU-NSW`, `AU-VIC`, `AU-QLD`, `AU-SA`, `AU-WA`, `AU-ACT`, `AU-TAS` and `AU-NT`. If the state is unrecognised, the value is `AU`.
* Other countries get a short code (`CA`, `SG`, `HK`, `IE`, `AE`, `PH`), or `Other`.

**HubSpot:** there is no address field, so region comes from the **first** of these rules that applies:

| # | Evidence | Result | Rows |
|---|---|---|---|
| 1 | Country-code domain ending (`.au`, `.nz`, `.uk`, `.us`, `.ca`, `.ie`, `.sg`) | That country | 235 |
| 2 | Company name: `Pte Ltd` → SG, `Pty` → AU, or the name contains Australia / New Zealand / NZ / UK / Canada / Singapore | That country | 72 |
| 3 | Financial Reports text names exactly one non-US country (ASIC, ABN, `.gov.au`, Companies House, NZBN, …) and no US source (SEC, EDGAR, Delaware, …) | That country | 22 |
| 4 | Other non-US evidence: name ends in `Ltd` / `Limited` / `GmbH` / `PLC` / `BV` / `AG` / `ehf` / `ApS`, or the Financial Reports text names several non-US countries, or a non-US country alongside a US source | **Blank** (not US) | 12 |
| 5 | None of the above **and** the domain ends in `.com` | `US`, **assumed** | 125 |
| – | Generic ending (`.net`, `.org`, `.co`, `.io`, …) with no evidence | Blank | 18 |

HubSpot region is only Australian at **country** level (`AU`, no state).
`region_source` records which rule applied. Rule 5 is tagged `assumed: .com → US`.

## 9. Matching (HubSpot ↔ MyStaff)

Each HubSpot record is matched to at most one MyStaff client. The first rule that applies wins:

| Priority | Rule | `match_type` | Rows |
|---|---|---|---|
| 1 | MyStaff `CRM Company ID` = HubSpot `Record ID` | `CRM ID + domain` / `CRM ID` | 200 / 17 |
| 2 | Same normalised website domain, used by **one** MyStaff client | `Website domain` | 45 |
| 3 | Same domain shared by several clients, and exactly one has the same normalised name | `Website domain (name tie-break)` | 3 |
| 4 | Same domain shared by several clients, no unique name match | `Website domain (ambiguous)` | 2 |
| – | No ID or domain match | none | 217 |

* **Domain normalisation:** lowercase, strip protocol, `www.`, path, query and port.
* **Company name is not a match key.** If a HubSpot name equals a client's name but neither ID nor domain matches,
  the client name goes in `name_match_review` and the row stays New Logo (27 rows).
* A CRM ID carried by **more than one** MyStaff client is excluded from ID matching (currently `44331567279`,
  on RA Management NSW and TIA School of Allied Health).
* 45 domains are shared by several MyStaff clients (franchises / trusts, e.g. Barry Plant, Buxton, DPN, El Jannah).

## 10. Goal assignment and merge (survivorship)

| Case | Result |
|---|---|
| HubSpot record matched to a MyStaff client (rules 1–3) | **One row**, goal `Organic Growth`. The HubSpot row is removed (265 rows). |
| Ambiguous domain match (rule 4) | Goal `Organic Growth`, kept as its **own** HubSpot row; candidate clients listed in `note` (2 rows) |
| Unmatched HubSpot record | `New Logo` (217) |
| MyStaff client (matched or not) | `Organic Growth` (1,108) |

**Survivorship for merged rows.** The MyStaff record wins identity: `shortcode`, `account_id`, `company_name`, office region.

| Field | Winner |
|---|---|
| `industry` | MyStaff (including its Roll Up fallback); HubSpot only if MyStaff is still blank (35 rows filled) |
| `region` | MyStaff office address; HubSpot only if MyStaff is blank (0 rows needed it) |
| `employee_band` | HubSpot, the only source (233 rows filled) |
| `annual_revenue`, `hubspot_record_id`, `hs_company_name` | HubSpot |

If several HubSpot records match one client, the highest-priority match supplies values and all their record IDs are kept
(comma-separated) in `hubspot_record_id`. This does not occur in the current data.

**Result:** 1,327 rows: 217 New Logo, 1,110 Organic Growth (843 MyStaff only, 265 merged, 2 ambiguous).

## 11. Signals, scoring and routing (stages 7–10)

Settings for these rules are listed in [`PIPELINE.md` §5](PIPELINE.md).

### 11.1 Signals (stage 7, group `2_enrichment`)

| Column(s) | Source today | Notes |
|---|---|---|
| `seats_added_6m` | **Real: MyStaff** | Sum of MyStaff `Month to Date` + `Last Month` + `Month-2…Month-5 Movement Add` (≈ last 6 months). Organic Growth only; blank for New Logo |
| `web_visits_30d`, `team_builder_visit`, `form_fill_30d`, `news_signal`, `news_signal_date`, `job_postings_30d`, `hiring_spike`, `diamond_referral`, `prior_bpo_flag` | **MOCK** | Generated with the mock workbook's rules (below) |
| `industry_trend` | Mock values | `INDUSTRY_TREND` (A8) |

> **The mock signal values are fictional.** No real source is connected for them yet. They let scoring and routing run
> end to end on the real account list, and **must not be used to prioritise real accounts**.
> This is a deliberate, flagged exception to the project rule "never mix mock data with real client data"
> (`reference materials/CLAUDE.md`).

| Rule | Detail |
|---|---|
| Mode switch | `ENRICHMENT_MODE = "mock"`; `"live"` raises "not built" until real sources exist |
| Generator | Same rules as `reference materials/scripts/generate_mock_workbook.py`: a latent "intent" per account (Beta 1.05, 1.0) drives visits, Team Builder visits, form fills, news category and recency, job postings, hiring spikes, Diamond referral and Competitor client |
| Trigger rates (`MOCK_RATES`, 2026-11-13) | The workbook's own rates gave about a third of accounts a trigger (Diamond referral 16% of prospects, Team Builder visit and heavy visits 15% of clients). Tuned so about 10% of each list has one: visits = intent × 16 (was 26), Team Builder visit = intent × 0.055 (0.45), form fill = intent × 0.04 (0.28), job postings = intent × 15 (26), Diamond referral = 0.005 + intent × 0.045 (0.02 + intent × 0.25). News is unchanged. Current run: any trigger **8.3% New Logo, 9.5% Organic Growth**. New Logo: hiring spike 2.8%, funding / PE 2.8%, Diamond referral 0.9%, form fill 0.9%, heavy visits 1.4%, leadership change 0.9%. Organic Growth: Team Builder visit 2.1%, PE buyout 1.8%, funding 1.5%, heavy visits 1.4%, form fill 1.3%, restructuring 1.3%, leadership change 0.8%. Lower visit and job numbers also lower the website and news signals, so scores and tier cut-offs drop (Tier 1 from about 60 to 41–43) |
| Unknown rates | Same as the mock. Website unknown: New Logo 68%, Organic 28%. News/jobs unknown: New Logo 55%, Organic 38%. Diamond / Competitor: Yes / No / blank (New Logo), `N/A` (Organic Growth) |
| Reproducible | Random seed = `MOCK_SEED` (42) + `account_id`, so an account gets the same values on every run, whatever the row order |
| News dates | Relative to `SCORING_AS_OF` (the run date) |
| `industry_trend` | Mock trend values carried over from the workbook's industries to the matching industry group (e.g. Healthcare 0.8 → Healthcare & Wellness). Groups with no workbook equivalent (Professional Services, Business & Consumer Services, Manufacturing & Industrial, Energy & Environment, Non-profit & Public Sector) get no trend, so their modifier is 1.0 |
| Tagging | Every row: `enrichment_source = "MOCK signals (synthetic, seed=42); seats_added_6m real (MyStaff); assigned_team RANDOM (mock) unless an Act now trigger applies"` (the last part is added by routing, §11.3). The saved file is renamed `…_MOCK_SIGNALS.xlsx` |

`prior_bpo_flag` keeps the mock's column name but means **Competitor client**: a past client of a competing outsourcing
provider (the dashboard's definition). Former **Cloudstaff** clients are a different signal (win-back) and are not in this flag.

Real seat growth (current run, 1,108 MyStaff clients): **0 seats 751 (68%)**, 1–5 seats 320, 6–10 seats 19,
11+ seats 18. The 2 Organic Growth rows from shared HubSpot domains (§10) have no seat data, so they use the average seat signal of the clients that have it (0.097, about 1.9 of 20 points). Because most clients added no seats, Organic Growth scores are lower than in the dashboard mock,
which used made-up seat data.

**To go live**, replace the mock generator with real sources that return the same 9 columns (where to change the code:
[`PIPELINE.md` §8](PIPELINE.md)):

| Column(s) | Expected source (to confirm) | Join key |
|---|---|---|
| `web_visits_30d`, `team_builder_visit`, `form_fill_30d` | Website analytics / HubSpot activity | `website_domain`, `crm_company_id` |
| `news_signal`, `news_signal_date` | News scraper (`News Scraper/` at the repo root, already outputs both fields) | `company_name`, `website_domain` |
| `job_postings_30d`, `hiring_spike` | Job postings source (TBD) | `company_name`, `website_domain` |
| `diamond_referral`, `prior_bpo_flag` (Competitor client) | TBD (New Logo only) | `crm_company_id` |
| `industry_trend` | Industry news | `industry` |

### 11.1b Propensity signals (stage 7b, group `5_propensity`)

Fit scores from the **Client Propensity** project (`Client Propensity/`): how likely clients or prospects *like this one*
are to add seats or departments. Since v0.4 their **bands** feed the **Fit** points of `priority_score` (live profile
`dashboard_v3`, §11.2b) and the fit chips on the page (§11.4). Rules for the scores themselves: `Client Propensity/DOCUMENTATION.md`.

| `PROPENSITY_MODE` | Behaviour |
|---|---|
| `"real"` (default) | Reads the newest `*_Propensity_Extract_propensity_accounts.csv` and its `_prospect_profiles.csv` in `DATA_DIR` (Client Propensity's `run_pipeline.py` copies them there), plus `run_info` from the `.xlsx` for the model version, as-of date and AUCs |
| `"mock"` | **Synthetic** values, seeded per `account_id` (`MOCK_SEED`), with the real score bands' cut-offs. Fictional |
| `"off"` | The columns stay blank |

Independent of `ENRICHMENT_MODE`: either can be real or mock. A mock propensity run adds `_MOCK_SIGNALS` to the saved file
names, like mock signals do (`is_mock_run()`), and the dashboard's `meta.mock_signals` is true.

| Rows | Join | Columns filled |
|---|---|---|
| Organic Growth | `account_id` (`MS-<shortcode>`), left join, one-to-one (a duplicate fails). The extract's `shortcode` and `crm_company_id` are not taken: the dashboard keeps its own | `fit_seat_milestone` (the client's next seat milestone: 1–4 seats → 5, 5–9 → 10, 10–19 → 20; blank = 20+ seats, out of scope), `fit_seat_milestone_p` / `_band` / `_why`, `fit_dept_expand_*`, `fit_dept_vs_peers`, `fit_dept_why`, `depts_so_far` / `depts_so_far_names` (departments the client has had so far), `fit_second_dept_p` / `_band` (one-department clients only: the chance of a second department, banded among one-department clients), `likely_next_dept`, `likely_next_dept_by_lift`, `seats_change_6m_net`; `fit_growth_*` / `fit_reach_10_*` for clients under a year |
| New Logo | `industry` + `|` + country, from the prospect profiles. Country from `region` (`propensity_country()`): `AU*` Australia, US, UK, NZ, CA, blank = Unknown, anything else = Other. A blank industry = `Unknown` | `fit_growth_*`, `fit_reach_10_*`, `fit_branch_1y_*` (incl. `fit_branch_1y_why`), `likely_first_new_dept`, `fit_outlook` (the extract's `outlook`) |

* `fit_coverage` says why a row has no score. Organic Growth rows the extract doesn't have get `not in propensity extract`
  (today 24 of 1,110: 2 HubSpot-only rows, and clients newer than the extract's MyStaff file). New Logo rows get `prospect profile: <key>`.
* `propensity_source` on every row names the extract (date and model version), or the mock / off mode.
* The extract's own `industry` and `region` columns are not used here, so the dashboard's industry shows beside the fit scores
  (the scores were fitted on Client Propensity's MyStaff extract; see its DOCUMENTATION §3.2 for the industry mismatch).
* Checks (§13): `fit_*_p` within 0–1 and valid bands (error); `fit_second_dept_*` only on one-department Organic Growth
  clients (error); at least 95% of Organic Growth rows found, at least 70% scored, every New Logo row profiled, and the
  extract's as-of date within 45 days of `SCORING_AS_OF` (warn).
* The dashboard JSON carries the columns in every row (`DASH_ROW_FIELDS`) and `meta.propensity` (mode, source, as-of,
  model version, AUCs, band cut-offs, and `definitions`). The page shows them as Fit points and fit chips (§11.2b, §11.4).
* **What each score means** (`definitions`, from the extract's `score_definitions`): the question, who it applies to, the
  outcome and time window, the assumptions, the historical average, AUC and band cut-offs. Also saved as the
  `propensity_definitions` sheet of the output workbook. In mock mode the meanings are kept and the numbers blanked.

### 11.2 Scoring (stage 8, group `3_scoring`)

The formulas are the original Priority Score model's, the same ones `reference materials/data/accounts.csv` was scored with.
`workbook` below means those **original settings** (`reference materials/data/scoring_settings.json`). Four settings profiles
are in use; **`SCORING_PROFILE = "dashboard_v3"` is live** (v0.4): `dashboard_v2` plus a **Fit** component and new point
weights (§11.2b). `dashboard_v2` (live in v0.3) is the `dashboard` profile (live until v0.2) with the changes agreed in the
scoring review of 2026-11-10 (in bold below); everything in the `dashboard_v2` column still holds in `dashboard_v3` except the points:

| Setting | `workbook` (regression test only) | `dashboard` (until v0.2) | **`dashboard_v2` (v0.3; v0.4 = `dashboard_v3`)** |
|---|---|---|---|
| Max points, New Logo | website 35, news/jobs 35, Diamond 15, prior BPO 15 | website 40, news/jobs 40, Diamond 10, Competitor client 10 | same as `dashboard` |
| Max points, Organic Growth | website 50, news/jobs 50 | website 40, news/jobs 40, seat growth 20 | same as `dashboard` |
| Website signal | 0.4 × Team Builder visit + 0.3 × form fill + 0.3 × min(visits / 20, 1) | 0.5 / 0.25 / 0.25 | same |
| News / jobs signal | 0.6 × news strength × recency + 0.4 × hiring | 0.625 / 0.375 | same (**`dashboard_v3`: 0.5 / 0.5**, news 15 and hiring 15 points) |
| Seat growth signal | n/a | seats added in ~6 months: 0 → 0, 1–5 → 0.25, 6–10 → 0.5, 11+ → 1.0 | same |
| Unknown component (share of max) | website 35%, news/jobs 30% | 25% for website, news/jobs and seat growth | **the average signal of the same goal's accounts where the component is known** (25% only if none is known) |
| Signal rounding | each 0–1 signal rounded to 3 decimals | not rounded | not rounded |
| Act now triggers | the 4 workbook triggers | the 4, plus a prospect's Team Builder visit, a hiring spike or 18+ job postings (New Logo), 10+ website visits in 30 days with no form fill, restructuring / leadership-change news within 60 days | the same, with **20+** website visits and a **30-day** window for restructuring / leadership-change news |
| Act now bonus | none | +15 for the **first** trigger (+7.5 for a Diamond referral) | **every trigger family adds**: the best bonus in each family (Website, News, Hiring, Referral), sorted, the 2nd family × 0.5, the 3rd × 0.25 (e.g. 15 + 7.5 + 3.75) |
| Tier | Tier 1 ≥ 70 · Tier 2 ≥ 40 | same | **by rank within each goal**: top 10% Tier 1, next 30% Tier 2, the rest Tier 3 |
| Order (`sort_key`) | score + 1000 if hot | same | **the final score** |

**Why these changes** (scoring review, 2026-11-10):
* **Unknown = average.** A flat 25% put an account we know nothing about above one we checked and found weak, and the 25% wasn't
  tied to the data. Now an unknown component counts like a typical account of the same goal. A known zero still scores below
  an unknown (it is genuinely below average), but the gap is no longer arbitrary.
* **Rarer triggers.** Under `dashboard`, 39% of New Logo and 49% of Organic Growth accounts were "Act now", so the flag didn't
  single anything out. 20 visits is the point where visit volume already earns full credit (`vol_cap`).
* **Stacked bonus.** Independent evidence (e.g. a form fill **and** funding news) earns more than one trigger. Triggers in the same
  family measure the same thing (form fill, Team Builder visit and heavy visits are all website engagement), so a family counts once.
* **No +1000.** The +1000 put every account with a trigger above every account without one, so a weak account with a trigger
  outranked a strong account without one, and the bonus never changed the order between the two groups. Now the bonus does the
  ranking: Act now accounts rise by 15+ points but aren't pinned.
* **Percentile tiers.** Fixed cut-offs gave lists of very different sizes per goal (e.g. 49 Tier 1 of 1,110 Organic Growth). Rank-based
  tiers keep each tier a known share of its goal, so "Tier 1" means "top 10%" on both goals.

Shared by all profiles:

| Step | Rule |
|---|---|
| Hiring | 1 if hiring spike, else min(job postings / 20, 1). News/jobs is unknown only if news **and** postings are unknown |
| News strength | Funding round 1.0 · PE buyout 1.0 · M&A 0.8 · Expansion 0.7 · Restructuring 0.5 · Leadership change 0.3 · Other 0.3 · None 0 (checked, nothing found) |
| Recency | 0–30 days 1.0 · 31–90 0.7 · 91–180 0.4 · 181+ 0 |
| Points | signal × max, rounded to 1 decimal. Unknown → the profile's fill (average or baseline) × max, listed in `estimated_fields` |
| Unknown fill (`dashboard_v2`) | Calculated on each run from the accounts being scored, per goal, rounded to 3 decimals. Current run: website 0.261 (New Logo) / 0.280 (Organic Growth), news/jobs 0.283 / 0.320, seat growth 0.097 (Organic Growth). The website and news values come from mock signals |
| Diamond / Competitor | full points if `Yes`; blank counts as `No`; `N/A` for Organic Growth |
| Industry modifier | 0.9 + 0.2 × `industry_trend`; 1.0 when unknown |
| Score | `score_before_bonus` = min(100, round(base points × modifier)); `priority_score` = min(100, round(base × modifier + `act_now_bonus`)). Excel rounding (half away from zero) |
| Act now triggers | Checked in this order: Diamond referral (New Logo) → form fill → Team Builder visit (a client's; a prospect's in the dashboard profiles) → funding round / PE buyout within 30 days → *dashboard profiles:* hiring spike or 18+ job postings (New Logo) → heavy website visits with no form fill → restructuring / leadership-change news. `act_now_triggers` lists every one that applies; `hot_trigger` is the first, and it decides the team (§11.3) |
| Trigger families (`TRIGGER_FAMILY`) | Website: form fill, Team Builder visit, heavy website visits · News: funding round, PE buyout, restructuring, leadership change · Hiring: hiring spike · Referral: Diamond referral |
| Tier (`dashboard_v2`) | Rank of the final score within the goal: the share of the goal's accounts scoring strictly higher < 10% → Tier 1, < 40% → Tier 2. Equal scores share the higher tier, so a tier can be slightly larger than its share. The coverage cap for Tier 1 applies to the fixed-score rule only, and is off |
| `data_coverage` | share of max points backed by real data (information only) |
| `sort_key` | `dashboard_v2`: the final score. Older profiles: final score + 1000 if hot, so hot accounts sort first |

**Golden tests** (both must pass with 0 mismatches, or the notebook stops). They run the older profiles, so they prove the
shared formulas didn't change; the `dashboard_v2` additions are switched off by leaving their keys out of those profiles:

| Test | Reference | Result |
|---|---|---|
| Workbook profile | `reference materials/data/accounts.csv`: 400 mock accounts scored with the original settings | 15 columns, 0 mismatches |
| Dashboard **reference** profile (the `dashboard` profile without the extended triggers) | `data/account_priority_dashboard.json`: 800 accounts scored by the dashboard's `prep.py` | 10 columns (points, score before/after bonus, tier, trigger, estimated fields, sort key), 0 mismatches |

The dashboard JSON lost the news category `"None"` (checked, nothing found), because `prep.py` read the CSV with pandas' default
missing values. The test restores it where the dashboard still treats news as known.

**Effect of the review** (current run; mock signals, so for illustration only):

| | New Logo, `dashboard` | New Logo, **`dashboard_v2`** | Organic Growth, `dashboard` | Organic Growth, **`dashboard_v2`** |
|---|---|---|---|---|
| Act now share | 39.2% | **32.7%** | 48.7% | **33.9%** |
| Tier 1 / 2 / 3 | 5 / 49 / 163 | **22 / 71 / 124** | 49 / 355 / 706 | **117 / 330 / 663** |
| Lowest Tier 1 / Tier 2 score | 70 / 40 | **58 / 32** | 70 / 40 | **61 / 33** |

Accounts with more than one trigger family: 10 New Logo (bonuses of 18.75–26.25) and 34 Organic Growth (22.5). The top of each list barely
moves: of the top 50 per goal, 46 (New Logo) and 44 (Organic Growth) are in the top 50 under both profiles. Act now was still
far above the 10% target (`ACT_NOW_TARGET_SHARE`, a DQ warning) because the mock generator's website and Diamond rates were
too high; since 2026-11-13 the mock rates are tuned (§11.1, `MOCK_RATES`) and Act now is 8.3% / 9.5%.

Without the bonus no score can exceed 100 by points alone (each list's points total 100), but the industry nudge (up to ×1.08 with
today's trend values, ×1.1 at most) can lift a near-perfect account above 100 before the cap. The highest score before the bonus is 82;
one account reaches 100 with the bonus.

### 11.2b Fit points (`dashboard_v3`, live from v0.4)

Agreed 2026-11-13: the Client Propensity scores (§11.1b) are rolled into `priority_score` like the other signals, as a
**Fit** component (`fit_signal (0-1)`, `fit_pts`). Fit says whether accounts *like this one* grow; the other signals say
whether *now* is a good time. Settings: `FIT` and `SCORING_DASHBOARD_V3` (notebook §0b).

| Max points | Website | News / jobs | Seat growth | Diamond | Competitor client | **Fit** |
|---|---|---|---|---|---|---|
| New Logo (`dashboard_v2` → **`dashboard_v3`**) | 40 → **30** | 40 → **30** (news 15, hiring 15) | – | 10 | 10 | **20** (profile growth 15, second department 5) |
| Organic Growth | 40 → **30** | 40 → **30** (news 15, hiring 15) | 20 → **15** | – | – | **25** (seat milestone 15, second department 10) |

News and hiring were 0.625 / 0.375 of the News and jobs points (18.75 / 11.25 of 30); evened out to 15 / 15 on 2026-11-13,
together with New Logo fit 15 / 5 (was 14 / 6).

Seat growth drops to 15 because the seat-milestone fit already uses recent seat adds (rank correlation 0.53 with
`seats_added_6m`), so keeping 20 would count recent growth twice.

| Rule | Organic Growth | New Logo |
|---|---|---|
| Parts (weight) | **Next seat milestone** (0.6): `fit_seat_milestone_band`, the band of the client's next milestone (1–4 seats → 5+, 5–9 → 10+, 10–19 → 20+) within 12 months. **Second department** (0.4): `fit_second_dept_band`, **one-department clients only** (the goal: clients that start with one department and grow past it). Clients with 2+ departments score **0** on it (`multi_dept_value`) with the weights kept, so their fit is at most 15 of 25 points (2026-11-13) | **Profile growth** (0.75 = 15 points): the better of `fit_growth_band` (5+ seats in 1 year) and `fit_reach_10_band` (10+ in 2 years). **Second department** (0.25 = 5 points): `fit_branch_1y_band`. All for the prospect's industry \| country, *if we sign them* |
| Band → share of the part | High 1.0 · Medium 0.5 · Low 0 (`FIT["band_value"]`) | same |
| A part without a score | The other part counts alone (e.g. 1 department with 20+ seats: the second department alone). The 47 clients with 20+ seats and 2+ departments have no seat milestone, so their fit is unknown (average) | same |
| No fit at all | Unknown component: the average fit of the goal's known accounts (`unknown_fill`), listed in `estimated_fields` as "Fit". Mostly the 260 clients with no current seats, plus 67 with no known starting department, 24 not in the extract, and 47 with 20+ seats and 2+ departments. Current run: 0.414 × 25 = 10.4 points | Every row has a prospect profile. Average (fallback only): 0.498 |
| Bands | Relative: High = top third of past clients (per seat range for milestones; among one-department clients for the second department) | Top third of past new clients |

**Fit chips** (Why column, kind `fit`): one chip per score whose band is `FIT["chip_band"]` (High) **and** whose chance
is at least `FIT["chip_min_lift"]` (1.5) × the score's usual rate (its historical base rate, from the extract's score
definitions). The band alone isn't enough, because bands are relative: the top third of 1–4 seat clients starts at a 5%
chance, below the usual 7% (44 of 216 High clients were below it), and New Logo profiles barely differ from average (High
5+ seats: 8.3–10.7% against a usual 9.6%; High 10+: 3.4–5.2% against 4.6%), so no New Logo seat chip clears 1.5× of
the past-client rate. **New Logo "Likely 5+ seats" therefore compares a prospect with the average prospect on the list**
(`FIT["New Logo"]["growth_compare"] = "prospects"`; today 5.7%, so the chip needs ≥ 8.6%): a like-for-like comparison,
since every prospect is scored the same way (unknown role, launch of 1–2 staff). Its card names that comparison, shows the
prospect's industry · country profile and the past new-client rate (9.6%) for context. 10+ seats and 2nd department still
compare with past clients.
The chip shows the multiple (e.g. "2.3×"). Hovering or focusing it opens a card: the chance, a bar with the usual rate
marked, the multiple, the "why", for departments the departments now / often added next / unusually likely, and the
comparison group. The chips are built by `fit_chips()` (stage 11, hover data as a dict) and only appear when the profile
scores fit. **The Fit points still use the bands** (a High New Logo profile earns full fit points at a near-average chance; open item §15.13).

| Chip | Organic Growth | New Logo |
|---|---|---|
| Likely 5+ / 10+ / 20+ seats | Next seat milestone band High (1–4 seats → 5+, 5–9 → 10+, 10–19 → 20+) | 10+ in 2 years High, else 5+ in 1 year High (only the larger one) |
| Likely 2nd department | One department so far and `fit_second_dept_band` High. Hover: the department held, the most common next departments, the unusually likely ones (lift) | `fit_branch_1y_band` High. Which department can't be predicted before the starting role is known |
| *(no chip)* | Clients with 2+ departments get no department chip (2026-11-13; the earlier "Likely new department" chip was removed) | – |

**Effect** (current run; mock timing signals, so tiers are for illustration only). Tier 1 / 2 / 3: New Logo 22 / 71 / 124
→ **24 / 65 / 128**; Organic Growth 117 / 330 / 663 → **122 / 326 / 662**. Fit points average 10.0 of 20 (New Logo) and 13.7
of 25 (Organic Growth). Accounts changing tier: 30 New Logo, 164 Organic Growth. Of the top 50 per goal, 43 (New Logo) and 35
(Organic Growth) stay in the top 50. Fit chips today (High and ≥ 1.5× usual): Organic Growth 115 "Likely 5+ seats", 22
"10+", 7 "20+", 84 "2nd department" (after the 180-day department launch rule in Client Propensity v1.2: departments
first staffed in a client's first 6 months count as its launch, not as a second department; the card says so); New Logo 20 "5+ seats" (vs the average prospect: Technology US, Hospitality AU / US,
Education AU, Financial Services US) and 8 "2nd department" (High band alone would give 216 / 33 / 10 / 115 and New
Logo 29 / 22 / 81). With the department part limited to one-department clients (2+ departments score 0 on it), average fit
points are 11.8 of 25 for one-department clients (max 25) and 9.2 for 2+ department clients (max 15); the unknown-fit
average is 10.4 (0.414 × 25). Organic Growth tiers: 111 / 345 / 654.

### 11.3 Routing (stage 9, `assigned_team`, `rank_in_team_list`)

Teams are the mock dashboard's three roles (`work/account_priority_dashboard/account_roles.csv`). The goals each may own are enforced by a DQ check:

| Team | New Logo | Organic Growth |
|---|---|---|
| **BDM** | ✓ | ✓ |
| **Marketing** | ✓ | ✓ |
| **SDR** | ✓ | – |

Routing has two steps.

**1. An account with an Act now trigger goes to the team of its first trigger** (`hot_trigger`, `TRIGGER_TEAM`), whatever the routing mode.
Every trigger family earns a bonus (§11.2); the bonus column is the trigger's own bonus and its family.

| Trigger | New Logo | Organic Growth | Bonus (family) |
|---|---|---|---|
| Diamond referral | BDM | – | +7.5 (Referral) |
| Form fill | BDM | BDM | +15 (Website) |
| Team Builder visit | **SDR** (a prospect's visit) | BDM (a client's visit) | +15 (Website) |
| Funding round / PE buyout (last 30 days) | BDM | BDM | +15 (News) |
| Hiring spike or 18+ job postings | **SDR** | – | +15 (Hiring) |
| 20+ website visits in 30 days, no form fill | **Marketing** | **Marketing** | +15 (Website) |
| Restructuring / leadership-change news (last 30 days) | **Marketing** | **Marketing** | +15 (News) |

A trigger that isn't in the table goes to BDM; a DQ warning flags it.

**2. Every other account follows `ROUTING_MODE`.** `"random"` is live.

*Random assignment (mock).* The mock dashboard's own role assignment (`work/account_priority_dashboard/make_mock_data.py`):
a **seeded random draw** with set probabilities per account type. The same account gets the same team on every run, whatever the
row order. It is a stand-in for real owner assignment, so it is **mock data**, and every row is tagged
`assigned_team RANDOM (mock) unless an Act now trigger applies` in `enrichment_source`.

| Account type (no trigger) | BDM | Marketing | SDR |
|---|---|---|---|
| Organic Growth | 70% | 30% | – |
| New Logo in the **top 10% by score of the prospects without a trigger** (`BDM_TOP_SHARE`; ranked like the tiers, ties share the place; today a score of 36 or more) | 80% | 20% | – |
| Other New Logo | – | 40% | 60% |

Diamond referrals always have a trigger, so they never take part in the draw (the mock dashboard sent 85% of them to SDR).

**Why the top 10% and not a fixed score** (2026-11-13). The workbook used a fixed 60 (`BDM_MIN_SCORE`, still used by the
workbook golden test). Once the mock trigger rates were tuned (§11.1), the highest New Logo score without a trigger was 44, so
no prospect without a trigger could reach BDM and BDM's New Logo list held only the 10 triggered accounts. A relative cut-off
keeps working as score levels change (mock → real signals). Today it is a score of 36 (`bdm_min` on the page shows it), and
BDM's New Logo list has 24 accounts: 10 with a trigger and 14 from the draw.

*Deterministic rules (`ROUTING_MODE = "rules"`).* For accounts without a trigger, the first rule that applies. There is **no**
"no data → Marketing" rule:

| # | Rule | Team |
|---|---|---|
| 1 | Top 10% by score of the goal's accounts without a trigger (`BDM_TOP_SHARE`) | BDM |
| 2 | Organic Growth in Tier 3 | Marketing |
| 3 | Other New Logo | SDR |
| 4 | Other Organic Growth (Tier 2) | BDM |

The draw and the rules use the final score (after the Act now bonus); the trigger step doesn't use the score. The workbook routed all Organic Growth to AM, which isn't one of the
three roles, so neither mode follows it.

`rank_in_team_list` is the position within each **team × goal** list, by `sort_key`: the final score in `dashboard_v2`
(older profiles: accounts with a trigger first, then by score). Ties share a rank, as in the workbook.

Current run (mock signals + real seat growth, so for illustration only): 447 accounts have a trigger (626 under `dashboard`).

| Team | New Logo | Organic Growth | Total |
|---|---|---|---|
| BDM | 48 | 782 | 830 |
| Marketing | 73 | 328 | 401 |
| SDR | 96 | – | 96 |

| First trigger (current run) | Accounts | Team |
|---|---|---|
| Team Builder visit | 138 client + 6 prospect | BDM / SDR |
| Form fill | 9 New Logo + 103 Organic Growth | BDM |
| Heavy website visits (20+, no form fill) | 7 New Logo + 102 Organic Growth | Marketing |
| Diamond referral | 35 | BDM |
| Funding round / PE buyout (30 days) | 4 New Logo + 22 Organic Growth | BDM |
| Restructuring / leadership change (30 days) | 1 New Logo + 11 Organic Growth | Marketing |
| Hiring spike | 9 | SDR |

The tighter heavy-visits and restructuring / leadership thresholds moved about 180 accounts back into the random draw (mostly heavy website visits, 273 → 109), which is why BDM's
Organic Growth list grew and Marketing's shrank. Tiers are set per goal, not per list, so a list's tier mix depends on who is on it:
of the 117 Tier 1 Organic Growth accounts, 108 are with BDM.

### 11.4 What the dashboard shows (stage 11)

The Account Priority Dashboard shows each account on one of **5 lists**: Marketing × (New Logo, Organic Growth), SDR × New Logo,
and BDM × (New Logo, Organic Growth). The data format and build are in [`PIPELINE.md` §6](PIPELINE.md).

| What the page shows | Rule |
|---|---|
| Score and tier | The final `priority_score` and `tier` (after the Act now bonus). The page also shows the score **before** the bonus (`workbook_score`) and its tier with the same rule (`workbook_tier`). Tier text shows the rule (top 10% / next 30%) and today's lowest score per tier and goal (`meta.tier_cutoffs`) |
| Order within a list | By `sort_key`: the final score (Act now bonus included). Older data with `hot_first` puts Act now accounts first |
| Name on the page | The page calls Act now triggers **trigger events** ("A recent event that makes now a good time to engage: reach out (BDM, SDR) or target with a campaign (Marketing).") and the Act now bonus the **trigger bonus**. Code and data keep the `hot_trigger` / `act_now_*` names |
| Trigger event card (glossary) | Lists every trigger with its window or threshold (from the data), how bonuses stack, and which team owns it (from the pipeline's `TRIGGER_TEAM`). The list's Act now column shows every trigger (`act_now_triggers`) |
| Unknown values | The page states the average used for each unknown component and goal (`meta.unknown_fill`) |
| "Why" chips | Website / Team Builder visit, news (or hiring), seat growth, "Growing industry" (trend ≥ 0.7), Diamond referral, Competitor client, and "No … data" for estimated components. Strength dots: ●●● ≥ 66% of the signal, ●●○ ≥ 33%, ●○○ otherwise |
| Fit chips | Green chips with a seedling icon and a dashed border: "Likely 5+ / 10+ / 20+ seats", "Likely 2nd department", "Likely new department" (§11.2b). Hovering (or focusing) one shows the chance, what High means and why. A "Likely to grow" KPI counts the list's accounts with any fit chip. The CSV adds `fit_pts` and the fit chips with their hover text. The glossary, the points tables, the method steps and the worked example include Fit |
| Mock marking | While signals are mock, every chip from a mock signal ends in **"· mock"**. Seat growth and fit chips are real (fit chips get the tag only when `PROPENSITY_MODE = "mock"`), so they don't. The subtitle and the warning banner say the signals are mock |
| Profile line | "industry · size · region", with "unknown" for blanks |
| "With us" column (Organic Growth lists only) | One cell grouping the client's relationship with us: **current seats** (MyStaff `Total Staff`, `cs_staff_current`), **seats added in the last 6 months** (`seats_added_6m`, shown when above 0), and **time as a client** (`client_years`: as-of date minus MyStaff `Date of First Staff Engagement`, shown as months under a year, else years, plus "since <month>"). When the date is blank (15 clients, mostly with no staff yet), MyStaff's own `Tenure` band is shown instead, marked "(MyStaff)". Sorts by seats. The CSV adds current seats, client since and time as client |
| Workbook comparison | The same accounts scored with the **workbook** settings, for the page's "what the rounded points and seat growth change" charts |
| Organic Growth flags | Diamond / Competitor are not applicable: shown as no flag and 0 points |

The built page contains every account row, so it is handled as confidential data (§14).

## 12. Prototype assumptions

| # | Assumption | Evidence / risk | How to undo |
|---|---|---|---|
| A1 | `.com` with no other country evidence → `US` | Tested on MyStaff clients with a known office: `.com` is US 68% of the time and Australian 21%. Country-code endings are ~100% correct. The HubSpot pool is AU-heavy, so the real error rate may be higher. | Remove `ASSUMED_TLD`, or filter `region_source == "assumed: .com → US"` |
| A2 | Name and Financial Reports keywords indicate country | Keyword matching, so occasional false hits are possible. Rule 3 needs exactly one non-US country and no US source, so unclear cases fall to blank. | Edit `NAME_COUNTRY` / `REPORT_COUNTRY` |
| A3 | HubSpot `Number of Employees` is accurate enough for banding | Values look like enrichment ranges | n/a |
| A4 | Industry taxonomy (§6): 18 groups / 6 sectors, with `Outsourcing/Offshoring` treated as unknown | Built from the observed values. Borderline assignments are listed in §6.5 | Edit `INDUSTRY_GROUPS` / `UNCLASSIFIED_INDUSTRY` |
| A5 | Region values outside the reference list (`REF_REGIONS`) are kept (`AU` without state, `AU-ACT/TAS/NT`, `CA`, `SG`, `HK`, `IE`, `AE`, `PH`, `Other`) | More faithful than forcing them into 8 regions. DQ reports it as a warning. | Map or blank them in standardize |
| A6 | Exports are current, complete snapshots | The MyStaff export is active clients only | Confirm with production DB/API extracts |
| A7 | **Signals other than seat growth are synthetic** (mock generator rules) | Fictional. Scores, tiers and team lists are for testing the pipeline only | Build live sources; set `ENRICHMENT_MODE = "live"` |
| A8 | `industry_trend` per industry group = the workbook's mock trend for the nearest workbook industry; groups without one get no modifier | Mock values in the workbook too ("would come from Positive Industry News") | Replace `INDUSTRY_TREND` with real industry-news scores |
| A9 | **Accounts without an Act now trigger get a seeded random team** (BDM / Marketing / SDR), using the mock dashboard's probabilities. Accounts with a trigger go to the trigger's team (§11.3) | Fictional: a stand-in for real owner assignment. Without a trigger the team doesn't depend on the score | `ROUTING_MODE = "rules"` for deterministic rules (no "no data → Marketing" rule), or edit `ROUTING_PROBABILITIES` |
| A10 | Live scoring uses the **`dashboard_v2`** settings: the dashboard's round points and seat growth (from `work/account_priority_dashboard/score_adjustments.json`), plus the 2026-11-10 review (average fill, stacked bonus, rarer triggers, percentile tiers, no +1000) | Weights, the 0.5 stacking factor and the 10% / 30% tier shares are judgement calls, not yet validated against outcomes | `SCORING_PROFILE = "dashboard"` (previous) or `"workbook"`, or edit `SCORING_DASHBOARD_V2` |
| A13 | Tiers are **relative** (top 10% / next 30% of each goal) | A tier says how an account ranks, not how strong it is: if every account is weak, the top 10% is still Tier 1. Cut-offs move between runs | Set `tier` in `SCORING_DASHBOARD_V2` back to fixed scores (`_TIER`) |
| A15 | **Fit** (25 Organic Growth / 20 New Logo points) comes from Client Propensity **bands** (High 1 / Medium 0.5 / Low 0), weighted seat 0.6 / department 0.4 (Organic Growth) and growth 0.75 / department 0.25 (New Logo; 15 / 5 points). News and hiring are 15 / 15 points of News and jobs | The points and weights are agreed judgement calls, not fitted. Bands are relative (top third of past clients). New Logo fit depends on industry and country only, and the dashboard's MyStaff industry is out of line today (Client Propensity DOCUMENTATION §3.2), which affects the "why" text, not the score. The New Logo department band leans High (81 of 217) | `SCORING_PROFILE = "dashboard_v2"` (no fit), or edit `FIT` / `SCORING_DASHBOARD_V3` |
| A14 | Unknown components are scored at the **average of the known accounts** of the same goal | While website and news signals are mock, so is their average. If data is missing for a reason linked to intent (e.g. untracked visitors are less engaged), the average overstates them | `unknown_fill = "baseline"` in `SCORING_DASHBOARD_V2` |
| A11 | Seat growth = **gross** staff added (MyStaff `Movement Add`), month to date + 5 previous months | Gross adds include replacements for staff who left, so they can overstate growth. `Movement Net` is the alternative | Change `SEAT_WINDOW` / the sum in `standardize_mystaff()` |
| A12 | `prior_bpo_flag` = Competitor client (past client of a competing outsourcing provider) | Dashboard definition; no real source yet | Rename / redefine in `SCORING_DASHBOARD` and §11.1 |

## 13. Data quality checks

| Check | Stage | Level |
|---|---|---|
| `account_id` unique | 6 | error |
| Every HubSpot record accounted for (as a row or inside a merged row) | 6 | error |
| Every active MyStaff client present | 6 | error |
| No company duplicated via CRM ID (ignoring IDs already shared inside MyStaff) | 6 | error |
| `goal`, `employee_band` within the reference values (`GOALS`, `REF_BANDS`) or blank | 6 | error |
| `industry` is one of the 18 industry groups (or blank); `industry_sector` set wherever `industry` is | 6 | error |
| No unrecognised raw industry values (new values missing from the taxonomy) | 6 | warn |
| `region` within the reference list (`REF_REGIONS`) | 6 | warn (currently fails, see A5) |
| Signal and scoring columns empty before stage 7 (except real `seats_added_6m`) | 6 | info |
| Workbook and dashboard golden tests: 0 mismatches | 8 | error (assert) |
| `assigned_team` is BDM / Marketing / SDR, and SDR owns New Logo only | 10 | error |
| `priority_score` within 0–100; `tier` valid | 10 | error |
| Act now bonus only on hot accounts, and never lowers the score | 10 | error |
| Every account with an Act now trigger is on that trigger's team | 10 | error |
| `hot_trigger` is the first of `act_now_triggers`; no triggers listed without a `hot_trigger` | 10 | error |
| Act now on at most 10% of each goal's accounts (`ACT_NOW_TARGET_SHARE`) | 10 | warn (passes since the mock rates were tuned: 8.3% / 9.5%; was 32.7% / 33.9%) |
| Tier 1 share per goal within 5 points of the target (percentile tiers) | 10 | info |
| Every trigger that fires has an entry in `TRIGGER_TEAM` | 10 | warn |
| Diamond / Competitor are `N/A` for Organic Growth | 10 | error |
| Seat growth scored for Organic Growth only | 10 | error |
| Fit points within 0 and the goal's fit maximum (profiles with fit) | 10 | error |
| Fit known from the propensity extract (share per goal) | 10 | info (currently New Logo 100%, Organic Growth 67%) |
| Every team × goal list ranked from 1 | 10 | error |
| Every row has an `enrichment_source` | 10 | error |
| Seat growth known for Organic Growth rows (>90%) | 10 | info (currently 1,108 of 1,110: every MyStaff client; the 2 shared-domain HubSpot rows have none) |
| Enrichment uses real data | 10 | warn (currently fails: signals other than seat growth are mock) |
| One dashboard row per account; every row on one of the 5 shown lists | 11 | error |
| Every row has every field the page reads; every setting and `meta` key the page reads is present (incl. the fit settings) | 11 | error |
| Every fit chip carries its hover text | 11 | error |
| Worked-example account exists; list sizes add up to all accounts | 11 | error |
| Dashboard data is strict JSON (no NaN, dates or numpy types) | 11 | error |
| Required `meta` keys, settings keys and row fields present (checked again by `build_dashboard.py` before building) | part 2 | error (stops the build) |
| Built page renders with no JavaScript errors (`check_page.py`, optional) | part 2 | manual |

A failed **error** check stops the pipeline.

## 14. Data handling

* The MyStaff export is **confidential**. Raw inputs and the output workbook live in
  `~/Desktop/Projects/Marketing Intelligence Priority/Data`, **outside the git repo**.
* The notebook is committed **without outputs**. Clear outputs before committing.
* The processed data (Excel output and dashboard JSON) is saved **locally**, in the same data folder as the raw files.
  The file names and sheets are in [`PIPELINE.md` §9](PIPELINE.md).
* **While signals are mock, every output file name ends in `_MOCK_SIGNALS`**, so a file with synthetic signals never looks like a real one.
* **The dashboard page embeds every account row** (client names, scores, owners), so it is written to the same local data
  folder, **outside the repo**. As a safety net, the repo's root `.gitignore` still excludes `Marketing Intelligence/outputs/html/*.html`.

## 15. Open items

1. Review the 27 `name_match_review` rows. Several look like existing clients with a second HubSpot record.
2. Resolve the 2 ambiguous franchise-domain rows (`prd.com.au`, `ybr.com.au`).
3. Confirm the borderline industry assignments (§6.5). Of the 27 `Outsourcing/Offshoring` clients, 19 got an industry from their merged HubSpot record; decide whether the other 8 need a manual industry.
4. Replace assumption A1 with a real country field (HubSpot `Country` property, if populated) when extracting via the API.
5. Get state-level region for Australian HubSpot companies (needs an address field).
6. Connect real enrichment sources (§11.1), starting with the news scraper, which already produces `news_signal` / `news_signal_date`.
7. Replace the random team assignment (A9) with real owners (HubSpot ownership, MyStaff account managers), or agree deterministic rules with Sales and Marketing (`ROUTING_MODE = "rules"`).
8. Map `industry_trend` for the 5 industry groups that have no workbook equivalent (A8).
9. Decide gross vs net seat growth (A11).
10. Former Cloudstaff clients in the New Logo list (about 130 name matches): add a win-back signal or route them separately. They are not "Competitor client" (A12).
11. Act now is about 10% of each goal with the tuned mock rates (it was a third). Recheck with real website signals; if it is high, tighten the
    direct triggers too (e.g. Team Builder visit only with a form fill or 2+ visits) or set the heavy-visits threshold by percentile.
12. Validate the weights, the stacking factor (0.5) and the tier shares (10% / 30%) against outcomes (closed-won deals for New Logo,
    seat adds in the next 90 days for Organic Growth) once real signals are connected.
13. Later stages agreed in the review: **fit** is now in the score as points (§11.2b, v0.4); still open: New Logo Fit points (High profiles earn full points at near-average chances, §11.2b: base points on lift,
    or shrink New Logo fit), a fit × timing grid for Marketing, fit in routing, a 1–4 seats → 10+ score for existing clients, and **negative** signals for
    clients (seat losses, disengagement risk).
