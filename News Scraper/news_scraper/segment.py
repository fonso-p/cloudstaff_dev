"""Segment mode: news about an industry sector in a region (e.g. Healthcare & Wellness x AU), not about one company.

Three uses, one scrape:
  1. Market trend digest     segment_summary.csv: per sector x country, what is happening (themes, volume, momentum,
                             top headlines), for campaigns, content and sales talking points.
  2. Priority Score tailwind industry_trend.csv: a 0-1 trend per industry group x country (and per group overall), in the
                             Priority Score's `industry_trend` terms (modifier = 0.9 + 0.2 x trend; 0.5 = neutral).
  3. Prospect discovery      segment_companies.csv: companies named in the sector news, marked as existing account or new.
                             The file can be fed straight into company mode: run --companies out/segment_companies.csv

How it searches: one query per segment x theme x source, e.g. for Healthcare x AU x Labour shortage
    ("aged care" OR hospitals OR ...) ("skills shortage" OR "staff shortage" OR ...) (Australia OR Sydney OR ...)
on that country's Google News edition. The search engine looks at the whole article, so all three must appear somewhere
in it. At export each article is checked again on what we can see (headline, and the text if read): it counts when the
sector is named there and the headline is not about another country. Themes are re-classified on export, so rule
changes in sectors.py apply without scraping again.
"""
import csv
import datetime as dt
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import http
from .classify import PROFILE, load_settings, recency_factor
from .match import ENGLISH, core_name
from .pipeline import OVERLAP_DAYS, _reader, write_csv
from .relevance import INDUSTRY_MIN, REGION_MIN, IndustryScorer, RegionScorer, meta_of
from .sectors import (COUNTRIES, GROUPS, MAX_QUERY_WORDS, OTHER_THEME, SECTOR_TERMS, THEME_WEIGHT, THEMES, classify_theme,
                      country_code, or_group, sector_of, term_regex, trade_press_group)
from .sources import GDELT_MAX_DAYS, bing_search, gdelt_search, google_search, parse_feed
from .store import Store, dedupe_key, is_direct, real_url

SEGMENT_SOURCES = ["google", "bing", "gdelt", "curated"]   # bing: opt-in; it returns almost nothing for grouped OR queries
# job adverts and listings pages (e.g. ACCA Careers): not news, dropped like company-profile pages
JOB_AD = re.compile(r"\bjobs? with\b|^jobs? (in|at|for)\b|\bvacanc(y|ies) (at|in)\b|\bcareers? (at|with)\b|^[^|]{0,60} - [^|]{0,40}, "
                    r"(united kingdom|australia|new zealand|united states|canada|ireland|singapore)\b", re.I)
# pages that are not news stories, found by spot checks: listings ("Cafe & Coffee Shop - Pomona QLD 4568 - 2021062129"),
# numbered list items ("2. Kismet"), one- or two-word page titles ("Incidents", "SQM Research"), events and forms,
# stock-tip listicles ("Top 3 British AI Healthcare Stocks To Watch")
NOT_NEWS = re.compile(r"\b\d{4} - \d{7,}\b|^\s*\d{1,2}\.\s+\S+(\s+\S+){0,3}\s*$|^\s*\S+(\s+\S+)?\s*$|"
                      r"\b(open (evening|day)|information session|info session|webinar|^register now|resources for practitioners|"
                      r"application form|number application|prospective candidate|free resources|fact ?sheet)\b|^register for\b|"
                      r"^summary - |\((in person|online|virtual)\)|\b(accountancy|accounting|law) (group|firm) profile$|"
                      r"\bproperty for (sale|lease)\b|\bfor (sale|lease) in\b|^news\s*-\s*\S+(\s+\S+)?\s*$|\bconference summary\b|"
                      r"\|\s*\$\d|\$\d+\s*/\s*h(ou)?r\b|\bper hour\b|"
                      r"\bstocks? to (watch|buy)\b|\b(growth|dividend|penny|asx|ftse|insider[- ]backed) (stocks|shares)\b|"
                      r"\bdeserves your next\b|\bshares? to buy\b", re.I)
SOCIAL = {"instagram", "facebook", "linkedin", "tiktok", "youtube", "x", "x.com", "twitter", "threads", "reddit", "pinterest"}
SOURCES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "segment_sources.csv")
SHRINK = 10          # articles at which the trend is half-way from neutral to its full tailwind (few articles stay near 0.5)
NEUTRAL = 0.5        # industry_trend when a segment was checked but nothing counted: modifier 1.0, same as unknown


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


