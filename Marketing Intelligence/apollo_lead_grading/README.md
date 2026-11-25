# apollo_lead_grading: grade Apollo leads with the Priority Score

**Status (18 Nov 2026):** working prototype, run by hand. First input: two Apollo lists (UK care homes, UK cybersecurity), 230 companies, 339 contacts. Output: a standalone **EMEA Lead Grades** dashboard, one list owned by **BDM Marketing**. Not committed yet.

This README is the handoff: what it does, how to run it, every rule and why, what the first run found, and what's open. [PLAN.md](PLAN.md) holds the original design and decision log; where the two differ, this file is current.

---

## 1. What it does

Apollo gives us leads that are **not in HubSpot yet**. This grades them so BDM Marketing works the best ones first, from three kinds of information:

| Kind | Source | Used for |
|---|---|---|
| **What Apollo has** | Apollo contact export | Website, industry, activity codes (US SIC / NAICS), staff, revenue, city, latest funding type, parent company, software stack, contacts |
| **What we gather** | `News Scraper` (repo root) | Dated news events (with details), parent companies' news, open jobs and their dates, Companies House status and changes, the website's description, CQC register, public contracts, **who owns each lead** (Companies House PSC register, Charity Commission) |
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
| 7c | Ownership (Companies House PSC register + Charity Commission register) | `News Scraper` | `../.venv/Scripts/python.exe apollo_emea/ownership.py --download` (after 2 and 7a; monthly is enough; without `--download` the cached files are used) | ~2.6 GB + 45 MB download and ~10 min the first time per snapshot; then ~1 min |
| 7d | Officers (Companies House API: current directors) | `News Scraper` | `../.venv/Scripts/python.exe apollo_emea/officers.py` (key `COMPANIES_HOUSE_API_KEY` in `News Scraper/.env`; monthly with 7c; only new or 30-day-old companies are asked again) | ~10 min the first time, then ~1–2 min |
| 8 | Competitor-client map (when the CV export is refreshed) | `Client Extraction (CS Jobs)` | run `competitor_client_extraction.ipynb`, then `../.venv/Scripts/python.exe export_client_map.py` | ~3 min |
| 9 | UK market trend (weekly, optional; context only) | `News Scraper` | `… segment run --groups "Technology;Healthcare & Wellness" --countries UK`, then `… segment export` | ~2 min |
| 9a | Industry trends (**monthly, after the 1st**; Industry trends page only) | repo root | `.venv/Scripts/python.exe "Marketing Intelligence/apollo_lead_grading/industry_trends.py" --download` (after 7c, which downloads the PSC snapshot; `--download` fetches the newest Companies House file and the newest "Incorporated companies in the UK" statistics release, kept in `News Scraper/data/registers/ch_stats/`). Each run keeps a small copy of the Companies House file in `News Scraper/data/registers/ch_snapshots/` (~50 MB a month): skipping a month only makes that comparison span two months. It also refreshes the trends in an existing `lead_grades_*.json`, so steps 11–12 alone rebuild the page | ~3 min the first time per PSC snapshot, then ~2 min |
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

**Needs review** (Relevant events table, 23 Nov 2026): a row is marked when (a) the news classifier rated it medium or low confidence (scored at half weight); (b) a CQC or Find a Tender match was made on the company name only and is not confirmed in `register_match_reviews.csv` (scored in full until rejected); or (c) Claude labelled it in `manual_events.csv` and the classifier does not also find it at high confidence. It clears when a person corrects or confirms the article in `event_overrides.csv` or confirms the match in `register_match_reviews.csv`. High-confidence mistakes are not caught by the rule: only a person's correction fixes those. A grouped event is marked only when every one of its reports is; the flag never changes the score.

### 4.4 Target industry ("check that the industry matches")
Since 24 Nov 2026 (user) a lead outside its list's target industry is scored **and tiered** like the rest (until then it was graded "Check fit" and not tiered). It is not marked in the leads table; the company panel shows "check that the industry matches the list" on the sector line and in its checks, and the Target industry filter lists them.

