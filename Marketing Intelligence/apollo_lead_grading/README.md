# apollo_lead_grading: grade Apollo leads with the Priority Score

**Status (18 Nov 2026):** working prototype, run by hand. First input: two Apollo lists (UK care homes, UK cybersecurity), 230 companies, 339 contacts. Output: a standalone **EMEA Lead Grades** dashboard, one list owned by **BDM Marketing**. Not committed yet.

This README is the handoff: what it does, how to run it, every rule and why, what the first run found, and what's open. [PLAN.md](PLAN.md) holds the original design and decision log; where the two differ, this file is current.

---

## 1. What it does

Apollo gives us leads that are **not in HubSpot yet**. This grades them so BDM Marketing works the best ones first, from three kinds of information:

| Kind | Source | Used for |
|---|---|---|
| **What Apollo has** | Apollo contact export | Website, industry, activity codes (US SIC / NAICS), staff, revenue, city, latest funding type, parent company, software stack, contacts |
| **What we gather** | `News Scraper` (repo root) | Dated news events (with details), parent companies' news, open jobs and their dates, Companies House status and changes, the website's description |
| **What we know internally** | MyStaff and HubSpot (priority list), Client Propensity, Staff Central, candidates' CVs | Existing clients (gate), fit from past clients, roles Cloudstaff fills, competitor clients |

The score is the **live Priority Score code** (`../format data/priority_scoring.py`, profile `dashboard_v3`, New Logo), without the parts that need HubSpot (§4.2).

## 2. How the pieces fit

```
<Data>/EMEA/apollo-contacts-export*.csv
        │
        ├─► News Scraper/apollo_emea/prepare.py ─► companies.csv, parents.csv
        │        ▼  News Scraper: filings · run (news) · jobs · run parents · nlp run · export
        │   News Scraper/apollo_emea/out/company_summary.csv, signal_events.csv   (+ apollo_emea/data/news.db)
        │        │
        └────────┴─► Marketing Intelligence/apollo_lead_grading/grade_leads.py
                         ▲  priority list (MyStaff / HubSpot identity) · Client Propensity profiles
                         │  Staff Central JP titles (roles.py) · competitor_clients.csv (Client Extraction)
                         │  News Scraper industry_trend.csv (context only)
                         ▼
          <Data>/lead_grades_apollo_emea.xlsx + .json ─► build_dashboard.py ─► <Data>/<date>_EMEA_Lead_Grades.html
```

- **News Scraper collects; Marketing Intelligence grades.** Apollo runs use their own database (`News Scraper/apollo_emea/data/news.db`). The scraper's code changed in one place for this work: its event classifier (`classify.py`, `event_examples.py`) gained two categories and the phrasings it was missing (§7.2). That change applies to every list it runs on.
- **Join keys:** the Apollo account id, `apollo-<id>` in the scraper and `AP-<id>` here; parents are `parent-<domain>`.
- `<Data>` = `~/Desktop/Projects/Marketing Intelligence Priority/Data`. **Everything written there stays out of the repo**: grades, contacts and the built page (it embeds names and emails).

## 3. Run it

The repo's `.venv` (Python 3.12) with the `nlp` dependency group (spaCy, sentence-transformers) and Playwright Chromium; all installed on this machine. `…` = `../.venv/Scripts/python.exe -m news_scraper`.