@dataclass
class Segment:
    industry_group: str
    country: str
    extra_terms: list = field(default_factory=list)      # more sector words for this segment, e.g. NHS for Healthcare x UK
    exclude_terms: list = field(default_factory=list)    # words that must not appear (search operator -word)
    lookback_days: int | None = None

    def __post_init__(self):
        self.country = country_code(self.country)
        if self.industry_group not in SECTOR_TERMS:
            raise ValueError(f"unknown industry group {self.industry_group!r}; choose from: {'; '.join(GROUPS)}")
        if self.country not in COUNTRIES:
            raise ValueError(f"unknown country {self.country!r}; choose from: {', '.join(COUNTRIES)}")

    @property
    def segment_id(self):
        return f"seg:{_slug(self.industry_group)}:{self.country}"

    @property
    def sector(self):
        return sector_of(self.industry_group)

    @property
    def terms(self):
        return list(dict.fromkeys(SECTOR_TERMS[self.industry_group] + self.extra_terms))

    def queries(self, theme_terms, region=True):
        """The search for one theme, split into as many queries as needed to keep each under MAX_QUERY_WORDS
        (Google ignores the rest of a long query): '(sector terms) (theme terms) (region terms) -excluded'."""
        tail = f" {or_group(theme_terms)}" + (f" {or_group(COUNTRIES[self.country]['query'])}" if region else "")
        tail += "".join(f" -{or_group([t])}" for t in self.exclude_terms)
        budget = MAX_QUERY_WORDS - 2 - len(tail.split())                 # 2 = the after:/before: dates
        chunks, cur = [], []
        for t in self.terms:
            if cur and len(or_group(cur + [t]).split()) > budget:
                chunks.append(cur)
                cur = []
            cur.append(t)
        chunks.append(cur)
        return [or_group(c) + tail for c in chunks]

    def site_queries(self, source):
        """Google News queries for one curated site. A site for every industry gets the sector words; a site for several
        countries gets the region words; a site that is specific on both gets just 'site:domain'."""
        tail = "" if source["countries"] != "all" and len(source["countries"]) == 1 else " " + or_group(COUNTRIES[self.country]["query"])
        head = f"site:{source['site']}"
        if source["industry_group"] != "all":
            return [head + tail]
        budget = MAX_QUERY_WORDS - 2 - len((head + tail).split())
        chunks, cur = [], []
        for t in self.terms:
            if cur and len(or_group(cur + [t]).split()) > budget:
                chunks.append(cur)
                cur = []
            cur.append(t)
        chunks.append(cur)
        return [f"{head} {or_group(c)}{tail}" for c in chunks]


def _split(v):
    return [x.strip() for x in (v or "").split(";") if x.strip()]


def read_segments(path):
    """CSV: industry_group, country (both required); optional extra_terms, exclude_terms (';'-separated), lookback_days.
    industry_group 'all' expands to the 18 groups; country can list several, e.g. 'AU;NZ'."""
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("industry_group") or not r.get("country"):
                continue
            groups = GROUPS if r["industry_group"].lower() == "all" else [r["industry_group"]]
            for g in groups:
                for c in _split(r["country"].replace(",", ";")):
                    out.append(Segment(g, c, _split(r.get("extra_terms")), _split(r.get("exclude_terms")),
                                       int(r["lookback_days"]) if r.get("lookback_days", "").isdigit() else None))
    return out


def load_sources(path=SOURCES_FILE):
    """segment_sources.csv: websites that report on an industry in a region (trade press, industry bodies, regulators,
    statistics agencies, research). Columns: industry_group (a group or 'all'), country (codes separated by ';', or 'all'),
    name, site (domain), type, feed_url (optional RSS/Atom feed), notes."""
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("site"):
                continue
            g = r.get("industry_group") or "all"
            if g != "all" and g not in SECTOR_TERMS:
                raise ValueError(f"{os.path.basename(path)}: unknown industry group {g!r} for {r['site']}")
            countries = "all" if (r.get("country") or "all").lower() == "all" else [country_code(c) for c in _split(r["country"].replace(",", ";"))]
            out.append({"industry_group": g, "countries": countries, "name": r.get("name") or r["site"],
                        "site": re.sub(r"^https?://(www\.)?", "", r["site"].lower()).strip("/"), "type": r.get("type", ""),
                        "feed_url": r.get("feed_url", "")})
    return out


def sources_for(seg, sources):
    """The curated sources that cover a segment: same group (or 'all') and same country (or 'all')."""
    return [s for s in sources if s["industry_group"] in (seg.industry_group, "all")
            and (s["countries"] == "all" or seg.country in s["countries"])]


def curated_match(seg, sources, *urls):
    """The curated source an article comes from (by the publisher's domain), or None."""
    hosts = [re.sub(r"^https?://", "", (u or "").lower()).split("/")[0] for u in urls if u]
    for s in sources_for(seg, sources):
        if any(h == s["site"] or h.endswith("." + s["site"]) for h in hosts if h):
            return s
    return None


def make_segments(groups, countries):
    """--groups 'all' or 'Accounting;Legal' x --countries 'AU,NZ'."""
    gs = GROUPS if groups.strip().lower() == "all" else _split(groups)
    return [Segment(g, c) for g in gs for c in re.split(r"[,;]", countries) if c.strip()]


# ---------------------------------------------------------------- scrape
def _fetch(src, seg, query, since, until):
    if src == "google":
        return google_search(query, seg.country, since, until)
    if src == "bing":
        return bing_search(query, market=seg.country)
    if src == "gdelt":       # GDELT filters by the publisher's country itself, so the region words are left out of its query
        return gdelt_search(query, since, until, filters=f"sourcelang:english sourcecountry:{COUNTRIES[seg.country]['gdelt']}")
    raise ValueError(src)


