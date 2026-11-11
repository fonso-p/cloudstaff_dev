"""HTML -> article text, title, publish date. BeautifulSoup only (no paid service, no extra packages).

Order of attempts:
  1. JSON-LD articleBody: the text the publisher itself declares (NewsArticle / Article / BlogPosting).
  2. Paragraph density: the <article> element, else the container holding the most paragraph text.
  3. Meta description: a last resort, returned with method "meta" (usually too short to count).
"""
import json
import re

from bs4 import BeautifulSoup

ARTICLE_TYPES = {"newsarticle", "article", "blogposting", "reportagenewsarticle", "analysisnewsarticle", "pressrelease", "techarticle"}
JUNK_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button", "svg", "iframe", "figure", "figcaption"]
JUNK_ATTR = re.compile(r"comment|share|social|related|newsletter|subscribe|promo|advert|\bad-|cookie|banner|sidebar|footer|menu|breadcrumb|popup|modal", re.I)
BOILER = re.compile(r"^(advertisement|sign up|subscribe|read more|related:|share this|follow us|click here|cookie|all rights reserved|©)", re.I)
MIN_PARA = 40


def _jsonld_objects(soup):
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "", strict=False)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                stack.extend(o.get("@graph", []) if isinstance(o.get("@graph"), list) else [])
                yield o
            elif isinstance(o, list):
                stack.extend(o)


def _types(o):
    t = o.get("@type", "")
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _clean(text):
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\r\n\r\n", text or "")]
    return "\n\n".join(p for p in paras if p and not BOILER.match(p))


def _meta(soup, *names):
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"itemprop": n})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def extract(html):
    """Returns dict(text, title, published, author, method)."""
    soup = BeautifulSoup(html, "html.parser")
    meta = {"title": _meta(soup, "og:title", "twitter:title") or (soup.title.get_text(strip=True) if soup.title else ""),
            "published": _meta(soup, "article:published_time", "datePublished", "pubdate", "date"), "author": _meta(soup, "author", "article:author")}

    # 1. JSON-LD
    for o in _jsonld_objects(soup):
        if _types(o) & ARTICLE_TYPES:
            meta["title"] = o.get("headline") or meta["title"]
            meta["published"] = o.get("datePublished") or meta["published"]
            a = o.get("author")
            if isinstance(a, dict):
                meta["author"] = a.get("name") or meta["author"]
            elif isinstance(a, list) and a and isinstance(a[0], dict):
                meta["author"] = ", ".join(x.get("name", "") for x in a if isinstance(x, dict)) or meta["author"]
            body = o.get("articleBody")
            if isinstance(body, str) and len(body) >= 300:
                return {**meta, "text": _clean(BeautifulSoup(body, "html.parser").get_text("\n\n")), "method": "jsonld"}

    # 2. paragraph density
    for t in soup(JUNK_TAGS):
        t.decompose()
    for t in soup.find_all(attrs={"class": JUNK_ATTR}) + soup.find_all(attrs={"id": JUNK_ATTR}):
        if t.name not in ("body", "html", "article", "main"):
            t.decompose()
    best, best_len = None, 0
    candidates = soup.find_all("article") or []
    candidates += list({id(p.parent): p.parent for p in soup.find_all("p") if p.parent is not None}.values())
    for c in candidates:
        n = sum(len(p.get_text(" ", strip=True)) for p in c.find_all("p", recursive=c.name != "article") if len(p.get_text(strip=True)) >= MIN_PARA)
        if n > best_len:
            best, best_len = c, n
    if best is not None and best_len >= 300:
        paras = [p.get_text(" ", strip=True) for p in best.find_all("p") if len(p.get_text(strip=True)) >= MIN_PARA]
        return {**meta, "text": _clean("\n\n".join(paras)), "method": "paragraphs"}

    # 3. meta description
    return {**meta, "text": _meta(soup, "og:description", "description", "twitter:description"), "method": "meta"}
