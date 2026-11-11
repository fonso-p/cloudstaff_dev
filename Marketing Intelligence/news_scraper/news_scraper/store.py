"""Local SQLite store.

companies        the input list, plus the company's feed URL once found
articles         one row per article per company (deduplicated), with match score and category
source_coverage  one row per company x source x run: the window checked and whether the check worked.
                 This is what separates "checked, found nothing" from "never checked" in the scoring.
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
"""


def dedupe_key(title, publisher, url):
    """Same story from different sources: normalised headline + publisher (Google's links are opaque redirects)."""
    t = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    t = re.sub(r"\s+", " ", t).strip()[:120]
    p = re.sub(r"^www\.", "", (publisher or "").lower().strip())
    return hashlib.sha1(f"{t}|{p}".encode()).hexdigest()[:20] if t else hashlib.sha1((url or "").encode()).hexdigest()[:20]


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(companies)")}
        for col in ("context", "ticker", "ambiguous"):                      # upgrade databases made by earlier versions
            if col not in have:
                self.db.execute(f"ALTER TABLE companies ADD COLUMN {col} TEXT")
        self.lock = threading.Lock()

    def upsert_company(self, c):
        amb = "" if c.ambiguous is None else ("yes" if c.ambiguous else "no")
        with self.lock, self.db:
            self.db.execute("""INSERT INTO companies(company_id,name,domain,location,country,aliases,context,ticker,ambiguous,lookback_days)
              VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(company_id) DO UPDATE SET name=excluded.name, domain=excluded.domain, location=excluded.location,
              country=excluded.country, aliases=excluded.aliases, context=excluded.context, ticker=excluded.ticker,
              ambiguous=excluded.ambiguous, lookback_days=excluded.lookback_days""",
                            (c.company_id, c.name, c.domain, c.location, c.country, ";".join(c.aliases), ";".join(c.context),
                             c.ticker, amb, c.lookback_days))

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
            self.db.execute("INSERT OR REPLACE INTO article_texts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (company_id, dedupe_key, r.final_url, r.status, r.method, r.chars, r.text, r.published, r.author, r.error,
                             dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))

    def add_coverage(self, company_id, source, start, end, status, n_results=0, n_kept=0, error=None):
        with self.lock, self.db:
            self.db.execute("INSERT INTO source_coverage VALUES(?,?,?,?,?,?,?,?,?)",
                            (company_id, source, start.isoformat() if start else None, end.isoformat() if end else None,
                             dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), status, n_results, n_kept, error))
