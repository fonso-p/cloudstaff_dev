# News scraper (proof of concept)

This tool finds recent news about a list of companies and turns it into the `news_signal` / `news_signal_date` inputs used by the Priority Score. It is a zero-budget POC:

- Runs locally.
- Uses only free sources.
- Needs no new packages: it uses `requests` and `beautifulsoup4`, which are already in the repo's `.venv`.
- Stores everything in one SQLite file.

## Run it (from this folder)

```bash
../../.venv/Scripts/python.exe -m news_scraper run --companies sample_companies.csv     # scrape
../../.venv/Scripts/python.exe -m news_scraper export                                   # write out/*.csv
```

| Option | What it does |
|---|---|
| `--lookback-days 180` | **The lookback toggle.** How far back to look: 180 = 6 months (default). A `lookback_days` column in the CSV overrides it for one company. |
| `--mode auto` | Default. The first run for a company pulls the whole lookback window. After that, only new articles are fetched: since the last successful check, with a 2-day overlap. If you raise the lookback beyond what was already checked, it backfills again automatically. |
| `--mode backfill` | Always pull the whole window. |
| `--sources google,bing,newsroom` | Which sources to use (see below). Add `gdelt` to include it. |
| `--workers 6` | Companies processed in parallel. Each source still has its own rate limit, so adding workers does not make any source go faster. |
| `--limit N` | Only the first N companies, for testing. |

## Reading the full article (optional)

Reading full articles is handled by **`article_reader/`**, a separate package that turns a URL into clean article text. It does not import `news_scraper`, and `news_scraper` only loads it when reading is switched on.

```bash
# switched on during a scrape: reads the newest matched articles that have no text yet
../../.venv/Scripts/python.exe -m news_scraper run --companies sample_companies.csv --read-articles [--read-max-per-company 10] [--read-min-match 0.6]
# or afterwards, for articles already scraped
../../.venv/Scripts/python.exe -m news_scraper read [--max-per-company 10]
# or on its own, for any URL
../../.venv/Scripts/python.exe -m article_reader https://example.com/some-article [--json]
```

**How it reads (free: `requests` + BeautifulSoup only)**

1. **Google News links** (`news.google.com/rss/articles/…`) are first turned into the publisher's real URL. This uses the same internal call the Google News page makes, so it is unofficial; if it fails, the read is recorded as `decode_failed`.
2. **`robots.txt` is respected.** Pages it disallows are recorded as `blocked_robots` and not fetched. Each publisher also gets its own polite rate limit.
3. **Text extraction** tries three methods in order:
   - the `articleBody` the publisher declares in its page data (JSON-LD)
   - otherwise, the `<article>` or the block with the most paragraph text, with menus, ads, share bars and so on removed
   - otherwise, the meta description, recorded as `too_short`
4. **Every result is stored with a status**, in the `article_texts` table: `ok`, `too_short` (paywall or JavaScript-only page), `http_error` (often a 403 from sites that block scripts), `blocked_robots`, `decode_failed`, `not_html` or `error`.
   - Failed reads are retried after 7 days.
   - Successful reads are never fetched again.

**What the text adds on export**

- **Classification:** if the headline alone says nothing specific ("Other"), the first 600 characters of the article decide the category.
- **A check on the match.** The article moves to `review.csv`, with the reason in the `check` column, if:
  - the text never names the company (or its domain), or
  - the company has `context` words and none appear, or
  - the article is not in English.

  On the test list, this caught "Rajasthan Deputy CM…" (for Deputy) and a Somali article where "xero" means "camp" (for Xero).
