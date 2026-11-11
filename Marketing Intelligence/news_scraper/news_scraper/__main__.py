"""Command line.

    python -m news_scraper run    --companies sample_companies.csv [--lookback-days 180] [--mode auto|backfill|incremental]
                                  [--sources google,bing,gdelt,newsroom] [--workers 6] [--limit N] [--db data/news.db]
                                  [--read-articles [--read-max-per-company 10] [--read-min-match 0.6]]
    python -m news_scraper read   [--max-per-company 10] [--min-match 0.6]      # text for articles already scraped
    python -m news_scraper export [--out out] [--db data/news.db] [--min-match 0.6] [--lookback-days 180]
"""
import argparse
import os
import sys

from .pipeline import build_profiles, export, read_companies, read_stored, run
from .sources import SOURCES

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(HERE, "..", "reference materials", "data", "scoring_settings.json")   # read only


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="news_scraper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="scrape news for a list of companies")
    r.add_argument("--companies", required=True, help="CSV: company_name, and optionally company_id, website, location, country, aliases, lookback_days")
    r.add_argument("--lookback-days", type=int, default=180, help="how far back to look (default 180 = 6 months); a lookback_days column overrides it per company")
    r.add_argument("--mode", choices=["auto", "backfill", "incremental"], default="auto",
                   help="auto: whole window the first time, then only new articles (default); backfill: always the whole window")
    r.add_argument("--sources", default="google,bing,newsroom",
                   help="comma-separated: google, bing, newsroom, gdelt (gdelt is opt-in: 1 request per 5+ s, last ~90 days, often rate-limited)")
    r.add_argument("--workers", type=int, default=6)
    r.add_argument("--limit", type=int, help="only the first N companies (testing)")
    r.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    r.add_argument("--read-articles", action="store_true", help="also fetch the full text of matched articles (article_reader package); off by default")
    r.add_argument("--read-max-per-company", type=int, default=10, help="most articles to read per company per run, newest first (default 10)")
    r.add_argument("--read-min-match", type=float, default=0.6, help="only read articles with at least this match score (default 0.6)")
    p = sub.add_parser("profile", help="build each company's card from its website and show what was found")
    p.add_argument("--companies", required=True)
    p.add_argument("--refresh", action="store_true", help="rebuild even if the card is less than 30 days old")
    p.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    d = sub.add_parser("read", help="fetch the full text of articles already scraped (article_reader package)")
    d.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    d.add_argument("--max-per-company", type=int, default=10)
    d.add_argument("--min-match", type=float, default=0.6)
    d.add_argument("--workers", type=int, default=6)
    e = sub.add_parser("export", help="write signal_events.csv, company_summary.csv and review.csv")
    e.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    e.add_argument("--out", default=os.path.join(HERE, "out"))
    e.add_argument("--min-match", type=float, default=0.6)
    e.add_argument("--lookback-days", type=int, default=180)
    e.add_argument("--settings", default=SETTINGS if os.path.exists(SETTINGS) else None)
    a = ap.parse_args(argv)

    if a.cmd == "run":
        sources = [s.strip() for s in a.sources.split(",") if s.strip()]
        bad = [s for s in sources if s not in SOURCES]
        if bad:
            ap.error(f"unknown source(s) {bad}; choose from {list(SOURCES)}")
        companies = read_companies(a.companies)[: a.limit]
        os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
        read = {"min_match": a.read_min_match, "max_per_company": a.read_max_per_company} if a.read_articles else None
        run(companies, a.db, sources, a.lookback_days, a.mode, a.workers, read)
    elif a.cmd == "profile":
        build_profiles(read_companies(a.companies), a.db, a.refresh)
    elif a.cmd == "read":
        read_stored(a.db, a.min_match, a.max_per_company, a.workers)
    else:
        res = export(a.db, a.out, a.settings, a.min_match, a.lookback_days)
        print(f"Wrote {a.out}: {res['companies']} companies, {res['events']} matched articles, {res['review']} to review · {dict(res['status'])}")


if __name__ == "__main__":
    main()
