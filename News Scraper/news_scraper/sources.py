"""Free news sources. Each fetch(company, since, until) returns a list of article dicts:
    {title, url, publisher, published_at (aware datetime, UTC), summary}
and raises FetchError when the source could not be checked (so "checked, nothing found" stays distinct
from "could not check").

| source   | lookback          | notes                                                                    |
|----------|-------------------|--------------------------------------------------------------------------|
| google   | 6+ months         | Google News RSS search; 100 results per query, so busy windows are split |
| bing     | recent only       | Bing News RSS; no date filter, so used as a top-up for the latest news   |
| gdelt    | last ~90 days     | GDELT DOC 2.0 API; max 1 request per 5 seconds for everyone              |
| newsroom | what the site has | the company's own RSS/Atom feed; skipped when there is no website        |
"""
import datetime as dt
import email.utils
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from . import http
from .match import core_name, root_domain

UTC = dt.timezone.utc
GOOGLE_REGION = {"AU": ("en-AU", "AU"), "NZ": ("en-NZ", "NZ"), "UK": ("en-GB", "GB"), "GB": ("en-GB", "GB"), "US": ("en-US", "US"),
                 "PH": ("en-PH", "PH"), "CA": ("en-CA", "CA"), "SG": ("en-SG", "SG"), "IE": ("en-IE", "IE")}
GOOGLE_CAP = 100          # Google News RSS never returns more than this per query
GDELT_MAX_DAYS = 89       # GDELT DOC API searches a rolling ~3-month window
FEED_PATHS = ["/feed", "/rss", "/news/feed", "/blog/feed", "/feed.xml", "/rss.xml", "/news/rss.xml"]


class SkipSource(Exception):
    """The source does not apply to this company (e.g. no website, or the website has no news feed)."""


def _text(html):
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def _rfc822(s):
    try:
        d = email.utils.parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _iso(s):
    try:
        d = dt.datetime.fromisoformat((s or "").strip().replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def _q(term):
    return f'"{term}"' if " " in term or not term.isalnum() else term


def _query(company):
    """'"Deputy"', or with aliases '("Culture Amp" OR "CultureAmp")'. Context words narrow common names:
    '"Deputy" (software OR scheduling)'. Search engines look at the whole article, so the context word does
    not have to be in the headline."""
    names = list(dict.fromkeys([core_name(company.name), *company.aliases]))
    q = f'"{names[0]}"' if len(names) == 1 else "(" + " OR ".join(f'"{n}"' for n in names) + ")"
    if company.context:
        q += " (" + " OR ".join(_q(t) for t in company.context) + ")" if len(company.context) > 1 else f" {_q(company.context[0])}"
    return q


# ---------------------------------------------------------------- Google News RSS
def _google_once(query, country, since, until):
    hl, gl = GOOGLE_REGION.get((country or "AU").upper(), ("en-AU", "AU"))
    # dates first: Google News reads only about the first 32 words of a query and silently drops the rest
    q = f"after:{since:%Y-%m-%d} before:{until + dt.timedelta(days=1):%Y-%m-%d} {query}"
    r = http.get("https://news.google.com/rss/search", params={"q": q, "hl": hl, "gl": gl, "ceid": f"{gl}:{hl.split('-')[0]}"},
                 key="google", interval=1.2)
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        pub = (it.findtext("source") or "").strip()
        title = (it.findtext("title") or "").strip()
        if pub and title.endswith(" - " + pub):
            title = title[: -len(pub) - 3]
        # no summary: Google's description is a list of *other* related headlines, which misleads matching and classification
        src = it.find("source")
        out.append({"title": title, "url": it.findtext("link"), "publisher": pub, "published_at": _rfc822(it.findtext("pubDate")), "summary": "",
                    "publisher_url": src.get("url", "") if src is not None else ""})
    return out


def google_search(query, country, since, until):
    """Any Google News query (company or sector). Whole window first; if it hits the 100-result cap,
    re-query month by month so nothing is cut off."""
    items = _google_once(query, country, since, until)
    if len(items) < GOOGLE_CAP or (until - since).days <= 31:
        return items
    out, start = [], since
    while start <= until:
        end = min(until, start + dt.timedelta(days=30))
        out += _google_once(query, country, start, end)
        start = end + dt.timedelta(days=1)
    return out


def google(company, since, until):
    return google_search(_query(company), company.country, since, until)


# ---------------------------------------------------------------- Bing News RSS
BING_MARKET = {"AU": "en-AU", "NZ": "en-NZ", "UK": "en-GB", "GB": "en-GB", "US": "en-US", "CA": "en-CA", "PH": "en-PH",
               "SG": "en-SG", "IE": "en-IE"}


def bing_search(query, market=None):
    """Any Bing News query. market (e.g. 'AU') sets Bing's regional edition; None keeps Bing's default."""
    params = {"q": query, "format": "rss"}
    if market:
        params["mkt"] = BING_MARKET.get(market.upper(), "en-US")
    r = http.get("https://www.bing.com/news/search", params=params, key="bing", interval=1.2)
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        link = it.findtext("link") or ""
        real = parse_qs(urlparse(link).query).get("url", [link])[0]       # unwrap Bing's click-tracking link
        pub = next((c.text for c in it if c.tag.endswith("}Source")), "") or root_domain(real)
        out.append({"title": (it.findtext("title") or "").strip(), "url": real, "publisher": pub,
                    "published_at": _rfc822(it.findtext("pubDate")), "summary": _text(it.findtext("description"))})
    return out


def bing(company, since, until):
    return bing_search(_query(company))


# ---------------------------------------------------------------- GDELT DOC 2.0
def gdelt(company, since, until):
    q = _query(company)
    if " " not in core_name(company.name) and not company.aliases:
        q = q.replace(f'"{core_name(company.name)}"', core_name(company.name), 1)   # GDELT rejects short quoted phrases ("Rokt")
    return gdelt_search(q, since, until)


def gdelt_search(q, since, until, filters="sourcelang:english"):
    """Any GDELT query. filters: GDELT operators added to the query, e.g. 'sourcelang:english sourcecountry:australia'."""
    since = max(since, dt.date.today() - dt.timedelta(days=GDELT_MAX_DAYS))
    params = {"query": f"{q} {filters}".strip(), "mode": "artlist", "format": "json", "maxrecords": 250, "sort": "datedesc",
              "startdatetime": f"{since:%Y%m%d}000000", "enddatetime": f"{until:%Y%m%d}235959"}
    # GDELT allows one request at a time, 5+ seconds apart, for everyone: serial, 6 seconds after the last one finished
    r = http.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, key="gdelt", interval=6.0, timeout=60, serial=True, retries=1)
    if not r.text.strip():
        return []                            # no results
    try:
        arts = json.loads(r.text, strict=False).get("articles", [])   # strict=False: GDELT titles can contain raw control characters
    except ValueError:                       # GDELT answers some bad queries with a plain-text message
        raise http.FetchError(r.text[:150])
    return [{"title": a.get("title", ""), "url": a.get("url"), "publisher": a.get("domain", ""),
             "published_at": dt.datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if a.get("seendate") else None,
             "summary": ""} for a in arts]