Apollo's one-word industry is often wrong (Coxbench Hall Residential Care Home = "individual & family services"). `target_check()` uses evidence in this order and writes the reason to `fit_basis`:
1. Companies House UK SIC for furniture or building (`OTHER_TRADE_UK_STRONG`) → outside the target (suppliers' sites mention care too).
2. Apollo US SIC / NAICS for the target activity (`TARGET_CODES`) → in, unless Apollo's industry is a supplier trade (`SUPPLIER_GROUPS`) *and* the UK SIC is a staffing / consulting / property / head-office code (`OTHER_TRADE_UK_WEAK`, also how care groups register holding companies).
3. A weak other-trade UK SIC with no target codes → outside the target.
4. Website service lines for the list → in (not for supplier trades).
5. Otherwise Apollo's industry.

A lead put in the target gets the target's industry group for fit (`industry_apollo` keeps Apollo's).

### 4.5 Tiers
- **Within each Apollo list** (`TIER_GROUP = "lead_list"`): top 10% Tier 1, next 30% Tier 2.
- **Tier 3 = no scored signal** (user, 23 Nov 2026; `scored_signal`): no scored event in `scoring_events` (news, CQC, contract or parent), no roles we fill posted in 30 days, not a confirmed competitor client. Fit alone doesn't count (every lead gets fit points from its industry). Read from the evidence, not the points, so an estimated news part never counts. A lead without a signal is Tier 3 whatever its score: cyber leads score 21 on fit alone, above some care leads with a signal (10). 23 Nov run: care homes 15 / 5 / 122, cybersecurity 6 / 4 / 44; only 30 of 196 tiered leads have a signal.
- Exact ties share the higher tier, so a tier can run over its share.
- **No tie-break since 23 Nov 2026** (user): the readiness tie-break (0–4: Apollo funding label, verified decision-maker email, news in 180 days, target industry) was removed. Without it the bottom block of tied leads ran into Tier 2 and left Tier 3 empty, which is why Tier 3 is now defined by signal (above).