| # | Step | Run from | Command | Time (230 cos) |
|---|---|---|---|---|
| 1 | Apollo → scraper lists | `News Scraper` | `../.venv/Scripts/python.exe apollo_emea/prepare.py "<Data>/EMEA"` | seconds |
| 2 | Companies House + Gazette | `News Scraper` | `… filings --companies apollo_emea/data/companies.csv --registers uk --db apollo_emea/data/news.db` | ~5 min (monthly files cached in `data/registers/`) |
| 3 | News | `News Scraper` | `… run --companies apollo_emea/data/companies.csv --db apollo_emea/data/news.db --read-articles --read-max-per-company 5` | ~20 min first time, then only new articles |
| 4 | Jobs | `News Scraper` | `… jobs --companies apollo_emea/data/companies.csv --db apollo_emea/data/news.db` | ~10 min (incl. browser pass) |
| 5 | Parent companies' news | `News Scraper` | `… run --companies apollo_emea/data/parents.csv --db apollo_emea/data/news.db` | <1 min |
| 6 | Event details | `News Scraper` | `… nlp run --db apollo_emea/data/news.db --scope company --stages entities,events` | ~20 s |
| 7 | Export | `News Scraper` | `… export --db apollo_emea/data/news.db --out apollo_emea/out --lookback-days 365` | ~1 min |
| 7a | CQC register (care, England) | `News Scraper` | `../.venv/Scripts/python.exe apollo_emea/cqc.py --download` | ~30 s (+3 min per new monthly file) |
| 7b | Public contract awards | `News Scraper` | `../.venv/Scripts/python.exe apollo_emea/contracts.py` | ~15 min first time, then ~1 min |
| 7c | Ownership (Companies House PSC register) | `News Scraper` | `../.venv/Scripts/python.exe apollo_emea/ownership.py --download` (after 2 and 7a) | ~2.6 GB download and ~10 min the first time per snapshot; then ~1 min |
| 8 | Competitor-client map (when the CV export is refreshed) | `Client Extraction (CS Jobs)` | run `competitor_client_extraction.ipynb`, then `../.venv/Scripts/python.exe export_client_map.py` | ~3 min |
| 9 | UK market trend (weekly, optional; context only) | `News Scraper` | `… segment run --groups "Technology;Healthcare & Wellness" --countries UK`, then `… segment export` | ~2 min |
| 10 | Grade | `Marketing Intelligence` | `../.venv/Scripts/python.exe apollo_lead_grading/grade_leads.py` | ~30 s |
| 11 | Build the page | repo root | `.venv/Scripts/python.exe .claude/skills/cs-dashboard/scripts/build_dashboard.py --template "Marketing Intelligence/apollo_lead_grading/dashboard_template.html" --data "<Data>/lead_grades_apollo_emea.json" --out "<Data>/{date}_EMEA_Lead_Grades.html"` | seconds |
| 12 | Check the page | repo root | `.venv/Scripts/python.exe .claude/skills/cs-dashboard/scripts/check_page.py "<Data>/<file>.html"` (every page must print `errors: []`) | ~1 min |

- **After changing the scraper's rules** (classifier, overrides), re-run step 7 then 10–12; no new scraping is needed.
- **Jobs:** re-run step 4 after 21+ days and a hiring spike becomes measurable.

### Review loops (a person, or Claude, marks; the next run uses it)
| What | Where | How |
|---|---|---|
| A company name that matched someone else ("The Fed", "Titania") | `News Scraper/apollo_emea/overrides.csv` | `ambiguous = yes`; re-run step 3 for those companies, then 7 |
| An event with the wrong type | `event_overrides.csv` (here) | company, start of the headline, correct category, `labelled_by` |
| A CQC or contract match made on a name only ("Check match" chip, "needs review" badge) | `register_match_reviews.csv` (here) | company_name, source (`CQC register` / `Find a Tender`), notice (Find a Tender id; blank for CQC), verdict `confirmed` (flag cleared) or `rejected` (match dropped), reviewed_by, reviewed_on, note. Flagged matches score until rejected |
| An event the classifier missed | `manual_events.csv` (here) | company, date, category, headline, url, publisher, `labelled_by`, note |
| A missed phrasing that will recur | `News Scraper/news_scraper/event_examples.py` (+ `classify.py` rules) | then check `News Scraper/eval/eval_events.py` didn't get worse |

### A new Apollo list
1. Export contacts from Apollo into `<Data>/EMEA` (or a new folder, passed to `prepare.py` and `grade_leads.py --apollo`).
2. A new kind of list: add it to `LIST_TARGET` (name, target industry group), `TARGET_CODES` (its activity codes) and `SERVICE_LINES` in `grade_leads.py`.
3. Run steps 1–12.

## 4. How a lead is graded

### 4.1 Gates (before scoring)
| Grade | Rule | Setting |
|---|---|---|
| **Excluded: distressed** | Companies House / Gazette: administration, liquidation, receivership, strike-off, dissolved, insolvency notice | `DISTRESS` |
| **Existing client** | Website or email domain matches an active MyStaff client in the priority list | `match_internal()` |
| **Duplicate** | Apollo's name holds a rename ("Monarch Healthcare Now RDCP Care") and the new name is already another lead in the list. That lead is graded; this one keeps its contacts (§4.6, renamed companies) | `DUPLICATE`, `split_renamed()` |
| **Check fit** | Not in the list's target industry (§4.4). Scored, not tiered | `CHECK_FIT`, `target_check()` |

