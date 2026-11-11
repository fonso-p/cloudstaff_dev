"""Run the scrape for a list of companies, and export the results for the Priority Score.

Window per company and source (the lookback toggle):
  - lookback_days: the company's own value if given, else --lookback-days (default 180).
  - backfill: the whole lookback window. Used the first time, with --mode backfill, or when the lookback
    was raised beyond what has already been checked.
  - incremental (the daily run): only since the last successful check, minus a 2-day overlap for articles
    that are indexed late. One cheap query per company per source, whatever the lookback.
"""
import csv
import datetime as dt
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import http, profile
from .classify import OTHER, classify, load_settings, recency_factor
from .match import MATCH, POSSIBLE, Matcher, root_domain
from .sources import GDELT_MAX_DAYS, SOURCES, SkipSource, find_feed
from .store import Store, dedupe_key

OVERLAP_DAYS = 2
FEED_RECHECK_DAYS = 30
COUNTRY_NAMES = {"AU": "Australia", "NZ": "New Zealand", "UK": "United Kingdom", "GB": "United Kingdom", "US": "United States",
                 "PH": "Philippines", "CA": "Canada", "SG": "Singapore", "IE": "Ireland"}


@dataclass
class Company:
    name: str
    company_id: str = ""
    domain: str = ""
    location: str = ""
    country: str = ""
    aliases: list = field(default_factory=list)
    context: list = field(default_factory=list)      # words that narrow a common name in searches, e.g. Deputy -> software;scheduling
    lookback_days: int | None = None
    ticker: str = ""                                 # e.g. XRO or ASX:XRO; strong identity evidence when an article mentions it
    ambiguous: bool | None = None                    # name is a common word? None = assume yes when context words are given

    def __post_init__(self):
        self.domain = root_domain(self.domain)
        if not self.company_id:
            self.company_id = re.sub(r"[^a-z0-9]+", "-", f"{self.name} {self.domain}".lower()).strip("-")

    @property
    def places(self):
        """Location words used as a matching hint: 'Brisbane, QLD' + country -> Brisbane, QLD, Australia."""
        p = [x.strip() for x in re.split(r"[,;/]", self.location or "") if x.strip()]
        if self.country:
            p.append(COUNTRY_NAMES.get(self.country.upper(), self.country))
        return p


def read_companies(path):
    """CSV with company_name (required) and optional company_id, website, location, country, aliases and context
    (both ';'-separated), lookback_days, ticker, ambiguous (yes/no)."""
    def yes_no(v):
        v = (v or "").strip().lower()
        return True if v in ("yes", "y", "true", "1") else False if v in ("no", "n", "false", "0") else None
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("company_name"):
                continue
            out.append(Company(name=r["company_name"], company_id=r.get("company_id", ""), domain=r.get("website") or r.get("domain", ""),
                               location=r.get("location", ""), country=r.get("country", ""),
                               aliases=[a.strip() for a in r.get("aliases", "").split(";") if a.strip()],
                               context=[a.strip() for a in r.get("context", "").split(";") if a.strip()],
                               lookback_days=int(r["lookback_days"]) if r.get("lookback_days", "").isdigit() else None,
                               ticker=r.get("ticker", ""), ambiguous=yes_no(r.get("ambiguous"))))
    return out


def window(store, c, src, lookback, mode, today):
    full = today - dt.timedelta(days=lookback)
    if src == "gdelt":
        full = max(full, today - dt.timedelta(days=GDELT_MAX_DAYS))
    span = store.covered_span(c.company_id, src)
    if mode == "backfill" or span is None or full < span[0] - dt.timedelta(days=1):
        return full
    return max(full, span[1] - dt.timedelta(days=OVERLAP_DAYS))


