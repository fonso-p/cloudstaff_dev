"""Command line.

    python -m news_scraper run    --companies sample_companies.csv [--lookback-days 180] [--mode auto|backfill|incremental]
                                  [--sources google,bing,gdelt,newsroom] [--workers 6] [--limit N] [--db data/news.db]
                                  [--read-articles [--read-max-per-company 10] [--read-min-match 0.6]]
    python -m news_scraper read   [--max-per-company 10] [--min-match 0.6]      # text for articles already scraped
    python -m news_scraper export [--out out] [--db data/news.db] [--min-match 0.6] [--lookback-days 180]
    python -m news_scraper jobs     --companies companies.csv [--workers 6]      # open roles from careers pages
    python -m news_scraper filings  --companies companies.csv [--registers au,uk] # ASIC / Companies House / Gazette
    (export merges news, jobs and filings into signal_events.csv, told apart by signal_type)

Segment mode (news about an industry sector in a country, not one company):
    python -m news_scraper segment run    (--segments sample_segments.csv | --groups all --countries AU,NZ)
                                          [--themes all] [--lookback-days 90] [--mode auto|backfill] [--sources google,bing]
                                          [--workers 6] [--limit N] [--read-articles [--read-max-per-segment 5]]
    python -m news_scraper segment read   [--target newest|curated|uncertain] [--max-per-segment 20 (0 = all)]
    python -m news_scraper segment export [--out out] [--lookback-days 90] [--accounts accounts.csv]
    python -m news_scraper segment list   # industry groups, countries and themes
"""
import argparse
import json
import os
import sys