### 4.6 Other inputs
- **Roles we fill** (`roles.py`): each posted job title is cleaned (`shared/jp_titles.py`) and matched to Staff Central's JP titles with the scraper's MiniLM model. ≥ 0.80 = we fill (counted); 0.62–0.80 = possible (shown, not counted); care and facilities roles that must be done in person = on-site (`ONSITE`). Only the JP Title / JP Category columns of the Staff Central export are read.
- **Event details** (scraper `nlp run`): "bought by SecureSky", "buying four Yorkshire homes", "new Managing Director: Charly Davis", "raised £18.2m". The fullest detail among the company's articles on that event (`best_detail()`); only describes an event already counted.
- **Competitor-client map** (`Client Extraction (CS Jobs)/export_client_map.py` → `competitor_clients.csv`, company names only, competitors' own brands dropped): matched by `competitor_matches()` with `shared/company_keys.py`. One-word names need an exact match and no contradicting location; close names need 2+ words, 10+ letters and similarity ≥ 0.95 (`COMPETITOR_FUZZY`).
- **Registers** (added 20 Nov): `cqc.py` and `contracts.py` (News Scraper/apollo_emea) write dated events that are read like `manual_events.csv`, keyed by account, at full strength, labelled with their source: CQC takeovers (**M&A**), new CQC registrations (**Expansion / new office**) and Find a Tender awards (**Contract / partnership win**) score (`REGISTER_SCORED`); a new registered manager at one home is shown, not scored (turnover is common and it would trigger Act now). The CQC profile (locations, beds, home-care offices, services, people supported, ratings, councils) is shown in the lead panel; homes rated below Good in the last 6 months get a no-points chip.
- **Ownership** (added 23 Nov, `add_ownership()`, a flag, **no points**): BDM feedback: companies not owned by a parent, an umbrella group or an investor, and not run on public money, have fewer layers of sign-off and buy faster. `ownership.py` (News Scraper/apollo_emea) reads the Companies House register of people with significant control (free daily snapshot) for each lead's company numbers (Companies House name match, then CQC providers matched by number or website, then the "Company No." on the lead's own website, checked against the register and the lead's name), and follows owning companies up the chain. Classes, first that applies: **Public body** (council / NHS / government in the chain, or CQC provider type) · **Charity / not-for-profit** (registered with the Charity Commission, matched by company number, CQC charity number or website; else a CQC charity number, a guarantee or community-interest company type, or a charity in the chain) · **Investor-backed** (limited partnership or investment-vehicle name in the chain) · **Part of a corporate group** (top owner a company with no individual named) · **Owner-managed group** (individuals at the top of more than `GROUP_MAX` = 5 companies) · **Owner-managed** (individuals at the top, directly or via a small holding company: the BDM target) · **Unknown**. Grade_leads then adds: a PE buyout in the news in the last 2 years makes it Investor-backed; Apollo's parent fills an Unknown ("Part of a corporate group") or, against an owner-managed result, raises a **Check ownership** flag, as do recent M&A news and a number read from the website. Shown as the Ownership column, filter, lead-panel section and a Data gathered chart. Owner-managed leads are marked **direct** (the people named own the operating company itself) or **via holding company**. **Roles and stakes** (ownership.py `stake()`, added 23 Nov): every step of the chain carries its Companies House band (25–50 / 50–75 / 75–100% of shares or votes; the right to appoint or remove most of the board); people holding the lead's company directly are a route of their own. Each named person is an **owner** (controls it: a majority of shares or votes, or the right to appoint or remove most of the board, along a route that carries control), a **co-owner** (nobody controls it alone, e.g. two 25–50% founders) or a **minority owner** (someone else, a person or a company, controls it: Ben Fordy Taylor at The Fordy Group, 25–50% next to Goodall Brazier's 50–75%). **Owners in Apollo** (`match_owner_contacts()`): the named owners are matched to the lead's Apollo contacts on first + last name; a match is badged "owner", becomes the best contact, and is a filter ("Owner is an Apollo contact"). Named owners of live owner-managed leads and owner-managed groups with no Apollo contact go to `<Data>/owners_to_find_<date>.csv` (name, company, website, grade, Companies House link), best leads first, for an Apollo people search. Only the name is used, never the register's birth date, nationality or address (UK GDPR). **Officers** (24 Nov 2026, `load_officers()`, no points): the current directors, secretaries and LLP members of the lead's companies (`officers.py`, Companies House API). Owner = owns or controls it; officer = runs it and signs for it; an owner who is also a director is the person who decides. Officers are matched to Apollo contacts the same way (first + last name) and get an outlined **director** badge next to any owner badge. Best contact order: owners (owner, co-owner, minority owner), each with directors first; then directors who own nothing; then Apollo's seniority order. Directors who own nothing and are not in Apollo are listed in Who to talk to; named owners not in Apollo say whether they are also a director (`officer_role` in `owners_to_find_<date>.csv`). Filter: "Director is an Apollo contact". Only name, role and appointment date are kept.
- **Sub-sector** (`SUBSECTORS`, `add_subsectors()`): from CQC service types when the lead is registered, else from Apollo US SIC / NAICS (4 digits) and the Companies House UK SIC. Care: nursing homes, residential care, learning disability / mental health, home care, care staffing agency. Cyber: services / consultancy, software product, managed / hosted, training. A lead can have several. Descriptive, no points; each comes with a pitch hint (`SUBSECTOR_PITCH`, a first draft for BDM Marketing to correct) and is a filter on the page.
- **Renamed companies** (`reference_code/company_keys.py` `split_renamed()`, used by both `prepare.py` and here, added 20 Nov): Apollo sometimes stores a rebrand in the name, "Old Now New" (also "now known as", "now part of", "New formerly Old"). Splitting on "Now" alone is unsafe ("Here and Now Care"), so the name is split only when the website, a contact's email domain or the LinkedIn slug starts with one of the two names, or the new name is another account in the list. Then the new name is searched and shown as "New (was Old)", with a "Renamed" chip; with no evidence the name is left alone with a "Check the name" chip. The old name is not searched (Monarch Healthcare pulls US companies); add it to `overrides.csv` aliases if wanted. "Now part of X" keeps the company's own name.
- **Apollo funding vs the news** (`apollo_vs_news()`): matches (same kind of event) / news shows a different event / not in the news. Shown, never scored.