def _window(store, seg, key, lookback, mode, today, src):
    full = today - dt.timedelta(days=lookback)
    if src == "gdelt":
        full = max(full, today - dt.timedelta(days=GDELT_MAX_DAYS))
    span = store.covered_span(seg.segment_id, key)
    if mode == "backfill" or span is None or full < span[0] - dt.timedelta(days=1):
        return full
    return max(full, span[1] - dt.timedelta(days=OVERLAP_DAYS))


def _store_items(store, seg, items, src, since, today, key, query_theme="", publisher_url=""):
    rows = []
    for a in items:
        d = a["published_at"]
        if d is None or not (since <= d.date() <= today) or PROFILE.search(a["title"] or "") or JOB_AD.search(a["title"] or ""):
            continue
        rows.append({"segment_id": seg.segment_id, "dedupe_key": dedupe_key(a["title"], a["publisher"], a["url"]), "source": src,
                     "query_theme": query_theme, "title": a["title"], "url": a["url"], "publisher": a["publisher"],
                     "published_at": d.isoformat(timespec="seconds"), "summary": (a["summary"] or "")[:1000],
                     "publisher_url": a.get("publisher_url") or publisher_url or (a["url"] if src != "google" else "")})
    new = store.add_segment_articles(rows)
    store.add_coverage(seg.segment_id, key, since, today, "ok", len(items), len(rows))
    return new


def process_curated(store, seg, curated, lookback, mode, today):
    """One site: query per curated source (plus its feed, if given)."""
    stats = Counter()
    for s in sources_for(seg, curated):
        jobs = [(f"curated|{s['site']}|{i}", "site", q) for i, q in enumerate(seg.site_queries(s), 1)]
        if s["feed_url"]:
            jobs.append((f"curated|{s['site']}|feed", "feed", s["feed_url"]))
        for key, kind, q in jobs:
            since = _window(store, seg, key, lookback, mode, today, "google")
            try:
                if kind == "site":
                    items = google_search(q, seg.country, since, today)
                else:
                    items = parse_feed(http.get(q, interval=1.0).content)
                    for i in items:
                        i["publisher"] = i["publisher"] or s["name"]
            except (http.FetchError, Exception) as e:
                store.add_coverage(seg.segment_id, key, since, today, "error", error=f"{type(e).__name__}: {e}"[:300])
                stats["curated:error"] += 1
                continue
            stats["new_articles"] += max(_store_items(store, seg, items, f"site:{s['site']}", since, today, key,
                                                      publisher_url=f"https://{s['site']}"), 0)
            stats["curated:ok"] += 1
    return stats


def process_segment(store, seg, sources, themes, lookback_default, mode, today, read=None, curated=None):
    store.upsert_segment(seg)
    stats, lookback = Counter(), seg.lookback_days or lookback_default
    if "curated" in sources and curated:
        stats += process_curated(store, seg, curated, lookback, mode, today)
    for name, _, theme_terms, _ in THEMES:
        if name not in themes:
            continue
        for src in sources:
          if src == "curated":
              continue
          for i, query in enumerate(seg.queries(theme_terms, region=src != "gdelt"), 1):
            key = f"{src}|{name}|{i}"
            since = _window(store, seg, key, lookback, mode, today, src)
            try:
                items = _fetch(src, seg, query, since, today)
            except (http.FetchError, Exception) as e:          # one failing query must not stop the others
                store.add_coverage(seg.segment_id, key, since, today, "error", error=f"{type(e).__name__}: {e}"[:300])
                stats[f"{src}:error"] += 1
                continue
            new = _store_items(store, seg, items, src, since, today, key, query_theme=name)
            stats[f"{src}:ok"] += 1
            stats["new_articles"] += max(new, 0)
    if read:
        read_article = _reader()
        for k, url in store.unread_segment(seg.segment_id, read["max_per_segment"]):
            r = read_article(url)
            store.add_text(seg.segment_id, k, r)
            stats[f"read:{r.status}"] += 1
    return stats


def run_segments(segments, db_path, sources, themes=None, lookback_days=90, mode="auto", workers=6, read=None, log=print,
                 sources_file=SOURCES_FILE):
    """read: None, or dict(max_per_segment=N) to also fetch the text of the newest N unread articles per segment."""
    store, today, t0, total = Store(db_path), dt.date.today(), time.time(), Counter()
    themes = themes or [t[0] for t in THEMES]
    curated = load_sources(sources_file) if "curated" in sources else []
    if read:
        _reader()
    log(f"Scraping {len(segments)} segments x {len(themes)} themes · sources {', '.join(sources)} · lookback {lookback_days} days · "
        f"mode {mode} · {workers} workers" + (f" · reading up to {read['max_per_segment']} articles per segment" if read else ""))
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(process_segment, store, s, sources, themes, lookback_days, mode, today, read, curated) for s in segments]
        for i, f in enumerate(as_completed(futs), 1):
            total += f.result()
            if i % 10 == 0 or i == len(segments):
                log(f"  {i}/{len(segments)} segments · {total['new_articles']} new articles · {time.time() - t0:,.0f}s")
    log("Queries per source (ok / error): " + " · ".join(f"{s} {total[s + ':ok']}/{total[s + ':error']}" for s in sources))
    if read:
        log("Article text: " + (" · ".join(f"{k[5:]} {v}" for k, v in sorted(total.items()) if k.startswith("read:")) or "nothing new to read"))
    return total


