# apollo_emea: collect news, filings and jobs for Apollo lead lists

This folder **collects** signals for the companies in Apollo exports, using the news scraper's company mode. **Grading** the leads (Priority Score, gates, internal checks, the dashboard) happens in Marketing Intelligence: see [`../../Marketing Intelligence/apollo_lead_grading/README.md`](../../Marketing%20Intelligence/apollo_lead_grading/README.md), which also has the full run order.

Apollo exports give each company's **website**, **email domain**, **city** and **headcount**: what the scraper is short of elsewhere (no website means no company card, newsroom feed or careers page). Runs use their own database (`data/news.db`), so they never mix with the AU sample data.

**What changed in the scraper itself for this work (18 Nov 2026):** only its event classifier. `news_scraper/classify.py` and `event_examples.py` gained two categories, **Contract / partnership win** and **Product launch**, plus phrasings found missing on this data (see the main README, "What kind of news?", for the measured effect). That applies to every list the scraper runs on.

## The data (export of 18 Nov 2026)

| File (Desktop `Marketing Intelligence Priority/Data/EMEA`) | Apollo list | Contacts | Companies |
|---|---|---|---|
| `apollo-contacts-export.csv` | UK Care Homes 1–100 Contacts | 246 | 175 |
| `apollo-contacts-export (1) - Copy.csv` | UK Cybersecurity Decision-Makers – Verified | 93 | 55 |

All 230 companies are in the UK; the two lists don't overlap. Apollo names 13 parent companies.

| Apollo field | Coverage | Use here | Use in lead grading |
|---|---|---|---|
| `Website` (else email domain) | 228 + 2 | Company card, newsroom feed, careers page, domain evidence | Joins to MyStaff / HubSpot and the competitor map |
| `Company City`, `# Employees` | ~95%, 100% | Location evidence; small-company name rules | Employee band |
| `Latest Funding` | 41 (11 care, 30 cyber) | 365-day lookback, so the news can date it | Chip compared with the news; no points. **Type only: no amount, no date** |
| `Parent company (Apollo data)` | 13 | `parents.csv`: their news is collected too | Parent events at half strength, marked "Parent" |
| `Industry`, `SIC Codes`, `NAICS Codes`, `Technologies`, `Annual Revenue`, contacts | – | Not used | Target-industry check, pitch hints, contact readiness |

## Run it (from the `News Scraper` folder)

```bash
PY=../.venv/Scripts/python.exe; DB=apollo_emea/data/news.db
$PY apollo_emea/prepare.py "C:/Users/<you>/Desktop/Projects/Marketing Intelligence Priority/Data/EMEA"
$PY -m news_scraper filings --companies apollo_emea/data/companies.csv --registers uk --db $DB
$PY -m news_scraper run     --companies apollo_emea/data/companies.csv --db $DB --read-articles --read-max-per-company 5
$PY -m news_scraper jobs    --companies apollo_emea/data/companies.csv --db $DB
$PY -m news_scraper run     --companies apollo_emea/data/parents.csv --db $DB          # parent companies: news only
$PY -m news_scraper nlp run --db $DB --scope company --stages entities,events          # event details (who bought whom, amounts)
$PY -m news_scraper export  --db $DB --out apollo_emea/out --lookback-days 365
$PY apollo_emea/cqc.py --download                                                 # CQC register (care, England); after filings
$PY apollo_emea/contracts.py                                                      # public contract awards (Find a Tender); after cqc.py
```

About 20 minutes for news on 230 companies the first time (then only new articles), ~10 minutes for jobs, ~5 for filings (Companies House files are cached in `../data/registers/`), under a minute each for parents, event details and export. After changing the classifier or `overrides.csv`, only `export` needs re-running.

