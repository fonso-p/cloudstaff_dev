# Apollo lead grading: plan (history)

> **This is the original design and decision log, kept for history. The current, complete description is [README.md](README.md)**: run steps, every rule, results and open questions.
>
> **Names below are the 18 Nov 2026 layout.** Since 26 Nov 2026: `apollo_lead_grading/grade_leads.py` → `src/cloudstaff_dev/leads/` (run with `python -m cloudstaff_dev.leads run apollo_emea`); `News Scraper/apollo_emea/` → collectors in `src/cloudstaff_dev/signals/` and `leads/prepare.py`, hand-kept files in `Marketing Intelligence/lead_lists/apollo_emea/`; `format data/priority_scoring.py` → `src/cloudstaff_dev/scoring/priority.py`; `format data/` → `Marketing Intelligence/account_priority/`; `build_dashboard.py` → `src/cloudstaff_dev/dashboards/build.py`; the local `Data` folder → `<MI>/inputs/` and `<MI>/outputs/` (`<MI>` = OneDrive `Desktop/Projects/Marketing Intelligence Priority`).

**Status:** built 18 Nov 2026 (`grade_leads.py` [now `src/cloudstaff_dev/leads/`], `dashboard_template.html` [now `src/cloudstaff_dev/dashboards/templates/lead_grades.html`]; how to run: [README.md](README.md)) · **First input:** Apollo EMEA lists (UK care homes, UK cybersecurity), 18 Nov 2026

**Decided 18 Nov 2026:** D1 chip only, no points · D2 half strength · D3 tiers within the lead list · D4 a **standalone** EMEA / Apollo dashboard, one list owned by **BDM Marketing** (no SDR / BDM / Marketing split) · Fit: only 26 UK clients, so the industry-only profile (all countries) replaces the UK one · Ties: scores tie in large blocks, so equal scores are ordered by a 0–4 **readiness** count from the data we have (funding label, verified decision-maker, recent news or posts, target industry). It never adds points.