def process(store, c, sources, lookback_default, mode, today, read=None):
    store.upsert_company(c)
    card = profile.ensure(store, c)                        # company card from its website (rebuilt every 30 days)
    matcher, stats = Matcher(c, card), Counter()
    stats[f"profile:{card['status'].split(':')[0]}"] += 1
    lookback = c.lookback_days or lookback_default
    for src in sources:
        since = window(store, c, src, lookback, mode, today)
        try:
            if src == "newsroom":
                if not c.domain:
                    raise SkipSource("no website given")
                feed_url, checked = store.feed(c.company_id)
                if not checked or dt.datetime.fromisoformat(checked) < dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=FEED_RECHECK_DAYS):
                    feed_url = find_feed(c.domain)
                    store.set_feed(c.company_id, feed_url)
                items = SOURCES[src](c, since, today, feed_url)
            else:
                items = SOURCES[src](c, since, today)
        except SkipSource as e:
            store.add_coverage(c.company_id, src, since, today, "skipped", error=str(e))
            stats[f"{src}:skipped"] += 1
            continue
        except (http.FetchError, Exception) as e:          # one failing source must not stop the others
            store.add_coverage(c.company_id, src, since, today, "error", error=f"{type(e).__name__}: {e}"[:300])
            stats[f"{src}:error"] += 1
            continue
        rows = []
        for a in items:
            d = a["published_at"]
            if d is None or not (since <= d.date() <= today):
                continue
            score = matcher.score(a["title"], a["summary"], a["url"], src)
            category = classify(a["title"], a["summary"])
            if score < POSSIBLE or category is None:           # not about the company, or a profile page rather than news
                continue
            rows.append({"company_id": c.company_id, "dedupe_key": dedupe_key(a["title"], a["publisher"], a["url"]), "source": src,
                         "title": a["title"], "url": a["url"], "publisher": a["publisher"], "published_at": d.isoformat(timespec="seconds"),
                         "summary": (a["summary"] or "")[:1000], "match_score": score, "category": category})
        new = store.add_articles(rows)
        store.add_coverage(c.company_id, src, since, today, "ok", len(items), len(rows))
        stats[f"{src}:ok"] += 1
        stats["new_articles"] += max(new, 0)
    if read:
        stats += read_texts(store, c.company_id, **read)
    return stats


def _reader():
    """article_reader is a separate package, imported only when reading is switched on."""
    try:
        from article_reader import read_article
    except ImportError as e:
        raise SystemExit(f"--read-articles needs the article_reader package next to news_scraper ({e})")
    return read_article


def read_texts(store, company_id, min_match=MATCH, max_per_company=10):
    """Fetch the text of this company's matched articles that have not been read yet (newest first)."""
    read_article, stats = _reader(), Counter()
    for key, url in store.unread(company_id, min_match, max_per_company):
        r = read_article(url)
        store.add_text(company_id, key, r)
        stats[f"read:{r.status}"] += 1
    return stats


def read_stored(db_path, min_match=MATCH, max_per_company=10, workers=6, log=print):
    """`read` command: fetch text for articles already in the store (e.g. after a run without --read-articles)."""
    store, t0, total = Store(db_path), time.time(), Counter()
    ids = [r[0] for r in store.db.execute("SELECT company_id FROM companies ORDER BY name")]
    log(f"Reading article text for {len(ids)} companies · up to {max_per_company} per company · match ≥ {min_match}")
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(read_texts, store, cid, min_match, max_per_company) for cid in ids]):
            total += f.result()
    log(f"Read in {time.time() - t0:,.0f}s · " + " · ".join(f"{k[5:]} {v}" for k, v in sorted(total.items())))
    return total