READ_TARGETS = ["newest", "curated", "uncertain"]


def _uncertain(r, counted):
    """Worth reading: counted but no visible theme, or a near miss on industry or region (text can tip it either way)."""
    if counted:
        return r["theme"] == OTHER_THEME
    i, g = r["_industry"], r["_region"]
    return (1 <= i < INDUSTRY_MIN and g >= REGION_MIN - 1) or (i >= INDUSTRY_MIN and REGION_MIN - 2 <= g < REGION_MIN)


def read_segment_texts(db_path, max_per_segment=20, workers=6, log=print, target="newest", settings_path=None, sources_file=SOURCES_FILE):
    """`segment read`: fetch the text of segment articles already scraped, newest first, up to N per segment (0 = all).
    target: newest   - any unread article
            curated  - articles from curated sources (counted or not)
            uncertain- counted articles with no visible theme, and near misses in review
    Direct links (from a site's feed or Bing) are read without decoding Google's link."""
    store, t0, total = Store(db_path), time.time(), Counter()
    read_article = _reader()
    ids = [r[0] for r in store.db.execute("SELECT segment_id FROM segments ORDER BY segment_id")]
    wanted = None
    if target != "newest":
        events, review, _ = score_articles(db_path, settings_path, sources_file=sources_file)
        pick = (lambda r, c: bool(r["curated_source"])) if target == "curated" else _uncertain
        wanted = defaultdict(set)
        for rows, counted in ((events, True), (review, False)):
            for r in rows:
                if r["text_status"] != "ok" and pick(r, counted):
                    wanted[r["segment_id"]].add(r["_key"])
        log(f"{target}: {sum(map(len, wanted.values()))} articles to read")
    cap = max_per_segment if max_per_segment > 0 else 10 ** 9
    log(f"Reading article text for {len(ids)} segments · target {target} · " + (f"up to {cap} per segment" if max_per_segment > 0 else "all"))

    def one(sid):
        st, n = Counter(), 0
        for k, url in store.unread_segment(sid):
            if wanted is not None and k not in wanted.get(sid, ()):
                continue
            if n >= cap:
                break
            n += 1
            r = read_article(url)
            try:
                store.add_text(sid, k, r)
                st[r.status] += 1
                st["direct" if "news.google." not in url else "via google"] += 1
            except Exception as e:                      # one odd page must not stop the batch
                st["not saved"] += 1
                log(f"  could not save {url[:80]}: {e}")
        return st
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(one, sid) for sid in ids]
        for i, f in enumerate(as_completed(futs), 1):
            total += f.result()
            log(f"  {i}/{len(ids)} segments done · {time.time() - t0:,.0f}s · " + " · ".join(f"{k} {v}" for k, v in sorted(total.items())))
    log(f"Read in {time.time() - t0:,.0f}s · " + " · ".join(f"{k} {v}" for k, v in sorted(total.items())))
    return total


# ---------------------------------------------------------------- companies named in the news (prospect discovery)
_NAME = r"[A-Z][\w&'’.+-]*"
_JOIN = r"(?:&|and|of|for|de)"
_VERBS = (r"(?i:raises?|raised|acquires?|acquired|buys|bought|appoints?|names|hires?|taps|expands?|opens?|launch(?:es|ed)?|cuts?|axes|axed|"
          r"slash(?:es|ed)|sheds?|lays off|laid off|to (?:cut|acquire|buy|open|close|axe|shed|expand|hire|launch|offshore|outsource|merge|sell|"
          r"exit|enter|create|list|float|slash)|enters?|secures?|signs?|partners with|wins?|won|collapses?|collapsed|closes?|shuts?|posts?|reports?|"
          r"reveals?|unveils?|announces?|merges?|sells?|sold|offshores?|outsources?|moves?|invests?|backs?|plans?|bets?|eyes|targets?|adds?|"
          r"grows?|doubles?|triples?|restructures?|overhauls?|warns?|flags?|agrees?|completes?|snaps up|swoops|goes into|enters|calls in|"
          r"appoints|hits|tips|books|lifts|boosts|slumps|plunges|soars|jumps)")
_SUBJECT = re.compile(rf"^((?:{_NAME})(?:\s+(?:{_NAME}|{_JOIN})){{0,5}}?)(?:'s|’s)?\s+{_VERBS}\b")
_POSSESSIVE = re.compile(rf"^((?:{_NAME})(?:\s+(?:{_NAME}|{_JOIN})){{0,4}}?)(?:'s|’s)\s")
_EXEC_OF = re.compile(rf"^((?:{_NAME})(?:\s+(?:{_NAME}|{_JOIN})){{0,3}}?)(?:'s|’s)?\s+(?:CEO|CFO|COO|boss|founder|co-founder|"
                      rf"chief executive|chair|chairman|MD|managing director)\b")      # "Canva CEO Melanie Perkins says" -> Canva