### 4.2 Score (out of 100)
The live Priority Score code, New Logo, **without the HubSpot parts** (these leads are pre-HubSpot): website activity and Diamond referral get 0 points, and their 40 points are shared out in the live profile's own proportions (`SCORING`).

| Part | Points | From |
|---|---|---|
| News and hiring | 50 (25 + 25) | News: event type × recency (§4.3). Hiring: **roles Cloudstaff fills** posted in the last 30 days, 20+ = full (`HIRING_SCORE`) |
| Fit | 33 | Client Propensity prospect profile for the industry, **all countries** (`FIT_COUNTRY = "Unknown"`: only 26 UK clients, 2 in Healthcare, 2 in Technology). Growth 75% (better of 5+ seats in 1 year / 10+ in 2 years), second department 25% |
| Competitor client | 17 | Named as a competitor's client in candidates' CVs (§4.6). Exact name or website-name match to a confirmed map row = full points; close names or pending rows = a "check" chip, no points |
| Website activity, Diamond referral | 0 | Not scored: pre-HubSpot |
| Act now bonus | +15 per trigger family | Funding / PE buyout news ≤ 30 days, hiring spike or 18+ roles, restructuring / leadership news ≤ 30 days. Half-strength news never triggers it |

### 4.3 News rules
- **Strength:** Funding round 1.0 · PE buyout 1.0 · M&A 0.8 · Expansion / new office 0.7 · Restructuring 0.5 · **Contract / partnership win 0.5** · Leadership change 0.3 · **Product launch 0.3**. Recency: 0–30 days ×1.0 · 31–90 ×0.7 · 91–180 ×0.4 · older 0. The two in bold were added 18 Nov with first-guess strengths (`NEW_EVENT_STRENGTH`, passed to the scoring code as the profile's `news_strength_extra`).
- **Events add up** (changed 20 Nov, `COMPOUND_EVENTS`): a lead's reports (news, own site, hand-labelled, CQC, contracts, its parent's event) are grouped into distinct events (same type within `EVENT_WINDOW_DAYS` = 30 days is one event, so one deal in three outlets and CQC counts once). Each event is worth strength × confidence × recency; they combine as 1 − (1−a)(1−b)…, so one event scores as before, each extra one adds part of what is left, and news never passes its 25 points. Belmont: acquisition 0.56 and new commercial lead 0.30 → 0.69 (17.3 points, was 14). A reviewed headline (`event_overrides.csv`) decides for its whole event. Passed to the shared scoring as the optional column `news_compound` (blank = strongest event only, so the main pipeline is unchanged). Act now still keys off the strongest event. The lead panel lists the grouped events; a "2+ separate events" chip and filter mark leads with several.
- **"Other" news earns nothing** (`OTHER_NEWS_POINTS = False`), so a company's own blog posts count only when they report one of the events above.
- **Factors** (`news_strength_factor`, read by `priority_scoring._news_factor()`; blank = 1, so the main pipeline is unaffected): medium / low classifier confidence ×0.5 (`CONFIDENCE_FACTOR`); a parent company's event ×0.5 (`PARENT_FACTOR`), used only when it beats the lead's own; corrected (`event_overrides.csv`) and hand-labelled (`manual_events.csv`) events ×1.0.
- **Industry trend is not in the score** (`TREND_IN_SCORE = False`): tiers rank within each list, where every lead shares the same trend.

### 4.4 Target industry ("Check fit")
Apollo's one-word industry is often wrong (Coxbench Hall Residential Care Home = "individual & family services"). `target_check()` uses evidence in this order and writes the reason to `fit_basis`:
1. Companies House UK SIC for furniture or building (`OTHER_TRADE_UK_STRONG`) → check fit (suppliers' sites mention care too).
2. Apollo US SIC / NAICS for the target activity (`TARGET_CODES`) → in, unless Apollo's industry is a supplier trade (`SUPPLIER_GROUPS`) *and* the UK SIC is a staffing / consulting / property / head-office code (`OTHER_TRADE_UK_WEAK`, also how care groups register holding companies).
3. A weak other-trade UK SIC with no target codes → check fit.
4. Website service lines for the list → in (not for supplier trades).
5. Otherwise Apollo's industry.

A lead put in the target gets the target's industry group for fit (`industry_apollo` keeps Apollo's).