# ---------------------------------------------------------------- company website feed
def find_feed(domain):
    """The site's RSS/Atom feed: <link rel=alternate> on the home page, else a few common paths. None if not found."""
    base = f"https://{root_domain(domain)}"
    try:
        home = http.get(base, interval=1.0, retries=1)
        soup = BeautifulSoup(home.text, "html.parser")
        for ln in soup.find_all("link", rel="alternate"):
            if "rss" in (ln.get("type") or "") or "atom" in (ln.get("type") or ""):
                return urljoin(home.url, ln.get("href"))
        base = f"{urlparse(home.url).scheme}://{urlparse(home.url).netloc}"
    except http.FetchError:
        pass
    for p in FEED_PATHS:
        try:
            r = http.get(base + p, interval=1.0, retries=0)
        except http.FetchError:
            continue
        if r.content.lstrip()[:200].lower().find(b"<rss") >= 0 or b"<feed" in r.content[:300].lower():
            return r.url
    return None


def parse_feed(content):
    root = ET.fromstring(content.lstrip().lstrip(b"\xef\xbb\xbf") if isinstance(content, bytes) else content.lstrip())
    out = []
    for it in root.iter("item"):                                   # RSS 2.0
        out.append({"title": (it.findtext("title") or "").strip(), "url": it.findtext("link"), "publisher": "",
                    "published_at": _rfc822(it.findtext("pubDate")), "summary": _text(it.findtext("description"))[:500]})
    atom = "{http://www.w3.org/2005/Atom}"
    for e in root.iter(atom + "entry"):                            # Atom
        link = e.find(atom + "link")
        out.append({"title": (e.findtext(atom + "title") or "").strip(), "url": link.get("href") if link is not None else None,
                    "publisher": "", "published_at": _iso(e.findtext(atom + "published") or e.findtext(atom + "updated")),
                    "summary": _text(e.findtext(atom + "summary"))[:500]})
    return out


def newsroom(company, since, until, feed_url):
    """feed_url comes from the store (found once, re-checked every 30 days). No website or no feed -> SkipSource."""
    if not feed_url:
        raise SkipSource("no news feed on the company website")
    r = http.get(feed_url, interval=1.0)
    try:
        items = parse_feed(r.content)
    except ET.ParseError as e:
        raise http.FetchError(f"feed not parseable: {e}")
    for i in items:
        i["publisher"] = root_domain(company.domain)
    return items


SOURCES = {"google": google, "bing": bing, "gdelt": gdelt, "newsroom": newsroom}