def build_profiles(companies, db_path, refresh=False, workers=6, log=print):
    """`profile` command: build (or refresh) each company's card and print what was found."""
    store = Store(db_path)
    for c in companies:
        store.upsert_company(c)
    with ThreadPoolExecutor(workers) as ex:
        cards = list(ex.map(lambda c: profile.ensure(store, c, refresh), companies))
    for c, card in zip(companies, cards):
        m = Matcher(c, card)
        log(f"\n{c.name}  [{card['status']}]  name: {'ambiguous' if m.ambiguous else 'distinctive'}")
        for k in ("site_name", "legal_name", "ticker", "city"):
            if card.get(k):
                log(f"  {k:<10} {card[k]}")
        for k in ("alt_names", "people", "keywords"):
            if card.get(k):
                log(f"  {k:<10} {'; '.join(card[k])}")
    return cards


def run(companies, db_path, sources, lookback_days=180, mode="auto", workers=6, read=None, log=print):
    """read: None (default, headlines only) or dict(min_match=..., max_per_company=...) to also fetch article text."""
    store, today, t0, total = Store(db_path), dt.date.today(), time.time(), Counter()
    if read:
        _reader()                                          # fail early if the package is missing
    log(f"Scraping {len(companies)} companies · sources {', '.join(sources)} · lookback {lookback_days} days · mode {mode} · {workers} workers"
        + (f" · reading up to {read['max_per_company']} articles per company" if read else ""))
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(process, store, c, sources, lookback_days, mode, today, read): c for c in companies}
        for i, f in enumerate(as_completed(futs), 1):
            total += f.result()
            if i % 25 == 0 or i == len(companies):
                log(f"  {i}/{len(companies)} companies · {total['new_articles']} new articles · {time.time() - t0:,.0f}s")
    log("Per source (ok / error / skipped): " + " · ".join(f"{s} {total[s + ':ok']}/{total[s + ':error']}/{total[s + ':skipped']}" for s in sources))
    if read:
        log("Article text: " + (" · ".join(f"{k[5:]} {v}" for k, v in sorted(total.items()) if k.startswith("read:")) or "nothing new to read"))
    return total