| File | What it is |
|---|---|
| `prepare.py` | Apollo export(s) → `data/companies.csv` (one row per company, `company_id = apollo-<Apollo Account Id>`) and `data/parents.csv` (`parent-<domain>`). Cleans names ("MIRACL \| The login you love" → MIRACL, all-caps → Title Case), uses the email domain when there is no website, turns a rebrand in the name ("Monarch Healthcare Now RDCP Care") into the new name when the website, email or LinkedIn backs it (`reference_code/company_keys.py` `split_renamed()`; prints each one), sets a 365-day lookback for companies with a funding label, applies `overrides.csv`. Writes no contact data |
| `cqc.py` | CQC register (England, monthly files, Open Government Licence, no key). Joins on the provider's Companies House number, else website, else exact multi-word name; leads with the same name pool their providers. Writes `out/cqc_providers.csv` (locations, beds, services, ratings), `out/cqc_locations.csv`, `out/cqc_events.csv`: a home re-registered under the lead within 90 days of leaving another provider at the same postcode = **M&A**, a new home with no predecessor = **Expansion**, a new registered manager vs the previous monthly snapshot = Leadership change (from the second monthly run). Files in `../data/registers/cqc/` (the .ods is turned into a cached .csv once, ~3 min). Franchises match their franchisees through the shared website (Nurse Next Door: 4) |
| `contracts.py` | Public contract awards from Find a Tender's OCDS API (free, no key; all new UK procurements since Feb 2025). Every award notice in the lookback is cached by month in `../data/registers/fts/` (~1,000 a month; first run ~15 min) and matched by Companies House number (the lead's or a CQC provider's) or exact 2+ word name. Writes `out/contract_awards.csv` (Contract / partnership win events). Contracts Finder did not answer from this network |
| `overrides.csv` | Hand fixes by `company_name`: `aliases`, `context`, `ambiguous`. **19 rows**: Post-Quantum (pilot) and 18 from the full run (The Fed, George Thomas, White Hat, Titania, Pentest Limited…), all of which had matched someone else |
| `out/company_summary.csv`, `out/signal_events.csv` | **The hand-off to lead grading:** per company and per article |
| `out/article_check.xlsx` | A sheet to mark ~100 articles (right company? right event?) for an accuracy check on UK data; then `eval/eval_identity.py` and `eval/eval_events.py` |
| `data/`, `out/` | Git-ignored |

## What the run found (18 Nov 2026)

| Collector | Result |
|---|---|
| **News** | 1,763 articles fetched; **801 matched** (725 about leads, 76 about parents), 951 rejected as about someone else. Of the 725, 633 are the companies' own blog posts and newsletters. 79 leads with a confirmed article; **23 with a scored event** after the classifier change (M&A 7, Contract / partnership win 5, Expansion 4, Leadership change 3, Product launch 2, PE buyout 1, Funding round 1). Examples: Forge Care bought by Endurance Capital, Milkwood bought by Holmwood, Strong Life / Clarendon / Midlands buying homes, Dunham's £550m pipeline, CSA Cyber's new office, KYND chosen by Contour, e2e-assure's Cumulo launch |
| **Parents** | 13 searched; 6 had no news. Adds HC-One's CEO leaving (parent of Meridian Healthcare); the rest is noise or the lead's own story |
| **Filings** (Companies House + Gazette) | 162 / 230 matched by name. **4 distressed:** J S Wright & Co and Qualia Care (administration), Trustify (liquidation), Amica Care (strike-off proposed). 1 newly registered (Harrington Care Homes), 3 name changes. 68 not found: Apollo's name is often the trading name |
| **Jobs** | 26 careers pages read, 12 with open roles (106). Care homes mostly recruit through Indeed, NHS Jobs and agencies (not read: their terms forbid it); 9 companies link to Indeed, 1 to LinkedIn |
| **Website cards** | Description and keywords for 194 companies; lead grading reads service lines from them (care: residential, dementia…; cyber: GRC, identity…) |

**Matching gotchas**
- **Generic names** match other companies and people (obituaries, the Federal Reserve, theatre reviews). Sort `out/company_summary.csv` by `matched_articles` after each run and add them to `overrides.csv`.
- **Own-site posts dominate.** Most "articles" are the company's own newsletters; lead grading gives them no points unless they report a real event.

## Next steps (collection side)

1. **Better Companies House matching** for the 68 not found: try the email-domain name and Apollo's "Company Name for Emails", or the free Companies House search API (free key), which also gives **officers** and **PSC** (dated leadership and ownership changes).
2. **Adzuna API** (free key) for UK job-board listings, since care homes' hiring is mostly on boards.
3. ~~CQC data for the care list~~ done 20 Nov (`cqc.py`). Still open: Scotland (Care Inspectorate), Wales (CIW) and Northern Ireland (RQIA) registers; the CQC API (key) for inspection history.
4. **UK accuracy check:** mark `out/article_check.xlsx`, including some Contract / partnership and Product launch rows (the existing labels have none).