### 4.7 The page
| Where | What |
|---|---|
| **Events & signals** column | Events (with details), parent events (group icon, dashed, "Parent"), hiring (roles in bands 1–2 … 21+, how recent, how many we fill), Companies House changes, competitor client, fit chips (High **and** ≥ 1.5× the usual rate). A legend above the table explains each chip. Checks (competitor client to confirm, renamed, name, industry, register match, ownership, HubSpot match) and "N events need review" are **not** in the table since 24 Nov 2026: they show in the company panel (header and the matching section), still in the CSV export and the review filters |
| **Apollo** column (after Events & signals) | What comes from the Apollo export: the Latest Funding label compared with the news (database icon, no points), Apollo's parent company. An owner or director who is an Apollo contact is not a chip here (24 Nov 2026): the badge on Best contact says it |
| **Lead panel** (click a row) | Answer first, each fact once, empty fields left out (layout 23 Nov 2026). **Header**: tier and score with its three parts, one line on why (Tier 3 = no live signal), website, LinkedIn, city, staff, revenue (Apollo estimate), industry and sub-sector, the main contact (owners first) and anything to check · **Relevant events**: news, CQC register, public contracts and parent-company events merged into one table, last 12 months, newest first, one row per event (reports of the same type within 30 days, as the score groups them; public contracts one row each) with an expandable list of every report, only the relevant types (`NEWS_EVENTS`, after `event_overrides.csv`); a row a person should check is marked **Needs review** (hover for why, see 4.3); under it one line each for the news search, hiring (stale when nothing was posted in 90 days), Companies House filings and the Apollo funding label · **Why this score**: the points table, then the fit detail (each chance against the usual rate; outlook is the whole industry's) · **Pitch angles**: sub-sector back-office work (`SUBSECTOR_PITCH`), likely first department, software-stack hints (`TECH`), roles we fill, website service lines and the CQC footprint, each tagged with its source · **Who to talk to**: ownership in one line, then one table of Apollo contacts and named owners not in Apollo (role, stake, board control as a badge) · **Evidence** (closed until opened): Companies House, ownership chain and where the company number came from, CQC register and locations, public contracts, jobs with every posted role and its Cloudstaff match, news articles, how the event points add up, industry and activity codes |
| Other pages | Grades overview · Data gathered (news, events, filings, jobs, hiring bands and recency, Apollo funding vs news, contacts, coverage by source) · Fit and market (service lines, fit profiles, market trend as context, industry check) · Industry trends (below) · How grading works · QA |
| **Industry trends** page (added 24 Nov 2026) | Market context for **every live UK company**, not the leads; nothing on it feeds the grades, and the lead filters don't apply. Built by `industry_trends.py` from the Companies House file and the PSC snapshot already cached in `News Scraper/data/registers/`. Per MyStaff industry group (first SIC code, via `references/mystaff_industry/uk_sic_to_industry_group.csv`) and for all UK companies: KPI tiles; **Which industries are growing** (24 Nov 2026; replaced an ONS business-demography version the same day because ONS is annual and ~11 months late): **estimated net growth** = (companies opened − closed) ÷ companies at the start over the last 1 / 3 / 6 months (12 once the series is long enough). UK totals are official: Companies House's monthly statistics (incorporations, restorations, struck off by route, register size; monthly since April 2026, quarterly release ~1 month after the quarter). Each industry gets its share from our file: of companies incorporated in those months (opened), of companies awaiting strike-off (voluntary and compulsory strike-offs) and in liquidation (strike-offs after liquidation), of all companies (start). Companies only, as in the statistics (partnerships, overseas entities, CIOs left out). The UK row equals the official register change exactly (checked in the script). **The main assumption**: an industry's share of closures in the period = its share of companies on the way out now; the monthly copies will test it. **Operating companies** (24 Nov 2026; counts, new companies, insolvency, growth and the monthly copies): companies with a trading industry, no dormant accounts, and not a holding company in practice (holding SIC, or a parent, i.e. controlling another live company, named Holdings / Holdco / Topco / Midco / Bidco / Group / Investments; a sample of 15 such parents: 13 clear holding companies). Subsidiaries and trading parents count: position in a group doesn't decide. New companies have filed no accounts, so each industry's new companies are reduced by the dormant share of 24–36 month old companies (15–29% by industry, 20% overall). That adjustment moves the UK level by about a point (−0.49% vs +1.18% for Apr–Sep 2026), so read the chart as a ranking. The ownership charts keep holding companies, since takeovers are often recorded on the holding company; **opened and closed** from our own monthly Companies House copies (collecting since 1 Nov 2026: the first comparison after the December file, a 12-month figure from Nov 2027); an all-industries table, share **controlled by another company** by quarter (majority of shares or votes, or board right; rebuilt from the snapshot's `notified_on` / `ceased_on` dates, from Q1 2018), **takeovers** per quarter (a company over a year old gaining a company owner: first company owner by a group buyer with 3+ companies in the group, other first owner, or changed owner, i.e. sales between groups and restructures, e.g. Xeinadin moving 75 practices to a new parent on 20 May 2022), new companies per quarter, insolvency and strike-off now, and the most active buyers over 8 quarters. **Known limits:** both files list live companies only, so past quarters miss dissolved companies; SIC codes are self-declared; owner records can be filed weeks late |
| Filters | List, grade, Act now, hiring, service line, Apollo funding, industry; signal ticks incl. "Event needs review". CSV export of leads (with `events_and_signals`, `apollo`, `events_to_review`) and of contacts |