### 4.5 Tiers
- **Within each Apollo list** (`TIER_GROUP = "lead_list"`): top 10% Tier 1, next 30% Tier 2, the rest Tier 3.
- Equal scores are ordered by **readiness** (0–4), one point each: an Apollo funding label · a decision-maker (owner, founder, C-suite, partner, VP, director) with a verified email · in the news, or a relevant event on its own site, in the last 180 days · in the list's target industry. Readiness never adds points. Exact ties share the higher tier, so a tier can run over its share.

### 4.6 Other inputs
- **Roles we fill** (`roles.py`): each posted job title is cleaned (`shared/jp_titles.py`) and matched to Staff Central's JP titles with the scraper's MiniLM model. ≥ 0.80 = we fill (counted); 0.62–0.80 = possible (shown, not counted); care and facilities roles that must be done in person = on-site (`ONSITE`). Only the JP Title / JP Category columns of the Staff Central export are read.
- **Event details** (scraper `nlp run`): "bought by SecureSky", "buying four Yorkshire homes", "new Managing Director: Charly Davis", "raised £18.2m". The fullest detail among the company's articles on that event (`best_detail()`); only describes an event already counted.
- **Competitor-client map** (`Client Extraction (CS Jobs)/export_client_map.py` → `competitor_clients.csv`, company names only, competitors' own brands dropped): matched by `competitor_matches()` with `shared/company_keys.py`. One-word names need an exact match and no contradicting location; close names need 2+ words, 10+ letters and similarity ≥ 0.95 (`COMPETITOR_FUZZY`).
- **Registers** (added 20 Nov): `cqc.py` and `contracts.py` (News Scraper/apollo_emea) write dated events that are read like `manual_events.csv`, keyed by account, at full strength, labelled with their source: CQC takeovers (**M&A**), new CQC registrations (**Expansion / new office**) and Find a Tender awards (**Contract / partnership win**) score (`REGISTER_SCORED`); a new registered manager at one home is shown, not scored (turnover is common and it would trigger Act now). The CQC profile (locations, beds, home-care offices, services, people supported, ratings, councils) is shown in the lead panel; homes rated below Good in the last 6 months get a no-points chip.
- **Ownership** (added 23 Nov, `add_ownership()`, a flag, **no points**): BDM feedback: companies not owned by a parent, an umbrella group or an investor, and not run on public money, have fewer layers of sign-off and buy faster. `ownership.py` (News Scraper/apollo_emea) reads the Companies House register of people with significant control (free daily snapshot) for each lead's company numbers (Companies House name match, then CQC providers matched by number or website, then the "Company No." on the lead's own website, checked against the register and the lead's name), and follows owning companies up the chain. Classes, first that applies: **Public body** (council / NHS / government in the chain, or CQC provider type) · **Charity / not-for-profit** (CQC charity number, guarantee or community-interest company type, charity in the chain) · **Investor-backed** (limited partnership or investment-vehicle name in the chain) · **Part of a corporate group** (top owner a company with no individual named) · **Owner-managed group** (individuals at the top of more than `GROUP_MAX` = 5 companies) · **Owner-managed** (individuals at the top, directly or via a small holding company: the BDM target) · **Unknown**. Grade_leads then adds: a PE buyout in the news in the last 2 years makes it Investor-backed; Apollo's parent fills an Unknown ("Part of a corporate group") or, against an owner-managed result, raises a **Check ownership** flag, as do recent M&A news and a number read from the website. Shown as the Ownership column, filter, lead-panel section and a Data gathered chart.
- **Sub-sector** (`SUBSECTORS`, `add_subsectors()`): from CQC service types when the lead is registered, else from Apollo US SIC / NAICS (4 digits) and the Companies House UK SIC. Care: nursing homes, residential care, learning disability / mental health, home care, care staffing agency. Cyber: services / consultancy, software product, managed / hosted, training. A lead can have several. Descriptive, no points; each comes with a pitch hint (`SUBSECTOR_PITCH`, a first draft for BDM Marketing to correct) and is a filter on the page.
- **Renamed companies** (`reference_code/company_keys.py` `split_renamed()`, used by both `prepare.py` and here, added 20 Nov): Apollo sometimes stores a rebrand in the name, "Old Now New" (also "now known as", "now part of", "New formerly Old"). Splitting on "Now" alone is unsafe ("Here and Now Care"), so the name is split only when the website, a contact's email domain or the LinkedIn slug starts with one of the two names, or the new name is another account in the list. Then the new name is searched and shown as "New (was Old)", with a "Renamed" chip; with no evidence the name is left alone with a "Check the name" chip. The old name is not searched (Monarch Healthcare pulls US companies); add it to `overrides.csv` aliases if wanted. "Now part of X" keeps the company's own name.
- **Apollo funding vs the news** (`apollo_vs_news()`): matches (same kind of event) / news shows a different event / not in the news. Shown, never scored.

### 4.7 The page
| Where | What |
|---|---|
| **Why** column | Signals only: events (with details), parent events (group icon, dashed, "Parent"), hiring (roles in bands 1–2 … 21+, how recent, how many we fill), Companies House changes, Apollo funding (database icon), competitor client, fit chips (High **and** ≥ 1.5× the usual rate), check warnings. A legend above the table explains each chip |
| **Readiness** column | n/4, with a tooltip listing which points the lead has |
| **Lead panel** (click a row) | Fit detail (each chance against the usual rate, likely first new department, outlook, target-industry reason) · **Company profile** (service lines from its website, software-stack pitch hints, group membership) · Companies House · news list (incl. parent and hand-labelled articles) · jobs and every posted role with its Cloudstaff match · score breakdown · contacts |
| Other pages | Grades overview · Data gathered (news, events, filings, jobs, hiring bands and recency, Apollo funding vs news, contacts, coverage by source) · Fit and market (service lines, fit profiles, market trend as context, industry check) · How grading works · QA |
| Filters | List, grade, Act now, hiring, service line, Apollo funding, industry. CSV export of leads and of contacts |

## 5. Files

| File | What it is |
|---|---|
| `grade_leads.py` | The pipeline: Apollo → internal matches → News Scraper results (news rules, own-site rule, parents, event details, manual events, jobs, roles, service lines) → competitor clients → target check → fit → gates → score → tiers → chips → xlsx + json. Every rule is a setting at the top |
| `../../News Scraper/apollo_emea/cqc.py`, `contracts.py` | CQC register and public contract awards (§4.6, Registers) |
| `../../News Scraper/apollo_emea/ownership.py` | Ownership from the Companies House PSC register (§4.6, Ownership) |
| `roles.py` | Posted job titles → Cloudstaff roles (§4.6) |
| `dashboard_template.html` | The page (house format, `cs-dashboard` skill) |
| `event_overrides.csv` | Corrections of an event's type (leads and parents), with `labelled_by` |
| `manual_events.csv` | Events added by hand, with `labelled_by` (the first 9 by Claude, 18 Nov) |
| `PLAN.md` | Original design and decision log |
| `../format data/priority_scoring.py` | Shared scoring code, moved out of the notebook 18 Nov. Lead grading uses two optional extras the main pipeline doesn't set: the per-row `news_strength_factor` and the profile's `news_strength_extra`. After every change the notebook's golden tests passed and its scored output was checked identical to before |
| `../../News Scraper/apollo_emea/` | Collection: `prepare.py`, `overrides.csv` (19 generic names), its own README |
| `../../Client Extraction (CS Jobs)/export_client_map.py` | Writes the competitor-client map |
| `../../shared/company_keys.py`, `../../shared/jp_titles.py` | Company-name keys; job-title cleaning |

**Outputs** (in `<Data>`): `lead_grades_apollo_emea.xlsx` (sheets: leads, contacts, news_articles, parent_news_articles, run_info) · `lead_grades_apollo_emea.json` (the page's data) · `<date>_EMEA_Lead_Grades.html`.

## 6. Decisions (all 18 Nov 2026, by the requester)

| Decision | Why |
|---|---|
| Undated Apollo funding: no points, its own chip, compared with the news | No date or amount; could be years old. How to reconcile it is still open (§8) |
| Medium / low confidence news at half strength | The classifier's medium tier is near a coin flip on unseen companies |
| Tiers within each Apollo list | Separate campaigns; cyber was taking most Tier 1 places on fit alone |
| Standalone dashboard, one owner (BDM Marketing) | No SDR / BDM / Marketing split for these yet |
| Fit from industry only, all countries | 26 UK clients is too few for a UK estimate |
| Readiness tie-break from the data we have | Scores tie in large blocks |
| "Other" news earns nothing, and isn't shown as a reason | A score must only move for a reason shown |
| Parent news counts at half strength, marked "Parent" | Useful (HC-One's CEO left) but the parent isn't the lead |
| Hiring counts only roles Cloudstaff fills | Care homes mostly hire carers and nurses, which we don't place |
| Pre-HubSpot: no website activity or Diamond referral | No data can exist for them; points reshared proportionally |
| Industry trend out of the score | The same for every lead in a list |
| Why = signals only; descriptive chips in the company profile | A reason should be something to act on |
| Evidence-based target check; fit chips only at 1.5× the usual rate | Apollo's industry mislabelled real care homes; "High" alone flagged nearly every lead |
| Two new event types: Contract / partnership win, Product launch | Real growth signals were sitting in "Other". Sponsorships don't count |
| Missed events added by hand and marked who labelled them; the same phrasings taught to the classifier | One-offs fix today's list; the classifier fixes every future run |
| Competitor-client map from candidates' CVs fills Competitor client | The only source for it; also needed by the main pipeline |
| LinkedIn / Indeed not scraped | Their terms forbid automated access |
| New-prospect discovery and micro-industry trends: out of scope for now | Parked |

## 7. First run (18 Nov 2026)

### 7.1 Results
**Grades**

| List | Tier 1 | Tier 2 | Tier 3 | Check fit | Excluded |
|---|---|---|---|---|---|
| UK care homes (175) | 15 | 71 | 57 | 29 | 3 |
| UK cybersecurity (55) | 6 | 27 | 21 | 0 | 1 |

Tier 1, care: Lilian Faithfull Care, Strong Life Care, Forge Care, Dunham Care, Clarendon Care Group, Belmont Healthcare, Loveday & Co, Harrington Care Homes, Hoama Group, Milkwood Care, Kara Healthcare, Midlands Care, Nurse Next Door, First City Nursing & Care, Meridian Healthcare. Cyber: CSA Cyber, Soveren, KYND, OnecomMatrix, CyberOwl, e2e-assure.

**The data**

| Source | Result |
|---|---|
| News, size | Apollo database: 1,763 articles fetched, 460 texts attempted (282 read). **801 matched** (725 about leads, 76 about parents), 951 rejected as someone else. Of the 725, **633 are the companies' own blog posts and newsletters**, 92 from other publishers. 660 are "Other"; about 65 are real events |
| News, events | 79 leads with a confirmed article; **23 leads with a scored event**: M&A 7, Contract / partnership win 5, Expansion 4, Leadership change 3, Product launch 2, PE buyout 1, Funding round 1 (19 their own, 3 a parent's, 1 hand-labelled). After removing 19 generic-name mismatches and correcting 4 event types |
| Apollo funding vs news | Of 41 labels: 2 match, 7 show a different event, 32 not in the news. The news found 5 deals Apollo has no label for |
| Companies House | 162 / 230 matched by name; 4 distressed (J S Wright & Co, Qualia Care, Amica Care, Trustify); 1 newly registered, 3 name changes |
| Jobs | 26 careers pages read; 12 with open roles (106); of 71 roles listed by title, **4 are roles we fill**, 3 possible, 62 on-site. Care homes mostly hire through Indeed and agencies, which aren't read |
| Parents | 13 named by Apollo; their news adds HC-One's CEO leaving (parent of Meridian Healthcare) |
| Target check | 200 in target, 30 not: decided by activity codes for 196, another trade 20, Apollo industry only 13, website 1. Rescued 9 care providers Apollo mislabelled |
| Website service lines | Found for 99 / 175 care homes and 33 / 55 cyber companies |
| Competitor clients | Map of 2,931 clients from 18,302 CV rows (1,433 confirmed). **No Apollo UK lead matches** (competitors' clients are mostly AU / US). It does match 12 existing Cloudstaff clients, confirmed as a competitor's client (e.g. Alexilum and Taxes Decoded / TOA Global, HaloMD and Dylan's Candy Bar / Emapta, VikingCloud / KMC), and 25 pending: worth passing to Account Management |
| Internal | No Apollo company is a client or in the HubSpot report |
| Ownership (23 Nov, PSC snapshot 22 Nov) | Company number for 195 / 230 (154 Companies House name match, 37 CQC providers, 4 websites). **Owner-managed 114** (care 92, cyber 22) · owner-managed group 27 · investor-backed 22 · corporate group 16 · charity 10 · public body 1 · unknown 40 (35 no number found). Only 5 of the 21 Tier 1 leads are owner-managed. 16 leads flagged to check (mostly M&A news since the register was filed, e.g. Milkwood Care) |

### 7.2 Classifier change (News Scraper, 18 Nov)
- **Added:** Contract / partnership win and Product launch, plus the phrasings found in this list's "Other" pile ("adds six homes to portfolio", "takes 3,442 sq ft office", "development pipeline", "80-bed scheme", "secures £13m backing", "names new commercial lead", "strengthens leadership team"). Sponsorships excluded; "expands its partnership" counts as a partnership, not an expansion.
- **Measured** with `News Scraper/eval/eval_events.py`, the two new categories treated as Other so the numbers compare with the existing labels: build set precision 0.89 → 0.88, recall 0.80 → 0.79; 12 unseen companies precision 0.66 → 0.66 (rules alone 0.60 → 0.64), recall 0.55 → 0.55. All 33 scraper unit tests pass.
- **Not measured:** the new categories' own accuracy (the labels have none of them yet), and accuracy on UK data in general. `News Scraper/apollo_emea/out/article_check.xlsx` is ready for a person to mark ~100 rows (right company? right event?).

## 8. Open questions and next steps

**Focus (23 Nov 2026, the requester):** grading is not the priority now; events only need to be **flagged** on each lead. Questions 1–5 below are parked, not waiting on an answer.

**Open (parked)**
1. **Reconciling Apollo funding with the news.** Suggested: a match lets Apollo raise a medium-confidence event to full weight; a different event keeps the news (Apollo's is probably older); "not in the news" gets a manual date check recorded in a date-override file, then scores like news.
2. **Strengths of the two new event types** (0.5 and 0.3 are first guesses). When agreed, add them to `Marketing Intelligence/reference materials/data/scoring_settings.json` so the main pipeline uses the same values.
3. **The bottom of Tier 1:** some leads reach it on readiness alone (no scored signal). Optional rule: Tier 1 needs a scored signal.
4. **On-site hiring scores nothing.** To count it as a growth sign: `HIRING_SCORE = "all"`.
5. ~~One event per lead~~ events add up since 20 Nov (§4.3). Open: whether the 30-day grouping window and the combining rule are right.

**Next steps, in order of value**
1. **Accuracy check on UK data:** a person marks `article_check.xlsx` (~100 rows), including some new-category events; then the eval scripts score them.
2. **Firm up the competitor-client map:** clear its review queue (569 CV entries, 1,862 undecided client names), and feed it into the main pipeline's `prior_bpo_flag` (still mock there).
3. **Adzuna API** for UK job-board listings: care homes' hiring is mostly invisible today. The key is free and instant, but Adzuna's terms (checked 23 Nov 2026) put "sales prospecting or lead generation" outside free use: it needs a written licence agreement (a 14-day commercial trial is allowed only to test coverage). No company-name filter is documented; ads carry `company.display_name`, so matching would be by search and filter.
4. **Size and revenue in fit** (in Client Propensity, not here): size known for only 235 / 1,110 clients and biased; needs size at signing from HubSpot. The ICP growth profile (`client_growth_project`) found the same gap.
5. **Parked:** micro-industry trends (care sub-sectors could work, cyber is too thin in UK news); new-prospect discovery.
6. **Commit**, then schedule steps 3–12 nightly or weekly.
7. **Ownership gaps:** 35 leads have no company number (mostly cyber companies whose trading name differs from the legal name, and websites that print no number); there is no file yet for a person to supply a number by hand (an easy addition). Owners filing with no 25%+ holder show as Unknown. Public funding (Contracts Finder, website wording, council-funded care types, Innovate UK grants) is the next part of the BDM's criteria, not built yet.
8. **Out of scope for now, reminder:** `<Data>/EMEA/Apollo_list.xlsx` (20 Nov) checks 339 + 246 Apollo companies against HubSpot (`HubSpot Website`, `HubSpot Status`). Not used by any code; a possible source for the "already owned in HubSpot" gate later.