- **`signal_events.csv` gains three columns:** `text_status`, `check`, and `lead` (the article's opening ~300 characters).

**Results on the test list:** about 55–60% of articles were read in full, with a median of about 2,800 characters. Most failures are 403 errors from publishers that block automated requests, or paywalls. Articles that couldn't be read still count, just without the text-based checks.

**Speed:** decoding a Google News link takes 2 requests to Google at about 1 a second, so reading is limited to about 1 Google-sourced article every 2–3 seconds; other publishers are read in parallel. In daily mode only new articles are read, so 1,000 companies typically means a few hundred reads, about 15–30 minutes extra. Use `--read-max-per-company` to cap it.

**Copyright:** the text is kept only in the local database, to classify and check matches. Do not republish it. The CSV exports include only a ~300-character lead and the link.

## Input CSV

Only `company_name` is required.

| Column | Example | Used for |
|---|---|---|
| `company_name` | Culture Amp | The search. Legal suffixes (Pty Ltd, Inc…) are removed. |
| `website` | cultureamp.com | **Optional.** Finds the company's own news feed, and articles mentioning the domain count as a stronger match. Without it, matching uses the name and location only, and the summary says so. |
| `location`, `country` | Melbourne, AU | A matching hint. The country also sets the Google News region (AU, NZ, UK, US…). |
| `aliases` | CultureAmp;Culture Amp Pty Ltd | Other names, separated by `;`. Searched with OR. |
| `context` | software;rostering | **For company names that are common words** (Deputy, Orchard, Summit…). Added to the search so only articles that also mention one of these words come back. |
| `ticker` | ASX:XRO | Strong identity evidence when an article mentions it. Matched case-sensitively, so "TEAM" does not match "team". |
| `ambiguous` | yes / no | Whether the name is a common word. If blank, it is assumed **yes** when `context` words are given, otherwise **no**. |
| `company_id` | your HubSpot or account ID | Keeps results linked to your records. If blank, an ID is made from the name and website. |
| `lookback_days` | 365 | Overrides the lookback for this company only. |

## Sources (all free)

| Source | How far back | Notes |
|---|---|---|
| `google` | 6+ months | Google News RSS search: the main source. It returns up to 100 results per query, so busy companies are searched month by month. It is not an official API, so keep the rate low (≈1 request a second). |
| `bing` | Recent only | Bing News RSS. It has no date filter, so it acts as a top-up for the latest news. |
| `newsroom` | Whatever the site publishes | The company's own RSS/Atom feed, found once from the website and re-checked every 30 days. Skipped when there is no website. On the test list, 2 of 7 websites had a feed. |
| `gdelt` | Last ~90 days | **Opt-in.** GDELT allows only one request at a time, 5+ seconds apart. From this network it returned "rate limited" even 12 seconds apart, so it is off by default. |

## Output (`out/`)

- **`company_summary.csv`**: one row per company, in the scoring's terms.
  - `news_signal` and `news_signal_date` come from the strongest event: category strength × recency, read from `reference materials/data/scoring_settings.json`.
  - `news_signal` blank = **not checked** (the score uses the baseline). `news_signal` "None" = **checked, found nothing** (a real zero). These are the two kinds of "empty" in the scoring model.
  - It also includes the headline and link, article counts, which sources worked, failed or were skipped, and a note when there is no website.
- **`signal_events.csv`**: every matched article, with category, strength, recency, match score and link.
- **`review.csv`**: possible matches (match score 0.4–0.6) to check by hand.

Articles are classified again on every export, so changes to the rules in `classify.py` apply without scraping again.

## Company card (`profile.py`)

Each company with a website gets a card, built from its home page and About page and rebuilt every 30 days. It holds:
- the site name, legal name and alternative names (e.g. SafetyCulture's site now says "Mitti")
- the ticker, founders and city, from the structured page data (JSON-LD) when the site provides it
- up to 12 keywords and short phrases from the page title and description (e.g. Deputy: "employee scheduling", "payroll software", "labor forecasting")

The card is built automatically during `run`. To see what was found:

```bash
../../.venv/Scripts/python.exe -m news_scraper profile --companies sample_companies.csv [--refresh]
```

## Does an article count? (`match.py`, applied at export)

Each article collects **identity evidence**: points for signs that it means *this* company.

| Evidence | Points |
|---|---|
| Website domain, ticker, legal or alternative name, founder or executive | 2 |
| A `context` word (chosen by a person) | 2 |
| A card keyword phrase | 1 each |
| Card single words | 1 in total |
| City or country | 1 |

**2 points confirm the company.** What else is required depends on the name and on whether the article text was read:

| | Article text read | Text not read (stricter) |
|---|---|---|
| **Ambiguous name** (Deputy) | Named as the company, not as a title ("Deputy Mayor") or ordinary word ("deputy"), **and** 2+ points in the text | Named as the company in the headline, **and** 2+ points in the headline and summary |
| **Distinctive name** (Atlassian) | Named in the text, written the company's way ("ROKT" or "xero" don't count). A passing mention in the headline needs 2+ mentions in the text, or 2+ points | Named in the headline, written the company's way, and not a passing mention (lists like "Adobe, Canva, CapCut", comparisons like "X vs Canva", "Canva alternatives"), unless 2+ points confirm it |

Articles that fail go to `review.csv` with the reason in the `check` column. The `evidence` column shows what was found.

**On the 10 test companies:**
- **Deputy:** 35 unrelated articles moved to review ("Deputy Mayor", "deputy minister", "Deputy CM"…), with 1 real article lost.
- **Rokt:** 5 articles about an ETF with the ticker "ROKT" moved to review.
- **Distinctive names:** they kept 98% of their articles; only lists, comparisons and junk were removed.

## How it decides

- **The quick match score at scrape time** (`match.py`) decides what is stored. Each article gets a score from 0 to 1:
  - name in the headline: +0.6
  - name in the summary only: +0.4
  - website domain mentioned: +0.3
  - location or context word mentioned: +0.15
  - the company's own website: 1.0

  Ticker, legal name or a founder count like the domain (+0.3), and card keywords like location (+0.15). A score of 0.4 or more is stored; at export, an article also needs 0.6 or more, plus the identity checks above, to count.
- **What kind of news?** (`classify.py`) Keyword rules sort each article into the scoring categories: Funding round, PE buyout, M&A, Expansion / new office, Restructuring, Leadership change, otherwise "Other / Unclassified".
  - The rules exclude common false positives, such as "raises price target", "X-backed start-up raises", "stocks to buy" and "talent acquisition".
  - Company-profile pages (funding lists, stock charts) are dropped entirely.

## Results on the 10 sample companies (Nov 2026)

- **6-month backfill:** about 800 matched articles. Every company was found, and Google and Bing worked for all 10.
- **Daily update:** 10 companies in **16 seconds**, finding 31 new articles.
- **Correct examples:** the Canva layoffs and restructure, Airwallex's Series H, Culture Amp's job cuts, Airwallex's appointments, Octopus Energy entering the Irish market.

## Scale: 1,000+ companies a day

- **Daily update:** about 1 Google + 1 Bing query per company. At the polite rate of ≈1 request a second per source, run in parallel, that's about **25–30 minutes for 1,000 companies**.
- **First backfill:** most small companies need one Google query; busy ones need up to 7. That's roughly 1–2 hours for 1,000, done once.
- **Storage:** a few thousand articles a day in SQLite is no problem.
- **To schedule it locally,** use Windows Task Scheduler to run `run` then `export` every night.

## Known limits (and the next fixes, all still free)

1. **Common company names.**
   - Without a website or `context`, "Deputy" matches deputy mayors, and "Rokt" matched stock-option pages for a ticker.
   - **Fix in the input:** add `context` words for those companies.
   - **Fix in code:** have a free local LLM (e.g. [Ollama](https://ollama.com) with a small model) re-check matches between 0.4 and 0.7.
2. **Keyword classification is approximate.**
   - Without `--read-articles` it sees headlines only (Google gives no article summary).
   - Even with the text, keyword rules can't tell who did what ("Xero backers fund a start-up" is not Xero raising money).
   - **Fix:** the same local LLM, given the article text that `article_reader` now provides, classifying each article and quoting the evidence.
3. **Google News RSS is unofficial.**
   - It can rate-limit or change format without notice.
   - The coverage table records every failure, so a failed check never looks like "no news".
4. **Few small companies publish a news feed on their website.**
   - **Fix:** a sitemap or news-page scraper.
5. **More free sources to add:**
   - SEC EDGAR (US filings)
   - UK Companies House (officer changes; needs a free API key)
   - ASX announcements (Australian listed companies)