## 5. Files

| File | What it is |
|---|---|
| `grade_leads.py` | The pipeline: Apollo → internal matches → News Scraper results (news rules, own-site rule, parents, event details, manual events, jobs, roles, service lines) → competitor clients → target check → fit → gates → score → tiers → chips → xlsx + json. Every rule is a setting at the top |
| `../../News Scraper/apollo_emea/cqc.py`, `contracts.py` | CQC register and public contract awards (§4.6, Registers) |
| `../../News Scraper/apollo_emea/ownership.py` | Ownership from the Companies House PSC register and the Charity Commission register: class, chain with stakes, owner roles (§4.6, Ownership) |
| `roles.py` | Posted job titles → Cloudstaff roles (§4.6) |
| `industry_trends.py` | Industry trends page data (§4.7): writes `<Data>/industry_trends.json` (totals and company names only, no personal data) and caches the PSC snapshot's company owners as `News Scraper/data/registers/psc/corporate-<date>.csv.gz` |
| `../../references/mystaff_industry/uk_sic_to_industry_group.csv` | UK SIC 2007 → the 18 MyStaff industry groups (longest prefix wins; holding, dormant and non-trading companies have no group). The script stops if it drifts from `mystaff_industry` |
| `dashboard_template.html` | The page (house format, `cs-dashboard` skill) |
| `event_overrides.csv` | Corrections of an event's type (leads and parents), with `labelled_by` |
| `manual_events.csv` | Events added by hand, with `labelled_by` (the first 9 by Claude, 18 Nov) |
| `PLAN.md` | Original design and decision log |
| `../format data/priority_scoring.py` | Shared scoring code, moved out of the notebook 18 Nov. Lead grading uses two optional extras the main pipeline doesn't set: the per-row `news_strength_factor` and the profile's `news_strength_extra`. After every change the notebook's golden tests passed and its scored output was checked identical to before |
| `../../News Scraper/apollo_emea/` | Collection: `prepare.py`, `overrides.csv` (19 generic names), its own README |
| `../../Client Extraction (CS Jobs)/export_client_map.py` | Writes the competitor-client map |
| `../../shared/company_keys.py`, `../../shared/jp_titles.py` | Company-name keys; job-title cleaning |