from .pipeline import build_profiles, export, read_companies, read_stored, run
from .sources import SOURCES

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(HERE, "..", "Marketing Intelligence", "reference materials", "data", "scoring_settings.json")   # read only
ACCOUNTS = os.path.join(HERE, "..", "Marketing Intelligence", "reference materials", "data", "accounts.csv")           # read only


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
    j = sub.add_parser("jobs", help="job signals: open roles from each company's careers page (job-system feeds or JobPosting data)")
    j.add_argument("--companies", required=True)
    j.add_argument("--workers", type=int, default=6)
    j.add_argument("--limit", type=int)
    j.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    f = sub.add_parser("filings", help="filings: AU (ASIC companies + business names) and UK (Companies House + Gazette) registers")
    f.add_argument("--companies", required=True)
    f.add_argument("--registers", default="au,uk", help="comma-separated: au, uk")
    f.add_argument("--limit", type=int)
    f.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    nl = sub.add_parser("nlp", help="entities, events, embeddings and zero-shot categories for stored articles (CPU, free)")
    ns = nl.add_subparsers(dest="action", required=True)
    nr = ns.add_parser("run", help="compute NLP results for articles that don't have them yet")
    nr.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    nr.add_argument("--scope", choices=["company", "segment", "all"], default="all")
    nr.add_argument("--stages", default="entities,events,embed,zeroshot", help="comma-separated: entities, events, embed, zeroshot")
    nr.add_argument("--zs-all", action="store_true", help="zero-shot every story, not only the ones that matched a company (slow)")
    nr.add_argument("--limit", type=int)
    nb = ns.add_parser("label", help="write a sheet of articles to label by hand (about_company, category)")
    nb.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    nb.add_argument("--out", default=os.path.join(HERE, "out", "labels.csv"))
    nb.add_argument("--n", type=int, default=200)
    nb.add_argument("--settings", default=SETTINGS if os.path.exists(SETTINGS) else None)
    nt = ns.add_parser("train", help="train the about-company combiner and the SetFit category model from a labelled sheet")
    nt.add_argument("--labels", required=True)
    nt.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    nt.add_argument("--settings", default=SETTINGS if os.path.exists(SETTINGS) else None)
    sg = sub.add_parser("segment", help="news about an industry sector in a country (trend digest, Priority Score tailwind, prospects)")
    ss = sg.add_subparsers(dest="action", required=True)
    sr = ss.add_parser("run", help="scrape sector x country news")
    sr.add_argument("--segments", help="CSV: industry_group, country, and optionally extra_terms, exclude_terms, lookback_days")
    sr.add_argument("--groups", help="instead of --segments: 'all' or industry groups separated by ';' (see: segment list)")
    sr.add_argument("--countries", default="AU", help="with --groups: country codes separated by ',' (default AU)")
    sr.add_argument("--themes", default="all", help="'all' or theme names separated by ';' (see: segment list)")
    sr.add_argument("--lookback-days", type=int, default=90, help="how far back to look (default 90; momentum compares the last 30 days with the 60 before)")
    sr.add_argument("--mode", choices=["auto", "backfill"], default="auto")
    sr.add_argument("--sources", default="google,curated",
                    help="comma-separated: google, curated (the sites in segment_sources.csv), bing and gdelt (opt-in: Bing returns almost "
                         "nothing for these queries, GDELT is slow)")
    sr.add_argument("--sources-file", default=os.path.join(HERE, "segment_sources.csv"), help="curated websites per industry and country")
    sr.add_argument("--workers", type=int, default=6)
    sr.add_argument("--limit", type=int, help="only the first N segments (testing)")
    sr.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    sr.add_argument("--read-articles", action="store_true", help="also fetch the text of the newest articles (better themes and checks)")
    sr.add_argument("--read-max-per-segment", type=int, default=5)
    se = ss.add_parser("export", help="write segment_summary, segment_events, segment_review, industry_trend and segment_companies CSVs")
    se.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    se.add_argument("--out", default=os.path.join(HERE, "out"))
    se.add_argument("--lookback-days", type=int, default=90)
    se.add_argument("--sources-file", default=os.path.join(HERE, "segment_sources.csv"))
    se.add_argument("--settings", default=SETTINGS if os.path.exists(SETTINGS) else None)
    se.add_argument("--accounts", default=ACCOUNTS if os.path.exists(ACCOUNTS) else None,
                    help="CSV with company_name (and account_id) to mark named companies as existing accounts")
    sd = ss.add_parser("read", help="fetch the text of segment articles already scraped (newest first)")
    sd.add_argument("--db", default=os.path.join(HERE, "data", "news.db"))
    sd.add_argument("--max-per-segment", type=int, default=20, help="0 = all")
    sd.add_argument("--target", choices=["newest", "curated", "uncertain"], default="newest",
                    help="newest: any unread; curated: articles from curated sources; uncertain: counted with no visible theme, and near misses")
    sd.add_argument("--sources-file", default=os.path.join(HERE, "segment_sources.csv"))
    sd.add_argument("--workers", type=int, default=6)
    ss.add_parser("list", help="show the industry groups, countries and themes")
    a = ap.parse_args(argv)

    if a.cmd == "segment":
        from . import segment as seg
        from .sectors import COUNTRIES, SECTOR_TERMS, THEMES, sector_of
        if a.action == "list":
            print("Industry groups (sector) and search terms:")
            for g, terms in SECTOR_TERMS.items():
                print(f"  {g}  ({sector_of(g)}): {', '.join(terms)}")
            print("\nCountries: " + ", ".join(f"{k} ({v['name']})" for k, v in COUNTRIES.items()))
            print("\nThemes (tailwind weight): " + "; ".join(f"{n} ({w:+.1f})" for n, w, *_ in THEMES))
        elif a.action == "run":
            if not (a.segments or a.groups):
                ap.error("segment run needs --segments FILE or --groups")
            sources = [s.strip() for s in a.sources.split(",") if s.strip()]
            if [s for s in sources if s not in seg.SEGMENT_SOURCES]:
                ap.error(f"segment sources are {seg.SEGMENT_SOURCES}")
            themes = None if a.themes.strip().lower() == "all" else [t.strip() for t in a.themes.split(";") if t.strip()]
            if themes and [t for t in themes if t not in {n for n, *_ in THEMES}]:
                ap.error(f"unknown theme(s); choose from: {'; '.join(n for n, *_ in THEMES)}")
            try:
                segments = seg.read_segments(a.segments) if a.segments else seg.make_segments(a.groups, a.countries)
            except ValueError as e:
                ap.error(str(e))
            os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
            seg.run_segments(segments[: a.limit], a.db, sources, themes, a.lookback_days, a.mode, a.workers,
                             {"max_per_segment": a.read_max_per_segment} if a.read_articles else None, sources_file=a.sources_file)
        elif a.action == "read":
            seg.read_segment_texts(a.db, a.max_per_segment, a.workers, target=a.target, sources_file=a.sources_file,
                                   settings_path=SETTINGS if os.path.exists(SETTINGS) else None)
        else:
            res = seg.export_segments(a.db, a.out, a.settings, a.lookback_days, a.accounts, a.sources_file)
            print(f"Wrote {a.out}: {res['segments']} segments, {res['events']} articles counted, {res['review']} to review, "
                  f"{res['companies']} companies named ({res['new_prospects']} not in accounts) · {dict(res['status'])}")
        return

    if a.cmd == "nlp":
        from . import nlp
        if a.action == "run":
            stages = [s.strip() for s in a.stages.split(",") if s.strip()]
            nlp.run(a.db, a.scope, stages, a.zs_all, a.limit)
        elif a.action == "label":
            from .pipeline import judge_all
            events, review = judge_all(a.db, a.settings)
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            buckets = nlp.label_sheet(events, review, a.out, a.n)
            print(f"Wrote {a.out}: {sum(buckets.values())} rows to label · " + " · ".join(f"{b} {n}" for b, n in buckets.items()))
        else:
            from .pipeline import judge_all
            events, review = judge_all(a.db, a.settings)
            feats = {(r["company_id"], r["_key"]): r["_features"] for r in events + review if r.get("_features")}
            rep = nlp.train(a.labels, feats)
            print(json.dumps(rep, indent=2))
        return

    if a.cmd == "run":
        sources = [s.strip() for s in a.sources.split(",") if s.strip()]
        bad = [s for s in sources if s not in SOURCES]
        if bad:
            ap.error(f"unknown source(s) {bad}; choose from {list(SOURCES)}")
        companies = read_companies(a.companies)[: a.limit]
        os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
        read = {"min_match": a.read_min_match, "max_per_company": a.read_max_per_company} if a.read_articles else None
        run(companies, a.db, sources, a.lookback_days, a.mode, a.workers, read)
    elif a.cmd == "jobs":
        from .jobs import run_jobs
        os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
        run_jobs(read_companies(a.companies)[: a.limit], a.db, a.workers)
    elif a.cmd == "filings":
        from .registers import run_filings
        regs = [r.strip().lower() for r in a.registers.split(",") if r.strip()]
        if [r for r in regs if r not in ("au", "uk")]:
            ap.error("registers are au, uk (US filings are not covered yet)")
        os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
        run_filings(read_companies(a.companies)[: a.limit], a.db, regs)
    elif a.cmd == "profile":
        build_profiles(read_companies(a.companies), a.db, a.refresh)
    elif a.cmd == "read":
        read_stored(a.db, a.min_match, a.max_per_company, a.workers)
    else:
        res = export(a.db, a.out, a.settings, a.min_match, a.lookback_days)
        print(f"Wrote {a.out}: {res['companies']} companies, {res['events']} matched articles, {res['review']} to review · {dict(res['status'])}")


if __name__ == "__main__":
    main()
