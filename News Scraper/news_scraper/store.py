"""Local SQLite store.

companies        the input list, plus the company's feed URL once found
articles         one row per article per company (deduplicated), with match score and category
source_coverage  one row per company x source x run: the window checked and whether the check worked.
                 This is what separates "checked, found nothing" from "never checked" in the scoring.
segments         segment mode: one row per industry group x country (segment_id 'seg:<group>:<country>')
segment_articles one row per article per segment. Segment checks go in source_coverage (company_id = segment_id,
                 source = '<source>|<theme>') and article text in article_texts, under the segment_id.
"""
import datetime as dt
import hashlib
import json
import re
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  company_id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT, location TEXT, country TEXT, aliases TEXT, context TEXT,
  lookback_days INTEGER, feed_url TEXT, feed_checked_at TEXT);
CREATE TABLE IF NOT EXISTS articles (
  company_id TEXT NOT NULL, dedupe_key TEXT NOT NULL, source TEXT NOT NULL, title TEXT, url TEXT, publisher TEXT,
  published_at TEXT, summary TEXT, match_score REAL, category TEXT, first_seen_at TEXT,
  PRIMARY KEY (company_id, dedupe_key));
CREATE INDEX IF NOT EXISTS ix_articles_company ON articles(company_id, published_at);
CREATE TABLE IF NOT EXISTS source_coverage (
  company_id TEXT NOT NULL, source TEXT NOT NULL, window_start TEXT, window_end TEXT, checked_at TEXT,
  status TEXT, n_results INTEGER, n_kept INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS ix_cov ON source_coverage(company_id, source, status);
CREATE TABLE IF NOT EXISTS company_profiles (
  company_id TEXT PRIMARY KEY, status TEXT, built_at TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS article_texts (
  company_id TEXT NOT NULL, dedupe_key TEXT NOT NULL, final_url TEXT, status TEXT, method TEXT, chars INTEGER,
  text TEXT, published TEXT, author TEXT, error TEXT, read_at TEXT,
  PRIMARY KEY (company_id, dedupe_key));
CREATE TABLE IF NOT EXISTS segments (
  segment_id TEXT PRIMARY KEY, industry_group TEXT NOT NULL, industry_sector TEXT, country TEXT NOT NULL,
  extra_terms TEXT, exclude_terms TEXT, lookback_days INTEGER);
CREATE TABLE IF NOT EXISTS segment_articles (
  segment_id TEXT NOT NULL, dedupe_key TEXT NOT NULL, source TEXT NOT NULL, query_theme TEXT, title TEXT, url TEXT,
  publisher TEXT, published_at TEXT, summary TEXT, first_seen_at TEXT, publisher_url TEXT, title_key TEXT, direct_url TEXT,
  PRIMARY KEY (segment_id, dedupe_key));
CREATE INDEX IF NOT EXISTS ix_seg_articles ON segment_articles(segment_id, published_at);
"""


def dedupe_key(title, publisher, url):
    """Same story from different sources: normalised headline + publisher (Google's links are opaque redirects)."""
    t = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    t = re.sub(r"\s+", " ", t).strip()[:120]
    p = re.sub(r"^www\.", "", (publisher or "").lower().strip())
    return hashlib.sha1(f"{t}|{p}".encode()).hexdigest()[:20] if t else hashlib.sha1((url or "").encode()).hexdigest()[:20]


def title_key(title):
    """The same story from two sources (Google and the site's own feed) has the same headline but may have a different
    publisher name, so segment articles are also matched on the normalised headline."""
    t = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    return re.sub(r"\s+", " ", t).strip()[:100]


def real_url(*urls):
    """The first URL that is the article itself (a read page's final URL, a feed's link), not a Google/Bing redirect."""
    for u in urls:
        if is_direct(u):
            return u
    return next((u for u in urls if u), "")


def is_direct(url):
    return bool(url) and "news.google." not in url and "bing.com/" not in url


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(companies)")}
        for col in ("context", "ticker", "ambiguous", "employees"):                      # upgrade databases made by earlier versions
            if col not in have:
                self.db.execute(f"ALTER TABLE companies ADD COLUMN {col} TEXT")
        if "meta" not in {r[1] for r in self.db.execute("PRAGMA table_info(article_texts)")}:
            self.db.execute("ALTER TABLE article_texts ADD COLUMN meta TEXT")         # JSON: location metadata from the page
        seg_cols = {r[1] for r in self.db.execute("PRAGMA table_info(segment_articles)")}
        if "publisher_url" not in seg_cols:
            self.db.execute("ALTER TABLE segment_articles ADD COLUMN publisher_url TEXT")
        if "title_key" not in seg_cols:                      # one row per story across sources; direct links from feeds
            with self.db:
                self.db.execute("ALTER TABLE segment_articles ADD COLUMN title_key TEXT")
                self.db.execute("ALTER TABLE segment_articles ADD COLUMN direct_url TEXT")
                self.db.executemany("UPDATE segment_articles SET title_key=? WHERE segment_id=? AND dedupe_key=?",
                                    [(title_key(t), s, k) for s, k, t in self.db.execute("SELECT segment_id, dedupe_key, title FROM segment_articles")])
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_seg_title ON segment_articles(segment_id, title_key)")
        self.lock = threading.Lock()

    def upsert_company(self, c):
        amb = "" if c.ambiguous is None else ("yes" if c.ambiguous else "no")
        with self.lock, self.db:
            self.db.execute("""INSERT INTO companies(company_id,name,domain,location,country,aliases,context,ticker,ambiguous,lookback_days,employees)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(company_id) DO UPDATE SET name=excluded.name, domain=excluded.domain, location=excluded.location,
              country=excluded.country, aliases=excluded.aliases, context=excluded.context, ticker=excluded.ticker,
              ambiguous=excluded.ambiguous, lookback_days=excluded.lookback_days, employees=excluded.employees""",
                            (c.company_id, c.name, c.domain, c.location, c.country, ";".join(c.aliases), ";".join(c.context),
                             c.ticker, amb, c.lookback_days, getattr(c, "employees", None)))

    def profile(self, company_id):
        row = self.db.execute("SELECT data FROM company_profiles WHERE company_id=?", (company_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_profile(self, company_id, card):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO company_profiles VALUES(?,?,?,?)",
                            (company_id, card["status"], card["built_at"], json.dumps(card, ensure_ascii=False)))

    def feed(self, company_id):
        row = self.db.execute("SELECT feed_url, feed_checked_at FROM companies WHERE company_id=?", (company_id,)).fetchone()
        return row or (None, None)

    def set_feed(self, company_id, url):
        with self.lock, self.db:
            self.db.execute("UPDATE companies SET feed_url=?, feed_checked_at=? WHERE company_id=?",
                            (url or "", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), company_id))

    def covered_span(self, company_id, source):
        """(earliest start, latest end) of successful checks, or None if never checked successfully."""
        row = self.db.execute("SELECT MIN(window_start), MAX(window_end) FROM source_coverage WHERE company_id=? AND source=? AND status='ok'",
                              (company_id, source)).fetchone()
        return (dt.date.fromisoformat(row[0]), dt.date.fromisoformat(row[1])) if row and row[0] else None

    def add_articles(self, rows):
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self.lock, self.db:
            cur = self.db.executemany("""INSERT OR IGNORE INTO articles(company_id,dedupe_key,source,title,url,publisher,published_at,summary,
              match_score,category,first_seen_at) VALUES(:company_id,:dedupe_key,:source,:title,:url,:publisher,:published_at,:summary,
              :match_score,:category,'""" + now + "')", rows)
            return cur.rowcount

    def unread(self, company_id, min_match, limit, retry_failed_after_days=7):
        """Matched articles with no text yet (or a failed read older than N days), newest first."""
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=retry_failed_after_days)).isoformat(timespec="seconds")
        return self.db.execute("""SELECT a.dedupe_key, a.url FROM articles a LEFT JOIN article_texts t
              ON t.company_id=a.company_id AND t.dedupe_key=a.dedupe_key
            WHERE a.company_id=? AND a.match_score>=? AND (t.dedupe_key IS NULL OR (t.status NOT IN ('ok','blocked_robots') AND t.read_at < ?))
            ORDER BY a.published_at DESC LIMIT ?""", (company_id, min_match, cutoff, limit)).fetchall()

    def add_text(self, company_id, dedupe_key, r):
        """r: an article_reader.ReadResult (only its attributes are used, so this module does not import article_reader)."""
        with self.lock, self.db:
            self.db.execute("""INSERT OR REPLACE INTO article_texts(company_id,dedupe_key,final_url,status,method,chars,text,published,author,
              error,read_at,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (company_id, dedupe_key, r.final_url, r.status, r.method, r.chars, r.text, r.published, r.author, r.error,
                             dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                             json.dumps(getattr(r, "location", None) or {}, ensure_ascii=False)))

    def add_coverage(self, company_id, source, start, end, status, n_results=0, n_kept=0, error=None):
        with self.lock, self.db:
            self.db.execute("INSERT INTO source_coverage VALUES(?,?,?,?,?,?,?,?,?)",
                            (company_id, source, start.isoformat() if start else None, end.isoformat() if end else None,
                             dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), status, n_results, n_kept, error))

    # ------------------------------------------------------------ segment mode (sector x region)
    def upsert_segment(self, s):
        with self.lock, self.db:
            self.db.execute("""INSERT INTO segments VALUES(?,?,?,?,?,?,?)
              ON CONFLICT(segment_id) DO UPDATE SET industry_group=excluded.industry_group, industry_sector=excluded.industry_sector,
              country=excluded.country, extra_terms=excluded.extra_terms, exclude_terms=excluded.exclude_terms,
              lookback_days=excluded.lookback_days""",
                            (s.segment_id, s.industry_group, s.sector, s.country, ";".join(s.extra_terms), ";".join(s.exclude_terms),
                             s.lookback_days))

    def add_segment_articles(self, rows):
        """Insert new stories; for a story already stored (same key, or same headline from another source) fill in what it
        lacks: a direct link (from a feed or Bing), a summary, the publisher's domain. Returns the number of new stories."""
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        new = 0
        with self.lock, self.db:
            for r in rows:
                tk = title_key(r["title"])
                direct = r["url"] if is_direct(r["url"]) else ""
                hit = self.db.execute("SELECT dedupe_key FROM segment_articles WHERE segment_id=? AND (dedupe_key=? OR (title_key=? AND title_key<>''))",
                                      (r["segment_id"], r["dedupe_key"], tk)).fetchone()
                if hit:
                    self.db.execute("""UPDATE segment_articles SET
                          direct_url = CASE WHEN IFNULL(direct_url,'')='' THEN ? ELSE direct_url END,
                          summary = CASE WHEN IFNULL(summary,'')='' THEN ? ELSE summary END,
                          publisher_url = CASE WHEN IFNULL(publisher_url,'')='' THEN ? ELSE publisher_url END
                        WHERE segment_id=? AND dedupe_key=?""", (direct, r["summary"] or "", r["publisher_url"] or "", r["segment_id"], hit[0]))
                    continue
                self.db.execute("""INSERT INTO segment_articles(segment_id,dedupe_key,source,query_theme,title,url,publisher,published_at,summary,
                      publisher_url,first_seen_at,title_key,direct_url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (r["segment_id"], r["dedupe_key"], r["source"], r["query_theme"], r["title"], r["url"], r["publisher"],
                                 r["published_at"], r["summary"], r["publisher_url"], now, tk, direct))
                new += 1
        return new

    def unread_segment(self, segment_id, limit=-1, retry_failed_after_days=7):
        """Segment articles with no text yet (or a failed read older than N days), newest first: (key, url), preferring the
        direct link (no Google decoding). limit -1 = all."""
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=retry_failed_after_days)).isoformat(timespec="seconds")
        return self.db.execute("""SELECT a.dedupe_key, COALESCE(NULLIF(a.direct_url,''), a.url) FROM segment_articles a LEFT JOIN article_texts t
              ON t.company_id=a.segment_id AND t.dedupe_key=a.dedupe_key
            WHERE a.segment_id=? AND (t.dedupe_key IS NULL OR (t.status NOT IN ('ok','blocked_robots') AND t.read_at < ?)
                                      OR (t.status='ok' AND t.meta IS NULL))          -- read before location metadata was kept
            ORDER BY a.published_at DESC LIMIT ?""", (segment_id, cutoff, limit)).fetchall()
