"""Is a segment article about this industry in this country? Evidence points, like company mode's identity evidence.

Each article gets an industry score and a region score, with the evidence behind each. It counts when both reach
their minimum; otherwise it goes to segment_review.csv with the reason.

INDUSTRY (counts at 3+)                                      REGION (counts at 2+)
  sector word in the headline ................ 3              own-country place in the headline ............ 3
  else an industry word in the headline ...... 2              dateline / page contentLocation in the country  3
  curated source or trade press for it ...... 3              publisher based in the country ............... 2
  sector word in the lead (summary or first      (curated source for one country, domain, page data or
                                                               PUBLISHERS list; learned = 1)
    600 characters of the text) .............. 2              page locale is the country (en-AU, not GB/US)  1
  else an industry word in the lead .......... 1              text names the country 2+ times, at least as
  3+ sector or industry words in the body .... 1                often as any other ........................... 2
                                                                (once, and no other more often: 1)
Words in another sense are removed first                    headline names another country, not this one . -3
(SECTOR_EXCLUDE: "taken to hospital", "his lawyer").        dateline / contentLocation in another country  -3
                                                            publisher based in another country ........... -1
                                                            text is mostly about another country ......... -2

"Learned" publisher homes: a publisher whose articles name one country in the headline (or dateline) at least 80% of
the time, over 5+ articles, is taken to be based there. Our searches require the segment's place words, which skews this
towards the countries searched, so a learned home is worth only 1 point and wire services / global outlets
(GLOBAL_PUBLISHERS) are never learned. They are written to publishers.csv so they can be checked.
"Another country" includes places outside the segment countries (OTHER_PLACES: China, Gaza, Germany...).
"""
import json
import re
from collections import Counter, defaultdict

from .sectors import (COUNTRIES, INDUSTRY_EVIDENCE, OTHER_PLACES, SECTOR_STRONG, SECTOR_TERMS, _TRADE, country_code, is_global_publisher, place_regex,
                      publisher_country, strip_other_meanings, term_regex, trade_press_group)

INDUSTRY_MIN = 3
REGION_MIN = 2
LEAD_CHARS = 600
BODY_CHARS = 5000
LEARN_MIN_ARTICLES = 5
ELSEWHERE = "elsewhere"                # a place outside the segment countries (OTHER_PLACES)
LEARN_MIN_SHARE = 0.8
DEFAULT_LOCALES = {"US", "UK"}         # many sites declare en-US / en-GB whatever their country, so these say nothing


def _split_case(words):
    """(case-insensitive regex, case-sensitive regex): acronyms like IT, HR, NHS only count in capitals."""
    upper = [w for w in words if w.isupper() and len(w) <= 6]
    return term_regex([w for w in words if w not in upper]), term_regex(upper, case_sensitive=True)


def _find(rx_pair, text):
    return rx_pair[0].findall(text or "") + rx_pair[1].findall(text or "")


def _tld_country(*urls):
    for u in urls:
        host = re.sub(r"^https?://", "", (u or "").lower()).split("/")[0]
        if not host or "news.google." in host:
            continue
        for code, c in COUNTRIES.items():
            if any(host.endswith(t) for t in c["tlds"]):
                return code
    return None


# "SYDNEY, Nov 12 (Reuters) -", "LONDON — ", "Auckland, New Zealand: "
_DATELINE = re.compile(r"^\s*([A-Z][A-Za-z.' ]{2,40}?)\s*(?:,\s*[A-Za-z0-9 .]{1,25})?\s*(?:\([^)]{1,30}\))?\s*[-–—:]\s", re.M)