_OBJECT = re.compile(rf"\b(?:acquired by|acquisition of|acquisition by|takeover of|bought by|buys|acquires|merger with|merges with|partners with|"
                     rf"partnership with|stake in|deal with|sale of)\s+((?:{_NAME})(?:\s+(?:{_NAME}|{_JOIN})){{0,4}})")
_LEADIN = re.compile(r"^(?:[A-Z][\w ]{0,20}:\s+|[‘'\"“])")              # "Exclusive: ", "WATCH: ", opening quote
_ROLE = re.compile(r"\b(ceo|cfo|coo|cto|boss|founder|co-founder|chief|chair|chairman|chairwoman|md|director|executive|head|owner|spokesperson)\b", re.I)
_DESCRIPTOR = {"provider", "providers", "giant", "firm", "company", "operator", "retailer", "chain", "startup", "start-up", "lender",
               "insurer", "builder", "developer", "miner", "manufacturer", "maker", "agency", "brand", "platform", "listed", "backed",
               "based", "owned", "major", "rival", "unicorn", "fintech", "insurtech", "proptech", "edtech", "healthtech", "operator",
               "player", "group's", "outfit", "titan", "darling", "heavyweight", "behemoth", "juggernaut"}
_STOP = {"how", "why", "what", "when", "where", "who", "which", "this", "these", "those", "here", "there", "it", "its", "new", "top", "best",
         "more", "most", "all", "every", "inside", "report", "reports", "study", "survey", "exclusive", "breaking", "watch", "opinion",
         "analysis", "explainer", "podcast", "video", "update", "live", "news", "government", "govt", "labor", "labour", "coalition",
         "greens", "liberals", "tories", "treasury", "treasurer", "minister", "pm", "premier", "federal", "state", "council", "union",
         "unions", "workers", "businesses", "business", "industry", "sector", "firms", "companies", "banks", "retailers", "experts",
         "economists", "data", "research", "a", "an", "the", "i", "we", "you", "they", "he", "she", "our", "my", "your", "if", "as", "after",
         "amid", "despite", "will", "can", "could", "should", "would", "is", "are", "abs", "eu", "imf", "oecd", "actu", "ai", "fair work",
         "reserve bank", "bank of england", "federal reserve", "fed", "trump", "albanese", "starmer", "carney", "luxon", "white house",
         "parliament", "senate", "congress", "court", "high court", "supreme court", "police", "ombudsman", "commission", "regulator",
         "watchdog", "budget", "election", "mayor", "mp", "senator", "tariffs", "tariff", "jobs", "staff", "employers", "employees",
         "consumers", "shoppers", "customers", "investors", "patients", "students", "doctors", "nurses", "teachers", "accountants",
         "lawyers", "builders", "growth", "inflation", "wages", "costs", "prices", "demand", "sales", "profits", "revenue", "monday",
         "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december", "christmas", "covid", "chatgpt", "openai", "gaza",
         "ukraine", "israel", "china", "india", "japan", "europe", "economist", "migration", "immigration", "nhs", "mps", "ceos"}
_PLACE_WORDS = {p.lower() for c in COUNTRIES.values() for p in c["places"] + [c["name"]]}
_SECTOR_WORDS = term_regex([t for terms in SECTOR_TERMS.values() for t in terms] + [w for terms in SECTOR_TERMS.values() for t in terms for w in t.split()])


def _clean_candidate(name):
    toks = name.replace("’", "'").split()
    # "Australia's Regis Healthcare", "Sydney-based Canva", "ASX-listed Tyro" -> drop the place / descriptor prefix
    toks = [t for t in toks if not re.fullmatch(r"[\w.-]+-(based|listed|owned|backed|headquartered)|[\w.]+'s", t, re.I)
            or t is toks[-1]]
    if any(_ROLE.fullmatch(t) for t in toks):                       # "Canva CEO Melanie Perkins" -> Canva
        toks = toks[: next(i for i, t in enumerate(toks) if _ROLE.fullmatch(t))]
    for i in range(len(toks) - 1, -1, -1):                          # "Aged Care Provider Bolton Clarke" -> Bolton Clarke
        if toks[i].lower() in _DESCRIPTOR:
            toks = toks[i + 1:]
            break
    while toks and toks[-1].lower() in {"&", "and", "of", "for", "de"}:
        toks = toks[:-1]
    while toks and toks[0].lower() in {"the", "&", "and", "of", "for"}:
        toks = toks[1:]
    n = " ".join(toks).strip(" '.-")
    n = re.sub(r"'s$", "", n)
    low = n.lower()
    if (len(n) < 3 or len(toks) > 5 or low in _STOP or low in _PLACE_WORDS or toks[0].lower() in _STOP
            or all(t.lower() in _PLACE_WORDS | _STOP for t in toks) or re.fullmatch(r"[\d\W]+", n) or _SECTOR_WORDS.fullmatch(n)):
        return None
    return n


