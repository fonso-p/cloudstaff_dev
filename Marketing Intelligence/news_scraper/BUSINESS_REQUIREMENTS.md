# News Scraper: Business Requirements (POC)

**Status:** proof of concept · runs locally · zero budget · November 2026

## 1. Purpose

The scraper finds recent news about a list of companies and turns it into the news input for the Account Priority Score: one `news_signal` (the type of news) and one `news_signal_date` per company. Reps use these to spot accounts with buying triggers such as funding, expansion or leadership change.

## 2. What it does

| # | Capability | Detail |
|---|---|---|
| 1 | **Takes a company list** | A CSV that needs only `company_name`. Optional columns: website, location, country, aliases, context words, a lookback per company. |
| 2 | **Searches free news sources** | Google News RSS (main source, 6+ months back), Bing News RSS (latest news only), the company's own website news feed (when it has one), and GDELT (opt-in, last ~90 days). |
| 3 | **Configurable lookback** | Default 180 days, set for all companies or per company. The first run pulls the whole window; later runs fetch only new articles since the last check. |
| 4 | **Builds a company card** | From the company's website (home and About pages, every 30 days): alternative and legal names, ticker, founders, city, and keywords that describe what it does. |
| 5 | **Decides if an article is about the company** | Collects identity evidence (domain, ticker, legal name, founders, context words, card keywords, city); 2 points confirm the company. Common-word names (e.g. "Deputy") must be used as the company, not as a title ("Deputy Mayor"), and need confirming evidence. Distinctive names count unless they appear only in a list or comparison, or written differently ("ROKT"). Articles whose text could not be read are judged on the headline alone, more strictly. Doubtful articles go to a review file with the reason. |
| 6 | **Classifies the news** | Keyword rules sort each article into one of the scoring model's categories: Funding round, PE buyout, M&A, Expansion / new office, Restructuring, Leadership change, or Other. Investor-profile and stock-chart pages are dropped. |
| 7 | **Optionally reads the full article** | With `--read-articles`, a separate `article_reader` module fetches the text. This improves classification and flags doubtful matches: company not named, context words missing, or not in English. |
| 8 | **Scores and picks one signal per company** | Each article's value is category strength × recency, both from `scoring_settings.json`. The highest-value article sets `news_signal` and `news_signal_date`. |
| 9 | **Separates "nothing found" from "not checked"** | `news_signal` "None" = sources were checked and nothing matched (a real zero). Blank = no source could be checked (unknown, so the score uses its baseline). |
| 10 | **Writes CSV outputs** | `company_summary.csv` (one row per company), `signal_events.csv` (every matched article), `review.csv` (doubtful matches to check by hand). |
| 11 | **Records every check** | Each source × company × run is logged with its date window and status (ok, error or skipped), so failures are visible and never mistaken for "no news". |

## 3. Boundaries

- **Inputs:** a company CSV and the read-only `reference materials/data/scoring_settings.json`. It changes nothing else.
- **Outputs:** CSV files in `out/` and a local SQLite database in `data/news.db`. No other system is updated.
- **Runs:** on one machine, started manually or by Windows Task Scheduler.
- **Network:** only public news pages and feeds, at about 1 request a second per source. It respects `robots.txt` when reading articles.
- **Data kept:** headline, link, publisher, date, match score, and (if read) the article text. The article text stays in the local database only.

## 4. Out of scope (not built)

- **Writing back to HubSpot**, the dashboard or the Priority Score workbook. Feeding the scoring is a manual step.
- **Paid news APIs** or any paid service, including LLMs.
- **AI or NLP models.** Matching and classification are keyword rules only.
- **Social media** (LinkedIn, X), job postings, or company-registry sources (ASX, Companies House, SEC EDGAR).
- **Finding a company's website** when it isn't supplied.
- **Scheduling, alerting, monitoring dashboards**, multi-user access and cloud hosting.
- **Non-English news.** It is searched, but filtered out when the text is read.
- **Event dates inside the text.** The publish date is used as the event date.

## 5. Known limitations

| Area | Limitation | Effect |
|---|---|---|
| Matching | A common-word name is only treated strictly if it is marked: by `context` words or `ambiguous=yes` in the CSV. Nothing detects it automatically. | An unmarked common name lets unrelated articles through. |
| Matching | Strict rules for common names and unread articles trade some recall for precision. | E.g. "Deputy maps shift-worker pressures" (real) went to review because the headline alone did not confirm it. |
| Matching | No website means no company card. | Matching uses the name, location and CSV columns only; flagged in the summary. |
| Matching | Card keywords come from the website's title and description and can include filler words. | Mitigated by a generic-word filter and by counting single words as at most 1 point. |
| Classification | Keyword rules can't tell who did what or understand negation. | "Binance names Airwallex veteran as CFO" counts as an Airwallex leadership change, and "denies layoffs" would count as Restructuring. |
| Classification | Most articles (~85% on the test set) are "Other / Unclassified", which still has strength 0.3. | A fresh generic mention can outrank an older real event in the summary. |
| Sources | Google and Bing News RSS are unofficial endpoints. | They can rate-limit or change format without notice. |
| Sources | GDELT is often rate-limited from this network and covers only ~90 days. | It is off by default. |
| Sources | Few small companies publish a website news feed. | The company-website source is often skipped. |
| Article text | About 40–45% of articles can't be read: paywalls, sites blocking scripts, or `robots.txt`. | Those articles are classified on the headline only. |
| Scale | Rate limits set the speed, not the hardware. | About 25–30 min a day for 1,000 companies (daily mode), +15–30 min with article reading; the first backfill takes 1–2 hours. |

## 6. Success measures for the POC (to be agreed)

- **Matching:** at least 90% of articles counted as matches are about the right company, on a hand-labelled sample of about 100.
- **Classification:** at least 80% of articles classified as a specific event are the right category.
- **Coverage:** at least 70% of target companies have a successful check every day.
- **Reliability:** the daily run for 1,000 companies finishes overnight without manual help.