**Decided later on 18 Nov 2026:** tiers are ranked **within each Apollo list** (separate campaigns) · leads outside a list's target industry are **Check fit** (scored, not tiered; **changed 24 Nov 2026:** now tiered like the rest, with a "check that the industry matches" note in the company panel) · a company's **own blog posts earn no news points** unless the post is a relevant event · the **parent company's** events count at half strength when stronger than the lead's own news, marked "Parent" · half-strength news never triggers Act now · job recency (30 / 90 days, newest posting) shown on the page · LinkedIn jobs are not scraped (its terms forbid automated access) · "Other" news is not shown as a reason · hiring shown in bands (1–2 … 21+) with recency · leads are **pre-HubSpot**: website activity and Diamond referral are not scored (their points shared out in the live proportions) · hiring points count only **roles Cloudstaff fills** (Staff Central JP titles) · event details and website service lines added · new-prospect discovery is out of scope for now · "Other" news earns no points · Apollo funding shown as its own chip with how it compares to the news (after the classifier change: 2 match, 7 differ, 32 not in the news; 5 deals in the news Apollo doesn't have). **Open: how to reconcile Apollo funding with the news** · target-industry check now uses activity codes, Companies House and website service lines (9 mislabelled care providers rescued, suppliers stay "Check fit") · fit chips follow the dashboard's 1.5× rule · industry trend out of the score (context only) · Why = signals only, descriptive chips in the company profile · competitor-client map built from candidates' CVs (no Apollo UK match; 12 existing clients matched) · two new event types (Contract / partnership win 0.5, Product launch 0.3) taught to the News Scraper classifier, sponsorships excluded · missed events recorded in `manual_events.csv`, labelled by Claude · folder renamed `apollo_lead_grading` (docs now in `Marketing Intelligence/lead_grading/`, code in `src/cloudstaff_dev/leads/`, since 26 Nov 2026)

## 1. Goal

Grade bought or prospected leads (starting with Apollo exports) with the **same Priority Score** as the HubSpot prospects. That way a Tier 1 EMEA lead means the same as a Tier 1 New Logo account on the dashboard. The grade combines three kinds of information:

| Kind | Source | Examples |
|---|---|---|
| **What we have** | Apollo export | Website, industry, headcount, city, funding label, tech stack, contacts and their seniority |
| **What we gather** | `News Scraper` (company mode, jobs, filings, segment mode) | Dated news events, open roles and hiring spikes, Companies House status and changes, UK industry trend |
| **What we know internally** | MyStaff, HubSpot, Client Propensity | Already a client? Already in HubSpot (owner, deals)? How do past clients *like this one* grow (fit)? |

## 2. Where things live

| Folder | Job | Writes |
|---|---|---|
| `News Scraper/apollo_emea/` [now `src/cloudstaff_dev/signals/`, `leads/prepare.py`; outputs in `<MI>/outputs/collected/apollo_emea/`] | **Collect only.** `prepare.py` turns the Apollo export into the scraper's company list (`company_id = apollo-<Apollo Account Id>`). `overrides.csv` holds name fixes. Runs `run`, `jobs` and `filings`, then `export` | `apollo_emea/out/company_summary.csv`: one row per company with `news_signal`, `news_signal_date`, `signal_confidence`, `job_postings_30d`, `hiring_spike`, `filing_signal`, `registered_status` and more |
| `Marketing Intelligence/apollo_lead_grading/` [now `src/cloudstaff_dev/leads/`] | **Grade.** Reads the raw Apollo export, the scraper's `company_summary.csv` and the internal data, scores with the Priority Score settings and adds the lead-specific gates and chips | Local data folder only: `lead_grades_<list>.xlsx` and dashboard JSON |
| `Marketing Intelligence/format data/` [now `account_priority/`; scoring in `src/cloudstaff_dev/scoring/priority.py`] | The Priority Score pipeline. The **scoring functions and settings** move into a module that both pipelines import (§6, step 2) | Unchanged |

```
Apollo export (local) ──► News Scraper/apollo_emea ──► company_summary.csv (news, jobs, filings)
        │                                                        │
        └──────────────► Marketing Intelligence/apollo_lead_grading ◄───┘
                             ▲  MyStaff, HubSpot, Client Propensity profiles, industry_trend
                             ▼
                lead grades (xlsx, JSON) ──► dashboard list "EMEA leads"
```

Raw exports, contacts and outputs stay in `~/Desktop/Projects/Marketing Intelligence Priority/Data` (the MI convention) [now `<MI>/inputs/` and `<MI>/outputs/` on the OneDrive Desktop]. The repo holds code and docs only. Apollo contacts are personal data.

## 3. How an Apollo lead maps to the Priority Score

The lead becomes an account row in the pipeline's existing output contract (BUSINESS_RULES §4), so the scoring code doesn't change.

**Group 1 (company) and lineage**

| Column | Rule |
|---|---|
| `account_id` | `AP-<Apollo Account Id>` (`apollo-<id>` in the scraper) |
| `company_name` | Apollo `Company Name`, cleaned the way `prepare.py` cleans it |
| `goal` | `New Logo`. An existing MyStaff client becomes a **gate** (§4), not a new account |
| `industry` | Apollo `Industry` → the 18 groups through `INDUSTRY_GROUPS`, compared case-insensitively with "&" = "and" (Apollo uses LinkedIn's lowercase names). Gaps today: `furniture` (unmapped), and `security & investigations` maps to Business & Consumer Services, though for the cyber list it means Technology |
| `employee_band` | Apollo `# Employees` → `BAND_EDGES` |
| `region` | Apollo `Company Country` → `COUNTRY_CODE` (`UK`) |
| `website_domain` | Apollo `Website`, falling back to the contacts' email domain |
| `source` | `Apollo: <list name>` |

**Group 2 (signals)**

| Column | Source | Notes |
|---|---|---|
| `news_signal`, `news_signal_date` | Scraper `company_summary.csv`, joined on the id | `high` confidence at full strength. **Decision D2** covers `medium` / `low` |
| `job_postings_30d`, `hiring_spike` | Scraper jobs columns | Blank stays blank (unknown). `hiring_spike` needs a second run 21+ days later |
| `web_visits_30d`, `team_builder_visit`, `form_fill_30d` | HubSpot activity, if the lead's domain is in HubSpot | Otherwise unknown: the same average fill for every lead, so it doesn't change their order |
| `diamond_referral`, `prior_bpo_flag` | HubSpot, if present | Otherwise blank = No (the model's rule) |
| `industry_trend` | `News Scraper/out/industry_trend.csv` [now `<MI>/outputs/segments/industry_trend.csv`], UK row of the group | Needs a segment run for Healthcare & Wellness × UK and Technology × UK |
| Fit (`fit_growth_*`, `fit_reach_10_*`, `fit_branch_1y_*`) | Client Propensity `prospect_profiles.csv`, key **`industry\|Unknown`** (industry only, all countries) | The UK profiles rest on 26 UK clients, so they're not used (decided 18 Nov). Technology = **Medium** (6.3% reach 5+ seats in a year), Healthcare & Wellness = **Low** (3.0%); both **High** for a second department |

The score is the live profile `dashboard_v3`, New Logo: website 30, news and jobs 30 (15 + 15), Diamond 10, Competitor client 10, Fit 20, times the industry modifier, plus the Act now bonus.

## 4. What lead grading adds (not in today's model)

| Addition | Rule | Why |
|---|---|---|
| **Gate: distressed** | Companies House status *in administration*, *liquidation*, *proposal to strike off*, *dissolved*, or a Gazette insolvency notice → grade `Excluded`, no score | Pilot: 4 of 230 (J S Wright & Co, Qualia Care, Trustify, Amica Care) |
| **Gate: existing client** | Domain or company number matches an active MyStaff client → `Existing client`, sent to the AM's list, not to SDR | Pilot: 0 matches against the 1,327 priority-list accounts |
| **Gate: already owned in HubSpot** | Domain matches a HubSpot company with an owner or an open deal → keep the owner, show "in HubSpot" | The HubSpot report in the data folder holds only part of HubSpot. Needs a full company export, or the HubSpot connector authorised |
| **Flag: outside the list's target** | Apollo industry outside the list's intended groups (e.g. construction, furniture or an investor in the care list) → `Check fit` | About 40 of 175 care-list accounts |
| **Apollo funding label** | Undated, so no points by itself. Shown as a chip ("Apollo: Series A, undated"). Gets points once the news or a filing dates it. **Decision D1** | Pilot: 2 of 11 labels were dated by news (Forge Care, Milkwood Care) |
| **Filing events** | Newly registered, name change, new trading name: chips. Ownership change (Companies House PSC, when added): a News-family trigger like PE buyout | Dated and reliable for small UK firms, where news is thin |
| **Contact readiness** | Verified email, decision-maker seniority (owner, founder, C-suite, director), number of contacts. Shown next to the grade, **not in the score** | The score ranks the account; contact readiness decides whether we can work it today |
| **Pitch chips** | CRM plus helpdesk (HubSpot, Zendesk, Intercom) → "support / sales-ops team". Finance software (Sage, Xero) → "in-house finance admin". No points | A conversation opener, not evidence of intent |

**Output per lead:** `priority_score`, `tier`, `grade` (Tier 1–3, Excluded, Existing client), `act_now_triggers`, chips (the reasons), and the best contact and their title. Then the lineage, plus `news_checked`, `filings_status` and `jobs_status`, so "not checked" never looks like "nothing found".

## 5. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| **D1** | Does an undated Apollo funding label earn points? | **No points, chip only**, until a date is found. The other option, scoring it at the 91–180-day recency (0.4), rewards a label that may be years old |
| **D2** | `medium` / `low` news confidence | Half strength, as the News Scraper README suggests, until labels show medium beats a coin flip |
| **D3** | Tiers: percentile within the lead list, or the main list's cut-offs? | **Within the list for now**: the main list's New Logo scores still come from mock signals, so its cut-offs mean nothing yet. Switch to shared cut-offs once news and jobs are live for HubSpot accounts too |
| **D4** | One dashboard or separate? | A separate "EMEA leads" list on the same dashboard build (`build_dashboard.py` with a second JSON), merged into New Logo when the main pipeline goes live |
| **D5** | Who receives graded leads? | Today: SDR, or BDM for Act now and the top 10%, per the existing routing. Confirm the EMEA owners (Apollo's contact owner is a single person today) |

## 6. Steps

| # | Step | Where | Done when |
|---|---|---|---|
| 1 | **Full collection** for the 230 companies: `run --read-articles`, `jobs` (with the browser pass), `filings`, `export`. Review generic names and add them to `overrides.csv`. Segment runs for Healthcare & Wellness × UK and Technology × UK, with UK cyber and care trade press added to `segment_sources.csv` | News Scraper | `company_summary.csv` covers 230 with news checked; `industry_trend.csv` has both UK rows |
| 2 | **Move the scoring into a module.** Take `score_accounts()`, `score_account()`, `_signals()`, `act_now_bonus()`, `percentile_tier()`, `known_mean_fill()`, `_fit_signal()` and the settings in §0b out of the notebook into `format data/priority_scoring.py`. The notebook imports it | MI `format data` | Both golden tests still pass with 0 mismatches |
| 3 | **Build `apollo_lead_grading`**: extract the Apollo export, standardise it to the contract (§3), match MyStaff and HubSpot (gates, §4), join the scraper's results, add fit and trend, score with the module, write the xlsx and JSON locally | MI `apollo_lead_grading` | DQ checks pass: ids unique, every lead scored or gated, coverage counts reconcile with the scraper |
| 4 | **Dashboard list** "EMEA leads": Why chips (signals, Apollo label, filings, pitch) and the contact column | MI `build_dashboard` | Page check prints `errors: []` |
| 5 | **Pilot with reps** on the cyber list (55 companies, Medium fit): did the grade match their judgement, and which chips helped? Record outcomes | Sales | 2 weeks of feedback |
| 6 | **Merge into the main pipeline** as a third source (`Apollo`) beside HubSpot and MyStaff, once news and jobs are live for all accounts (no mixing of mock and real signals) | MI `format data` | `ENRICHMENT_MODE = "live"` for news and jobs |

**Later, more internal data:** win-back (former Cloudstaff clients, by domain), champion tracking (Apollo contacts who used to work at a client), and Companies House officers and PSC (dated leadership and ownership changes).

## 7. What the pilot already shows (18 Nov 2026)

- **Collection works on Apollo data:** all 230 companies have a website, and 162 matched Companies House.
- **Two real, dated events** in a 20-company news sample: Forge Care (PE buyout, Aug 2026) and Milkwood Care (acquired by Holmwood Care Group, Aug 2026). At 84 and 92 days old they get recency factors of 0.7 and 0.4. Forge Care's PE buyout would have been an Act now trigger within 30 days; M&A is not a trigger.
- **Job signals are thin** for these segments (2 of 20 readable). Hiring will mostly be unknown, so news, filings and fit will carry the grade.
- **Fit differs by list:** cyber (Technology | UK) Medium, care homes (Healthcare & Wellness | UK) Low. Expect the cyber list to grade higher, other things equal.
- Details and run commands: `News Scraper/apollo_emea/README.md` (now [`../lead_lists/apollo_emea/COLLECTING.md`](../lead_lists/apollo_emea/COLLECTING.md); current run commands in [README.md](README.md) §3).