def extract_companies(title):
    """Organisation names a headline is about, by headline shape (no NLP model): the subject before a business verb
    ("Healius cuts 200 jobs"), a possessive at the start ("Canva's layoffs"), or the object of a deal ("acquisition of
    Tyro"). Candidates, not facts: people and places can slip through; the mention count helps sort them."""
    t = _LEADIN.sub("", (title or "").strip())
    words = [w for w in re.findall(r"[A-Za-z][\w'’-]*", t) if len(w) > 3]
    title_case = len(words) >= 4 and sum(w[0].isupper() for w in words) / len(words) >= 0.7   # "Single Women Reshape Australia's ..."
    found = []
    for rx in (_EXEC_OF, _SUBJECT, _POSSESSIVE):
        m = rx.match(t)
        if m:
            found.append(m.group(1))
            break
    found += [m.group(1) for m in _OBJECT.finditer(t)]
    out = []
    for f in found:
        n = _clean_candidate(f)
        if n and title_case and len(n.split()) > 3:      # in Title Case every word is capitalised, so long runs are unreliable
            continue
        if n and n.lower() not in {o.lower() for o in out}:
            out.append(n)
    return out


def _norm(name):
    return re.sub(r"^the ", "", core_name(name).lower()).strip()


def load_known_accounts(path):
    """{normalised name: account_id} from an accounts CSV with company_name (and account_id / company_id)."""
    known = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("company_name"):
                    known[_norm(r["company_name"])] = r.get("account_id") or r.get("company_id") or "yes"
    return known


# ---------------------------------------------------------------- export
def score_articles(db_path, settings_path=None, lookback_days=90, sources_file=SOURCES_FILE):
    """Score every stored segment article (industry, region, theme). Returns (events, review, context)."""
    _, recency = load_settings(settings_path)
    store, now = Store(db_path), dt.datetime.now(dt.timezone.utc)
    q = store.db.execute
    segs = {r[0]: Segment(r[1], r[3], _split(r[4]), _split(r[5]), r[6])
            for r in q("SELECT segment_id, industry_group, industry_sector, country, extra_terms, exclude_terms, lookback_days FROM segments")}
    texts = {(r[0], r[1]): (r[2], r[3] or "", r[4] or "", meta_of(r[5]))
             for r in q("SELECT company_id, dedupe_key, status, text, final_url, meta FROM article_texts WHERE company_id LIKE 'seg:%'")}
    cov = defaultdict(dict)                                       # segment -> source|theme|n -> latest status
    for sid, key, status in q("SELECT company_id, source, status FROM source_coverage WHERE company_id LIKE 'seg:%' ORDER BY checked_at"):
        cov[sid][key] = status
    rows = q("SELECT segment_id, dedupe_key, source, query_theme, title, url, publisher, published_at, summary, publisher_url, direct_url "
             "FROM segment_articles").fetchall()

    region, industry = RegionScorer(), IndustryScorer()
    curated_all = load_sources(sources_file)
    seen = {}
    for sid, key, _, _, title, _, pub, _, _, _, _ in rows:          # learn publisher homes from all articles (each story once)
        st, text, _, meta = texts.get((sid, key), ("", "", "", {}))
        seen[key] = (pub, title, text if st == "ok" else "", meta)
    region.learn(seen.values())

    events, review, pubs = [], [], defaultdict(Counter)
    for sid, key, src, qtheme, title, url, pub, published, summary, pub_url, direct in rows:
        seg = segs.get(sid)
        if seg is None:
            continue
        age = (now - dt.datetime.fromisoformat(published)).days
        if (age > (seg.lookback_days or lookback_days) or JOB_AD.search(title or "") or PROFILE.search(title or "")
                or NOT_NEWS.search(title or "") or (pub or "").strip().lower() in SOCIAL):
            continue
        status, text, final_url, meta = texts.get((sid, key), ("not read", "", "", {}))
        text = text if status == "ok" else ""
        head = f"{title}. {summary or ''}"
        cur = curated_match(seg, curated_all, pub_url, final_url, url)
        cur_group = cur["industry_group"] if cur and cur["industry_group"] != "all" else None
        cur_country = cur["countries"][0] if cur and cur["countries"] != "all" and len(cur["countries"]) == 1 else None
        i_score, i_ev = industry.score(seg.industry_group, title, summary, text, pub, seg.extra_terms,
                                       curated=cur["name"] if cur_group == seg.industry_group else None)
        r_score, r_ev, home = region.score(seg.country, title, summary, text, pub, pub_url, final_url, meta,
                                           curated=(cur["name"], cur_country) if cur_country else None)
        pubs[pub][home or "?"] += 1
        # what is happening?
        theme, theme_basis = classify_theme(head), "headline"
        if theme is None and text:
            theme, theme_basis = classify_theme(text[:1500], min_hits=2), "text"
        if theme is None:            # the search matched the theme words somewhere on the page, but we can't see them: no credit
            theme, theme_basis = OTHER_THEME, "not seen"
        rec = recency_factor(age, recency)
        weight = THEME_WEIGHT.get(theme, 0.0)
        companies = extract_companies(title)
        words = re.findall(r"[a-z]+", text.lower())
        checks = []
        if i_score < INDUSTRY_MIN:
            checks.append(f"industry {i_score}/{INDUSTRY_MIN}" + ("" if text else " (text not read)"))
        if r_score < REGION_MIN:
            checks.append(f"region {r_score}/{REGION_MIN}" + ("" if text else " (text not read)"))
        if len(words) >= 60 and sum(w in ENGLISH for w in words) / len(words) < 0.08:
            checks.append("article not in English")
        row = {"segment_id": sid, "industry_group": seg.industry_group, "country": seg.country, "published_at": published[:10],
               "age_days": age, "theme": theme, "theme_basis": theme_basis, "theme_weight": THEME_WEIGHT.get(theme, 0.0),
               "recency_factor": rec, "weighted": round(weight * rec, 3),
               "industry_score": i_score, "industry_evidence": "; ".join(i_ev), "region_score": r_score, "region_evidence": "; ".join(r_ev),
               "title": title, "publisher": pub, "publisher_country": home or "", "url": real_url(final_url, direct, url), "google_url": url if not is_direct(url) else "", "source": src, "query_theme": qtheme,
               "curated_source": cur["name"] if cur else "", "companies": "; ".join(companies), "text_status": status, "check": "; ".join(checks),
               "lead": re.sub(r"\s+", " ", text[:300]), "_key": key, "_companies": companies,
               "_industry": i_score, "_region": r_score}
        (review if checks else events).append(row)
    return events, review, {"store": store, "segs": segs, "cov": cov, "region": region, "pubs": pubs, "now": now}


