# apollo_emea: collect news, filings and jobs for Apollo lead lists

This lead list **collects** signals for the companies in Apollo exports, using the news scraper's company mode (`cloudstaff_dev.signals`). This folder holds the list's hand-kept files (`overrides.csv`, `manual_events.csv`, `event_overrides.csv`, `register_match_reviews.csv`); the code is in `src/cloudstaff_dev/leads/` and `src/cloudstaff_dev/signals/`, the settings, step order and target markets in this folder's `list.toml`. **Grading** the leads (Priority Score, gates, internal checks, the dashboard) is described in [`../../lead_grading/README.md`](../../lead_grading/README.md), which also has the full run order.

Folders (from `cloudstaff_dev.common.paths.lead_list("apollo_emea")`; `<MI>` = OneDrive `Desktop/Projects/Marketing Intelligence Priority`, `LOCAL` = `~/cloudstaff_data`, not synced):

| Folder | What is in it |
|---|---|
| `<MI>/inputs/apollo/emea/` | The Apollo exports |
| `LOCAL/work/lead_lists/apollo_emea/` (`<work>`) | `news.db`, `adzuna.db`, `companies.csv`, `parents.csv`, `officers_cache.json`, `web_company_numbers.json`, `cqc_snapshots/` |
| `<MI>/outputs/collected/apollo_emea/` (`<collected>`) | What the collectors write and grading reads: `company_summary.csv`, `signal_events.csv`, `cqc_*.csv`, `contract_awards.csv`, `ownership.csv`, `officers.csv`, `adzuna_coverage.*` |
| `LOCAL/cache/registers/` | Companies House, PSC, CQC, Find a Tender and Charity Commission downloads, shared by every list |

Apollo exports give each company's **website**, **email domain**, **city** and **headcount**: what the scraper is short of elsewhere (no website means no company card, newsroom feed or careers page). Runs use their own database (`<work>/news.db`), so they never mix with the AU sample data.

**What changed in the scraper itself for this work (18 Nov 2026):** only its event classifier. `news_scraper/classify.py` and `event_examples.py` (now `src/cloudstaff_dev/signals/news/`) gained two categories, **Contract / partnership win** and **Product launch**, plus phrasings found missing on this data (see the main README, "What kind of news?", for the measured effect). That applies to every list the scraper runs on.

## The data (export of 18 Nov 2026)

| File (`<MI>/inputs/apollo/emea/`) | Apollo list | Contacts | Companies |
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

## Run it (from any folder)

`python` = the repo's `.venv/Scripts/python.exe` (the package is installed there, editable).

```bash
python -m cloudstaff_dev.leads run apollo_emea                 # every step below in order, then grade + page build and check
python -m cloudstaff_dev.leads run apollo_emea --download      # monthly: also fetch new CQC and PSC files
python -m cloudstaff_dev.leads run apollo_emea --from cqc      # resume at a step (also --only a,b, --skip a,b, --dry-run)
```

Steps: `prepare, filings, news, jobs, parents, nlp, export, cqc, contracts, ownership, officers, grade, build`. Each runs as its own process with its command printed first; by hand they are (`W` = `~/cloudstaff_data/work/lead_lists/apollo_emea`, `OUT` = `<MI>/outputs/collected/apollo_emea`):

```bash
python -m cloudstaff_dev.leads.prepare                                                # defaults: <MI>/inputs/apollo/emea -> W
python -m cloudstaff_dev.signals filings --companies $W/companies.csv --registers uk --db $W/news.db
python -m cloudstaff_dev.signals run     --companies $W/companies.csv --db $W/news.db --read-articles --read-max-per-company 5
python -m cloudstaff_dev.signals jobs    --companies $W/companies.csv --db $W/news.db
python -m cloudstaff_dev.signals run     --companies $W/parents.csv --db $W/news.db   # parent companies: news only
python -m cloudstaff_dev.signals nlp run --db $W/news.db --scope company --stages entities,events   # event details (who bought whom, amounts)
python -m cloudstaff_dev.signals export  --db $W/news.db --out $OUT --lookback-days 365
python -m cloudstaff_dev.signals.registers.cqc --download        # CQC register (care, England); after filings
python -m cloudstaff_dev.signals.registers.contracts             # public contract awards (Find a Tender); after cqc
python -m cloudstaff_dev.signals.registers.ownership --download  # who owns each lead (Companies House PSC); after filings and cqc
python -m cloudstaff_dev.signals.registers.officers              # who runs each lead (Companies House API, key in the repo-root .env); after ownership
```

The register commands take `--list NAME` (default `apollo_emea`) and use that list's folders.