class RegionScorer:
    def __init__(self):
        self.place_rx = {c: place_regex(c) for c in COUNTRIES}
        self.place_rx[ELSEWHERE] = _split_case(OTHER_PLACES)
        self.learned = {}                                  # publisher (lower) -> (country, share, n)

    def mentions(self, text):
        """Place-word mentions per country."""
        return Counter({c: len(_find(rx, text)) for c, rx in self.place_rx.items() if text} ) + Counter()

    def countries_named(self, text):
        return {c for c, n in self.mentions(text).items() if n}

    def to_country(self, s):
        """'AU', 'Australia', 'en-AU', 'Sydney' -> 'AU'; None if unknown."""
        s = (s or "").strip()
        if not s:
            return None
        m = re.fullmatch(r"[a-z]{2}[-_]([A-Za-z]{2})", s)
        code = country_code(m.group(1) if m else s)
        if code in COUNTRIES:
            return code
        named = self.countries_named(s)
        return next(iter(named)) if len(named) == 1 else None

    def dateline_countries(self, text, meta):
        found = set()
        m = _DATELINE.match((text or "")[:200])
        if m and m.group(1).isupper():                     # datelines are written in capitals: "SYDNEY", "NEW YORK"
            c = self.to_country(m.group(1).title())
            if c:
                found.add(c)
        for loc in (meta or {}).get("content_location", []):
            c = self.to_country(loc)
            if c:
                found.add(c)
        return found

    def publisher_home(self, pub, pub_url, final_url, meta, curated=None):
        """(country, basis) for where the publisher is based, or (None, ''). curated: (name, country) of a curated source."""
        if curated:
            return curated[1], f"curated: {curated[0]}"
        c = _tld_country(final_url, pub_url)
        if c:
            return c, "domain"
        for pc in (meta or {}).get("publisher_country", []):
            c = self.to_country(pc)
            if c:
                return c, "page data"
        c = publisher_country(pub)
        if c:
            return c, "known outlet"
        c = _tld_country(pub if "." in (pub or "") else "")   # some publisher names are domains
        if c:
            return c, "domain"
        hit = None if is_global_publisher(pub) else self.learned.get((pub or "").strip().lower())
        return (hit[0], "learned") if hit else (None, "")

    def learn(self, articles):
        """articles: iterable of (publisher, title, text, meta). A publisher is learned when one country is named alone in
        its headlines (or datelines) for at least 80% of 3+ articles. Each distinct article counts once."""
        votes = defaultdict(Counter)
        for pub, title, text, meta in articles:
            named = self.countries_named(title) | self.dateline_countries(text, meta)
            if len(named) == 1 and pub and not is_global_publisher(pub):
                votes[pub.strip().lower()][next(iter(named))] += 1
        self.learned = {}
        for p, cnt in votes.items():
            n = sum(cnt.values())
            c, k = cnt.most_common(1)[0]
            if n >= LEARN_MIN_ARTICLES and k / n >= LEARN_MIN_SHARE:
                self.learned[p] = (c, round(k / n, 2), n)
        return self.learned

    def score(self, own, title, summary, text, pub, pub_url, final_url, meta, curated=None):
        """(points, evidence list, home country)."""
        s, ev = 0, []
        head = f"{title}. {summary or ''}"
        named = self.countries_named(head)
        if own in named:
            s += 3
            ev.append("+3 place in headline")
        elif named:
            s -= 3
            ev.append(f"-3 headline names {'/'.join(sorted(named))}")
        dl = self.dateline_countries(text, meta)
        if own in dl:
            s += 3
            ev.append("+3 dateline")
        elif dl:
            s -= 3
            ev.append(f"-3 dateline {'/'.join(sorted(dl))}")
        home, basis = self.publisher_home(pub, pub_url, final_url, meta, curated)
        if home == own and basis == "learned":         # learned from our own (region-skewed) searches: supporting evidence only
            s += 1
            ev.append("+1 publisher (learned)")
        elif home == own:
            s += 2
            ev.append(f"+2 publisher ({basis})")
        elif home:
            s -= 1
            ev.append(f"-1 publisher in {home} ({basis})")
        loc = self.to_country((meta or {}).get("locale", ""))
        if loc == own and loc not in DEFAULT_LOCALES:
            s += 1
            ev.append("+1 page locale")
        if text:
            m = self.mentions(text[:3000])
            o = m.get(own, 0)
            other, top = max(((c, n) for c, n in m.items() if c != own), key=lambda x: x[1], default=(None, 0))
            if o >= 2 and o >= top:
                s += 2
                ev.append(f"+2 text names it {o}x")
            elif o >= 1 and o >= top:
                s += 1
                ev.append("+1 text names it once")
            elif top >= 3 and top >= 2 * o:
                s -= 2
                ev.append(f"-2 text mostly about {other} ({top}x vs {o}x)")
        return s, ev, home


class IndustryScorer:
    def __init__(self):
        self._cache = {}

    def _rx(self, group, extra_terms=()):
        key = (group, tuple(extra_terms))
        if key not in self._cache:
            self._cache[key] = (_split_case(SECTOR_TERMS[group] + SECTOR_STRONG.get(group, []) + list(extra_terms)), _split_case(INDUSTRY_EVIDENCE.get(group, [])))
        return self._cache[key]

    def score(self, group, title, summary, text, pub, extra_terms=(), curated=None):
        """(points, evidence list). curated: name of a curated source for this group (segment_sources.csv)."""
        sector, evidence = self._rx(group, extra_terms)
        clean = lambda t: strip_other_meanings(group, t)
        s, ev = 0, []
        t = clean(title)
        hit = _find(sector, t)
        if hit:
            s += 3
            ev.append(f"+3 sector in headline ({hit[0]})")
        else:
            hit = _find(evidence, t)
            if hit:
                s += 2
                ev.append(f"+2 industry word in headline ({hit[0]})")
        lead = clean(f"{summary or ''} {(text or '')[:LEAD_CHARS]}")
        if curated:
            s += 3
            ev.append(f"+3 curated source ({curated})")
        elif trade_press_group(pub) == group:
            # a known title counts on its own; a publisher matched only by a group word in its name ("Sydney Criminal Lawyers",
            # a firm's blog) needs some industry word in the headline or lead as well
            if (pub or "").strip().lower() in _TRADE or s or _find(sector, lead) or _find(evidence, lead):
                s += 3
                ev.append("+3 trade press")
            else:
                s += 1
                ev.append("+1 trade press by name only")
        hit = _find(sector, lead)
        if hit:
            s += 2
            ev.append(f"+2 sector in lead ({hit[0]})")
        else:
            hit = _find(evidence, lead)
            if hit:
                s += 1
                ev.append(f"+1 industry word in lead ({hit[0]})")
        if text:
            body = clean(text[LEAD_CHARS:BODY_CHARS])
            n = len(_find(sector, body)) + len(_find(evidence, body))
            if n >= 3:
                s += 1
                ev.append(f"+1 body {n}x")
        return s, ev


def meta_of(raw):
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}