# ---------------------------------------------------------------- export for the Priority Score
def export(db_path, out_dir, settings_path=None, min_match=MATCH, lookback_days=180):
    """signal_events.csv (every matched article), company_summary.csv (one row per company, in the scoring's
    news_signal / news_signal_date terms) and review.csv (possible matches to check by hand)."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    strength, recency = load_settings(settings_path)
    store, today = Store(db_path), dt.datetime.now(dt.timezone.utc)
    q = store.db.execute
    crow = q("SELECT company_id, name, domain, location, country, aliases, context, ticker, ambiguous FROM companies ORDER BY name").fetchall()
    companies = [(r[0], r[1], r[2]) for r in crow]
    cards = {cid: store.profile(cid) or {} for cid, _, _ in companies}
    matchers = {r[0]: Matcher(Company(name=r[1], company_id=r[0], domain=r[2] or "", location=r[3] or "", country=r[4] or "",
                                      aliases=[a for a in (r[5] or "").split(";") if a], context=[a for a in (r[6] or "").split(";") if a],
                                      ticker=r[7] or "", ambiguous={"yes": True, "no": False}.get(r[8] or "")), cards[r[0]])
                for r in crow}
    texts = {(r[0], r[1]): (r[2], r[3] or "") for r in q("SELECT company_id, dedupe_key, status, text FROM article_texts")}
    arts = q("SELECT company_id, source, title, url, publisher, published_at, match_score, summary, dedupe_key FROM articles").fetchall()
    # latest status per company x source
    cov = {}
    for cid, src, status, checked in q("SELECT company_id, source, status, checked_at FROM source_coverage ORDER BY checked_at"):
        cov[(cid, src)] = (status, checked)

    events, review = [], []
    for cid, src, title, url, pub, published, score, summary_text, key in arts:
        age = (today - dt.datetime.fromisoformat(published)).days
        cat = classify(title, summary_text)          # re-classified on export, so rule changes apply without re-scraping
        if age > lookback_days or cat is None:
            continue
        text_status, text = texts.get((cid, key), ("not read", ""))
        lead = text[:600] if text_status == "ok" else ""
        if lead and cat == OTHER:                    # headline says nothing specific: let the opening paragraphs decide
            cat = classify("", lead) or OTHER
        # does it count? identity evidence from the company card + CSV; stricter when the text could not be read
        ok, check, found = matchers[cid].verdict(title, summary_text, src, text if text_status == "ok" else None)
        if score < min_match:
            ok, check = False, check or f"low match score ({score})"
        row = {"company_id": cid, "published_at": published[:10], "age_days": age, "category": cat, "strength": strength.get(cat, strength.get(OTHER, 0.3)),
               "recency_factor": recency_factor(age, recency), "match_score": score, "title": title, "publisher": pub, "url": url, "source": src,
               "text_status": text_status, "evidence": "; ".join(found), "check": check, "lead": re.sub(r"\s+", " ", lead[:300])}
        row["weighted"] = round(row["strength"] * row["recency_factor"], 3)
        (events if ok else review).append(row)

    by_c = {}
    for e in events:
        by_c.setdefault(e["company_id"], []).append(e)
    summary = []
    for cid, name, domain in companies:
        statuses = {s: st for (c, s), (st, _) in cov.items() if c == cid}
        checked = [st for st in statuses.values() if st == "ok"]
        evs = sorted(by_c.get(cid, []), key=lambda e: (e["weighted"], e["strength"], e["published_at"]), reverse=True)
        best = evs[0] if evs else None
        status = "found" if best else ("checked, nothing found" if checked else "not checked")
        summary.append({
            "company_id": cid, "company_name": name, "website": domain or "", "news_status": status,
            # in the scoring's terms: blank = unknown (baseline), "None" = checked and found nothing (real zero)
            "news_signal": best["category"] if best else ("None" if checked else ""),
            "news_signal_date": best["published_at"] if best else "", "headline": best["title"] if best else "",
            "publisher": best["publisher"] if best else "", "url": best["url"] if best else "",
            "matched_articles": len(evs), "events_not_other": sum(e["category"] != OTHER for e in evs),
            "possible_matches_to_review": sum(r["company_id"] == cid for r in review),
            "name_type": "ambiguous" if matchers[cid].ambiguous else "distinctive",
            "profile_status": cards[cid].get("status", "not built"),
            "profile_keywords": "; ".join(cards[cid].get("keywords", [])[:8]),
            "sources_ok": ";".join(s for s, st in statuses.items() if st == "ok"),
            "sources_error": ";".join(s for s, st in statuses.items() if st == "error"),
            "sources_skipped": ";".join(s for s, st in statuses.items() if st == "skipped"),
            "note": "" if domain else "no website: matched on name and location only",
        })

    def write(name, rows, cols):
        path = os.path.join(out_dir, name)
        try:
            f = open(path, "w", encoding="utf-8-sig", newline="")
        except PermissionError:                  # the file is open (e.g. in Excel): write a timestamped copy instead
            path = os.path.join(out_dir, f"{name[:-4]}_{dt.datetime.now():%Y%m%d_%H%M%S}.csv")
            print(f"  {name} is open in another program, so this export went to {os.path.basename(path)}")
            f = open(path, "w", encoding="utf-8-sig", newline="")
        with f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    ev_cols = ["company_id", "published_at", "age_days", "category", "strength", "recency_factor", "weighted", "match_score", "title", "publisher", "url", "source",
               "text_status", "evidence", "check", "lead"]
    write("signal_events.csv", sorted(events, key=lambda e: (e["company_id"], e["published_at"]), reverse=True), ev_cols)
    write("review.csv", sorted(review, key=lambda e: (e["company_id"], e["published_at"]), reverse=True), ev_cols)
    write("company_summary.csv", summary, list(summary[0].keys()) if summary else ["company_id"])
    return {"companies": len(summary), "events": len(events), "review": len(review), "status": Counter(s["news_status"] for s in summary)}