About 20 minutes for news on 230 companies the first time (then only new articles), ~10 minutes for jobs, ~5 for filings (Companies House files are cached in `~/cloudstaff_data/cache/registers/`), under a minute each for parents, event details and export. After changing the classifier or `overrides.csv`, only `export` needs re-running (`--only export`).

| File | What it is |
|---|---|
| `leads/prepare.py` | Apollo export(s) → `<work>/companies.csv` (one row per company, `company_id = apollo-<Apollo Account Id>`) and `<work>/parents.csv` (`parent-<domain>`). Cleans names ("MIRACL \| The login you love" → MIRACL, all-caps → Title Case), uses the email domain when there is no website, turns a rebrand in the name ("Monarch Healthcare Now RDCP Care") into the new name when the website, email or LinkedIn backs it (`cloudstaff_dev.common.company_keys` `split_renamed()`; prints each one), sets a 365-day lookback for companies with a funding label, applies `overrides.csv`. Writes no contact data |
| `signals/registers/cqc.py` | CQC register (England, monthly files, Open Government Licence, no key). Joins on the provider's Companies House number, else website, else exact multi-word name; leads with the same name pool their providers. Writes `<collected>/cqc_providers.csv` (locations, beds, services, ratings), `cqc_locations.csv`, `cqc_events.csv`: a home re-registered under the lead within 90 days of leaving another provider at the same postcode = **M&A**, a new home with no predecessor = **Expansion**, a new registered manager vs the previous monthly snapshot = Leadership change (from the second monthly run; snapshots in `<work>/cqc_snapshots/`). Files in `~/cloudstaff_data/cache/registers/cqc/` (the .ods is turned into a cached .csv once, ~3 min). Franchises match their franchisees through the shared website (Nurse Next Door: 4) |
| `signals/registers/ownership.py` | Who controls each lead, from the Companies House "People with significant control" snapshot (daily, free, no key, ~2.6 GB in 33 zips cached in `~/cloudstaff_data/cache/registers/psc/`; only the newest kept). Pass 1 indexes every company-to-company ownership in the register (cached per snapshot as `graph-<date>.pkl`), pass 2 reads the full records of the leads and their owners (`records-<date>.json`). Company numbers: the filings match, CQC providers (number or website matches), else the number printed on the lead's website (`<work>/web_company_numbers.json`, cached; kept only when the registered name shares a word with the lead; `--no-web` skips it). Charities: the Charity Commission register (England & Wales, daily extract, free, ~45 MB, `~/cloudstaff_data/cache/registers/charity/`), matched by the lead's or an owner's company number, the CQC charity number, then the website (a website-only match never overrides the ownership register; it raises a check). Writes `<collected>/ownership.csv`: class (owner-managed, owner-managed group, corporate group, investor-backed, charity, public body, unknown), evidence, owner chain (`owner_chain_steps`: each step's company number and its stake in the company below, from the Companies House bands: 25–50 / 50–75 / 75–100% of shares or votes, right to appoint or remove most of the board), top owner, group size, individuals named, `owner_roles` (each person: owner = controls it, co-owner = nobody controls it alone, minority owner = someone else controls it; with stake and route), `ownership_route` (the controlling owner holds it directly or via a holding company), Charity Commission number, name, status and income |
| `signals/registers/officers.py` | Current officers (directors, secretaries, LLP members) of every company number `ownership.py` found for a lead, from the Companies House API (free key `COMPANIES_HOUSE_API_KEY` in the repo-root `.env`, see `.env.example`). One call every 2 s (~5% of the 600-per-5-minutes limit), cached in `<work>/officers_cache.json` and asked again only after 30 days, so a run stopped part-way resumes; "too many requests" pauses 5 minutes. Keeps only name, role and appointment / resignation dates (no birth date, nationality, occupation or address). Writes `<collected>/officers.csv` (current officers who are people). First run ~10 min for 297 numbers. `--dry-run` counts the calls; `--limit N`, `--csv-only` |
| `signals/registers/contracts.py` | Public contract awards from Find a Tender's OCDS API (free, no key; all new UK procurements since Feb 2025). Every award notice in the lookback is cached by month in `~/cloudstaff_data/cache/registers/fts/` (~1,000 a month; first run ~15 min) and matched by Companies House number (the lead's or a CQC provider's) or exact 2+ word name. Writes `<collected>/contract_awards.csv` (Contract / partnership win events). Contracts Finder did not answer from this network |
| `signals/jobs/adzuna.py` (was `adzuna_check.py`) | **Trial coverage check only, not part of the run order** (`python -m cloudstaff_dev.signals.jobs.adzuna [--limit N \| --report-only]`). Searches Adzuna's UK job-board ads (last 30 days) for each lead's name and keeps ads whose employer name is the lead's (Apollo name, aliases, Companies House name, CQC providers; one-word or ambiguous names only near the lead's city). Writes its own `<work>/adzuna.db` (ad id, title, employer, location, date; no descriptions) and `<collected>/adzuna_coverage.csv` / `.json`: how many leads with an unknown careers page would gain a hiring count, and whether the roles are ones we fill. Nothing in `export`, `company_summary.csv` or grading reads it. Keys in the repo-root `.env` (`.env.example`). **Why separate:** Adzuna's [API terms](https://developer.adzuna.com/docs/terms_of_service) (read 23 Nov 2026) need "our written agreement" for "sales prospecting or lead generation"; a commercial organisation gets a 14-day trial "strictly for the purpose of validating the general coverage and quality of the data". Without a licence, delete `<work>/adzuna.db` and `<collected>/adzuna_coverage.*` when the trial ends |
| `overrides.csv` (this folder) | Hand fixes by `company_name`: `aliases`, `context`, `ambiguous`. **19 rows**: Post-Quantum (pilot) and 18 from the full run (The Fed, George Thomas, White Hat, Titania, Pentest Limited…), all of which had matched someone else |
| `<collected>/company_summary.csv`, `<collected>/signal_events.csv` | **The hand-off to lead grading:** per company and per article |
| `<collected>/article_check.xlsx` | A sheet to mark ~100 articles (right company? right event?) for an accuracy check on UK data; then `News Scraper/eval/eval_identity.py` and `eval/eval_events.py` |
| `<work>`, `<collected>` | Outside the repo (`<work>` is not synced) |