def export_segments(db_path, out_dir, settings_path=None, lookback_days=90, accounts_path=None, sources_file=SOURCES_FILE):
    """segment_summary.csv, segment_events.csv, segment_review.csv, industry_trend.csv, segment_companies.csv, publishers.csv."""
    os.makedirs(out_dir, exist_ok=True)
    events, review, ctx = score_articles(db_path, settings_path, lookback_days, sources_file)
    store, segs, cov, region, pubs = ctx["store"], ctx["segs"], ctx["cov"], ctx["region"], ctx["pubs"]
    q = store.db.execute
    known = load_known_accounts(accounts_path)
    tracked = {_norm(r[0]) for r in q("SELECT name FROM companies")}

    # ---- one row per segment: the digest and the tailwind
    by_seg = defaultdict(list)
    for e in events:
        by_seg[e["segment_id"]].append(e)

    def trend(evs):
        """tailwind_index: recency-weighted average theme weight of the articles whose theme we can see (-1..1).
        industry_trend: 0.5 + 0.5 x tailwind, pulled towards 0.5 when there are few such articles (n / (n + SHRINK))."""
        themed = [e for e in evs if e["theme"] != OTHER_THEME and e["recency_factor"] > 0]
        if not themed:
            return None, None
        tail = sum(e["weighted"] for e in themed) / sum(e["recency_factor"] for e in themed)
        n = len(themed)
        return round(tail, 3), round(min(1.0, max(0.0, NEUTRAL + NEUTRAL * tail * n / (n + SHRINK))), 3)

    summary, trend_rows = [], []
    for sid, seg in sorted(segs.items(), key=lambda x: (x[1].industry_group, x[1].country)):
        evs = sorted(by_seg.get(sid, []), key=lambda e: (e["weighted"], e["published_at"]), reverse=True)
        st = cov.get(sid, {})
        ok, err = sum(v == "ok" for v in st.values()), sum(v == "error" for v in st.values())
        status = "found" if evs else ("checked, nothing found" if ok else "not checked")
        tail, tr = trend(evs)
        if tr is None and ok:
            tr, tail = NEUTRAL, 0.0
        n30 = sum(e["age_days"] <= 30 for e in evs)
        n_prior = sum(30 < e["age_days"] <= 90 for e in evs)
        momentum = round(n30 / max(n_prior / 2, 1), 2) if evs else ""
        themes = Counter(e["theme"] for e in evs)
        named = Counter(c for e in evs for c in e["_companies"])
        top = [e for e in evs if e["theme"] != OTHER_THEME][:3] or evs[:3]
        row = {"segment_id": sid, "industry_group": seg.industry_group, "industry_sector": seg.sector, "country": seg.country,
               "news_status": status, "industry_trend": "" if tr is None else tr, "tailwind_index": "" if tail is None else tail,
               "articles": len(evs), "articles_30d": n30, "articles_31_90d": n_prior, "momentum": momentum,
               "top_theme": next((t for t, _ in themes.most_common() if t != OTHER_THEME), themes.most_common(1)[0][0] if themes else ""),
               "theme_mix": "; ".join(f"{t} {n}" for t, n in themes.most_common()),
               **{f"n_{_slug(name).replace('-', '_')}": themes.get(name, 0) for name, *_ in THEMES},
               "from_curated_sources": sum(bool(e["curated_source"]) for e in evs), "companies_named": len(named), "new_prospects": sum(_norm(c) not in known for c in named),
               "top_headlines": " | ".join(f"{e['published_at']} · {e['theme']} · {e['title']}" for e in top),
               "top_url": top[0]["url"] if top else "", "to_review": sum(r["segment_id"] == sid for r in review),
               "queries_ok": ok, "queries_error": err}
        summary.append(row)
        trend_rows.append({k: row[k] for k in ("industry_group", "industry_sector", "country", "industry_trend", "tailwind_index",
                                                  "articles", "momentum", "top_theme", "news_status")})
    # per group across all countries (an article found in two countries counts once)
    for g in sorted({s.industry_group for s in segs.values()}):
        seen, evs = set(), []
        for e in events:
            if e["industry_group"] == g and e["_key"] not in seen:
                seen.add(e["_key"])
                evs.append(e)
        checked = any(r["news_status"] != "not checked" for r in summary if r["industry_group"] == g)
        tail, tr = trend(evs)
        if tr is None and checked:
            tr, tail = NEUTRAL, 0.0
        trend_rows.append({"industry_group": g, "industry_sector": sector_of(g), "country": "ALL", "industry_trend": "" if tr is None else tr,
                           "tailwind_index": "" if tail is None else tail, "articles": len(evs), "momentum": "",
                           "top_theme": next((t for t, _ in Counter(e["theme"] for e in evs).most_common() if t != OTHER_THEME), ""),
                           "news_status": "found" if evs else ("checked, nothing found" if checked else "not checked")})

    # ---- companies named in the counted articles
    comp = {}
    for e in sorted(events, key=lambda e: e["published_at"]):
        for c in e["_companies"]:
            k = (_norm(c), e["country"])
            d = comp.setdefault(k, {"company_name": c, "country": e["country"], "groups": Counter(), "themes": Counter(), "mentions": 0})
            d["mentions"] += 1
            d["groups"][e["industry_group"]] += 1
            d["themes"][e["theme"]] += 1
            d.update(latest_date=e["published_at"], latest_headline=e["title"], url=e["url"])
    companies = []
    for (n, _), d in comp.items():
        companies.append({"company_name": d["company_name"], "country": d["country"], "industry_group": d["groups"].most_common(1)[0][0],
                          "mentions": d["mentions"], "themes": "; ".join(t for t, _ in d["themes"].most_common()),
                          "latest_date": d["latest_date"], "latest_headline": d["latest_headline"], "url": d["url"],
                          "known_account": "yes" if n in known else "no", "account_id": known.get(n, "") if known.get(n) != "yes" else "",
                          "in_company_mode": "yes" if n in tracked else "no"})
    companies.sort(key=lambda c: (c["known_account"] == "yes", -c["mentions"], c["company_name"]))

    ev_cols = ["segment_id", "industry_group", "country", "published_at", "age_days", "theme", "theme_basis", "theme_weight", "recency_factor",
               "weighted", "industry_score", "region_score", "check", "title", "publisher", "curated_source", "publisher_country", "industry_evidence",
               "region_evidence", "url", "google_url", "source", "query_theme", "companies", "text_status", "lead"]
    pub_rows = []
    for name, homes in sorted(pubs.items(), key=lambda x: -sum(x[1].values())):
        home, basis = region.publisher_home(name, "", "", {})
        learned = region.learned.get((name or "").strip().lower())
        pub_rows.append({"publisher": name, "articles": sum(homes.values()), "home_country": home or "", "basis": basis,
                         "learned_country": learned[0] if learned else "", "learned_share": learned[1] if learned else "",
                         "learned_from": learned[2] if learned else "", "trade_press_for": trade_press_group(name) or "",
                         "homes_seen": "; ".join(f"{c} {n}" for c, n in homes.most_common())})
    write_csv(out_dir, "publishers.csv", pub_rows, ["publisher", "articles", "home_country", "basis", "learned_country", "learned_share",
                                                     "learned_from", "trade_press_for", "homes_seen"])
    order = lambda e: (e["segment_id"], e["published_at"])
    write_csv(out_dir, "segment_events.csv", sorted(events, key=order, reverse=True), ev_cols)
    write_csv(out_dir, "segment_review.csv", sorted(review, key=order, reverse=True), ev_cols)
    write_csv(out_dir, "segment_summary.csv", summary, list(summary[0]) if summary else ["segment_id"])
    write_csv(out_dir, "industry_trend.csv", trend_rows, ["industry_group", "industry_sector", "country", "industry_trend", "tailwind_index",
                                                          "articles", "momentum", "top_theme", "news_status"])
    write_csv(out_dir, "segment_companies.csv", companies, ["company_name", "country", "industry_group", "mentions", "themes", "latest_date",
                                                            "latest_headline", "url", "known_account", "account_id", "in_company_mode"])
    return {"segments": len(summary), "events": len(events), "review": len(review), "companies": len(companies),
            "new_prospects": sum(c["known_account"] == "no" for c in companies), "status": Counter(s["news_status"] for s in summary)}