**Outputs** (in `<Data>`): `lead_grades_apollo_emea.xlsx` (sheets: leads, contacts, news_articles, parent_news_articles, run_info) · `lead_grades_apollo_emea.json` (the page's data) · `<date>_EMEA_Lead_Grades.html` · `owners_to_find_<date>.csv` (named owners of owner-managed leads and groups with no Apollo contact, for an Apollo people search: name, role, stake, how held, company, website, grade, Companies House link; best leads and controlling owners first). All hold personal data: never commit them.

## 6. Decisions (all 18 Nov 2026, by the requester)

| Decision | Why |
|---|---|
| Undated Apollo funding: no points, its own chip, compared with the news | No date or amount; could be years old. How to reconcile it is still open (§8) |
| Medium / low confidence news at half strength | The classifier's medium tier is near a coin flip on unseen companies |
| Tiers within each Apollo list | Separate campaigns; cyber was taking most Tier 1 places on fit alone |
| Standalone dashboard, one owner (BDM Marketing) | No SDR / BDM / Marketing split for these yet |
| Fit from industry only, all countries | 26 UK clients is too few for a UK estimate |
| ~~Readiness tie-break from the data we have~~ removed 23 Nov 2026 | Scores tie in large blocks; the user removed it for now |
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
| Ownership (23 Nov, PSC snapshot 22 Nov) | Company number for 195 / 230 (154 Companies House name match, 37 CQC providers, 4 websites). **Owner-managed 114** (87 held directly by the people named, 27 via a holding company) · owner-managed group 27 · investor-backed 22 · corporate group 16 · charity / not-for-profit 11 (9 confirmed on the Charity Commission register) · public body 1 · unknown 39 (35 no number found). Only 5 of the 21 Tier 1 leads are owner-managed. 16 leads flagged to check (mostly M&A news since the register was filed, e.g. Milkwood Care). 299 of 311 chain steps link to Companies House (the rest are overseas owners or a council) |
| Owners in Apollo (23 Nov) | 248 people named as owners at 155 leads; 49 are already Apollo contacts (48 leads; mostly Managing Directors): 27 owners, 11 co-owners, 11 minority owners. 172 named owners of owner-managed leads and groups are not in Apollo (73 owners, 55 co-owners, 44 minority owners): `owners_to_find_<date>.csv` |

### 7.2 Classifier change (News Scraper, 18 Nov)
- **Added:** Contract / partnership win and Product launch, plus the phrasings found in this list's "Other" pile ("adds six homes to portfolio", "takes 3,442 sq ft office", "development pipeline", "80-bed scheme", "secures £13m backing", "names new commercial lead", "strengthens leadership team"). Sponsorships excluded; "expands its partnership" counts as a partnership, not an expansion.
- **Measured** with `News Scraper/eval/eval_events.py`, the two new categories treated as Other so the numbers compare with the existing labels: build set precision 0.89 → 0.88, recall 0.80 → 0.79; 12 unseen companies precision 0.66 → 0.66 (rules alone 0.60 → 0.64), recall 0.55 → 0.55. All 33 scraper unit tests pass.
- **Not measured:** the new categories' own accuracy (the labels have none of them yet), and accuracy on UK data in general. `News Scraper/apollo_emea/out/article_check.xlsx` is ready for a person to mark ~100 rows (right company? right event?).

## 8. Open questions and next steps

**Focus (23 Nov 2026, the requester):** grading is not the priority now; events only need to be **flagged** on each lead. Questions 1–5 below are parked, not waiting on an answer.

**Open (parked)**
1. **Reconciling Apollo funding with the news.** Suggested: a match lets Apollo raise a medium-confidence event to full weight; a different event keeps the news (Apollo's is probably older); "not in the news" gets a manual date check recorded in a date-override file, then scores like news.
2. **Strengths of the two new event types** (0.5 and 0.3 are first guesses). When agreed, add them to `Marketing Intelligence/reference materials/data/scoring_settings.json` so the main pipeline uses the same values.
3. ~~The bottom of Tier 1 on readiness alone~~ readiness removed 23 Nov 2026.
4. **On-site hiring scores nothing.** To count it as a growth sign: `HIRING_SCORE = "all"`.
5. ~~One event per lead~~ events add up since 20 Nov (§4.3). Open: whether the 30-day grouping window and the combining rule are right.
6. ~~Tier 3 empty without a tie-break~~ Tier 3 = no scored signal since 23 Nov 2026 (§4.5). Still open: a tie-break inside Tier 3 (e.g. owner-managed, an owner who is an Apollo contact).

**Next steps, in order of value**
1. **Accuracy check on UK data:** a person marks `article_check.xlsx` (~100 rows), including some new-category events; then the eval scripts score them.
2. **Firm up the competitor-client map:** clear its review queue (569 CV entries, 1,862 undecided client names), and feed it into the main pipeline's `prior_bpo_flag` (still mock there).
3. **Adzuna API** for UK job-board listings: care homes' hiring is mostly invisible today. The key is free and instant, but Adzuna's [API terms](https://developer.adzuna.com/docs/terms_of_service) (read 23 Nov 2026): "sales prospecting or lead generation, requires our written agreement"; a commercial organisation's 14-day trial "is strictly for the purpose of validating the general coverage and quality of the data", and the data "may not be used ... in aggregation" or for "ongoing work" without written consent. No company-name filter is documented; ads carry `company.display_name`, so matching is by search and filter. **Built for the trial only:** `News Scraper/apollo_emea/adzuna_check.py` writes a coverage report and its own database; grading and the dashboard do not read it. Wire it into hiring only once there is a licence.
4. **Size and revenue in fit** (in Client Propensity, not here): size known for only 235 / 1,110 clients and biased; needs size at signing from HubSpot. The ICP growth profile (`client_growth_project`) found the same gap.
5. **Parked:** micro-industry trends (care sub-sectors could work, cyber is too thin in UK news); new-prospect discovery.
6. **Schedule** steps 3–12 nightly or weekly (ownership 7c monthly).
7. **Owners in Apollo:** upload `owners_to_find_<date>.csv` to an Apollo people search (owners first if credits are short), export the contacts again and re-run step 10: found owners get their role badge and become the best contact.
8. ~~**Owner is also a director?**~~ Built 24 Nov 2026 (`officers.py`, §4.1 Ownership). Was: the PSC register says who owns or controls a company, not who runs it. The Companies House officers list (free API key, or one page read per company; not in the bulk files) would confirm the owner is a director, the closest test of "the person you talk to decides".
9. **Ownership gaps:** 35 leads have no company number (mostly cyber companies whose trading name differs from the legal name, and websites that print no number); there is no file yet for a person to supply a number by hand (an easy addition). Owners filing with no 25%+ holder show as Unknown. Public funding (Contracts Finder, website wording, council-funded care types, Innovate UK grants) is the next part of the BDM's criteria, not built yet.
10. **Out of scope for now, reminder:** `<Data>/EMEA/Apollo_list.xlsx` (20 Nov) checks 339 + 246 Apollo companies against HubSpot (`HubSpot Website`, `HubSpot Status`). Not used by any code; a possible source for the "already owned in HubSpot" gate later.