## What the run found (18 Nov 2026)

| Collector | Result |
|---|---|
| **News** | 1,763 articles fetched; **801 matched** (725 about leads, 76 about parents), 951 rejected as about someone else. Of the 725, 633 are the companies' own blog posts and newsletters. 79 leads with a confirmed article; **23 with a scored event** after the classifier change (M&A 7, Contract / partnership win 5, Expansion 4, Leadership change 3, Product launch 2, PE buyout 1, Funding round 1). Examples: Forge Care bought by Endurance Capital, Milkwood bought by Holmwood, Strong Life / Clarendon / Midlands buying homes, Dunham's £550m pipeline, CSA Cyber's new office, KYND chosen by Contour, e2e-assure's Cumulo launch |
| **Parents** | 13 searched; 6 had no news. Adds HC-One's CEO leaving (parent of Meridian Healthcare); the rest is noise or the lead's own story |
| **Filings** (Companies House + Gazette) | 162 / 230 matched by name. **4 distressed:** J S Wright & Co and Qualia Care (administration), Trustify (liquidation), Amica Care (strike-off proposed). 1 newly registered (Harrington Care Homes), 3 name changes. 68 not found: Apollo's name is often the trading name |
| **Jobs** | 26 careers pages read, 12 with open roles (106). Care homes mostly recruit through Indeed, NHS Jobs and agencies (not read: their terms forbid it); 9 companies link to Indeed, 1 to LinkedIn |
| **Website cards** | Description and keywords for 194 companies; lead grading reads service lines from them (care: residential, dementia…; cyber: GRC, identity…) |

**Matching gotchas**
- **Generic names** match other companies and people (obituaries, the Federal Reserve, theatre reviews). Sort `<collected>/company_summary.csv` by `matched_articles` after each run and add them to `overrides.csv`.
- **Own-site posts dominate.** Most "articles" are the company's own newsletters; lead grading gives them no points unless they report a real event.

## Next steps (collection side)

1. **Better Companies House matching** for the 68 not found: try the email-domain name and Apollo's "Company Name for Emails", or the free Companies House search API (free key), which also gives **officers** and **PSC** (dated leadership and ownership changes).
2. **Adzuna API** for UK job-board listings, since care homes' hiring is mostly on boards. The key is free, but lead generation needs a written licence ([terms](https://developer.adzuna.com/docs/terms_of_service)). `adzuna_check.py` (23 Nov 2026; now `python -m cloudstaff_dev.signals.jobs.adzuna`) measures coverage within the 14-day trial: run `--limit 10` first and check the matches, then all leads, and take `<collected>/adzuna_coverage.json` to Adzuna for a licence quote. Only with a licence: feed matched ads into the jobs columns (careers page wins when read; Adzuna fills unknowns; `hiring_spike` stays careers-only).
3. ~~CQC data for the care list~~ done 20 Nov (`cqc.py`, now `signals/registers/cqc.py`). Still open: Scotland (Care Inspectorate), Wales (CIW) and Northern Ireland (RQIA) registers; the CQC API (key) for inspection history.
4. **UK accuracy check:** mark `<collected>/article_check.xlsx`, including some Contract / partnership and Product launch rows (the existing labels have none).
