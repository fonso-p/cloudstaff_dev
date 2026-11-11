"""Company card: identity facts read from the company's own website, used to confirm that an article means
*this* company and not something else with the same name.

Read from the home page and one About page (robots.txt respected, refreshed every 30 days):
  - site_name, legal_name, alt_names   og:site_name, JSON-LD Organization name / legalName / alternateName
  - keywords                           distinctive words and short phrases from the page title and description
                                       (e.g. Deputy -> "employee scheduling", "timesheets", "time clock")
  - ticker, people, city               JSON-LD tickerSymbol, founder / employee names, address locality
Companies without a website get an empty card ("no website"); matching then relies on the CSV columns.
"""
import datetime as dt
import json
import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import http
from .match import core_name, root_domain

REFRESH_DAYS = 30
ABOUT_PATHS = ["/about", "/about-us", "/company", "/about/", "/en/about", "/company/about"]
MAX_KEYWORDS = 12
# words that say nothing about who a company is (they appear in almost any business article)
GENERIC = set("""a an and the of for to in on with by at from your our you we us is are be it its this that as or new more most best leading top
free online official home homepage welcome site website page pages company companies inc ltd pty group global world one all get start login log
sign up now today how what why who help easy simple smart better faster powerful modern trusted every everything business businesses team teams
people work working manage management solution solutions platform platforms service services product products customer customers data tool tools
app apps digital future world's australia australian more than over million thousands leader growth grow
about where other others everyone anyone someone create created creating small large big trial gives give complete simplifies simple simplify
move moves built build across happening what's whats learn core values value organize discuss connects connect transforming transform globally
global using use used technology making make makes fair pay less cheaper cheap price prices rewards awarded award supplier safely confidence meet
higher high standards standard smarter hourly visual media social posts suite project projects other bank accounts account financial money
we're you're it's don't can will just like also into about our their them they there here which while when then than very much many any some
each every both such only own same so too can't way ways need needs want find found see look day days year years time times first last next
best-in-class all-in-one end-to-end easy-to-use award-winning cloud-based cloud based powered power ai uk's nz au us usa uk nz's au's
contact support pricing plans plan features feature resources blog news careers partners partner integrations integration download demo""".split())


def _robots_ok(base, url):
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = http.get(base + "/robots.txt", interval=1.0, retries=0)
        rp.parse(r.text.splitlines())
    except http.FetchError:
        return True                                            # no robots.txt: allowed
    return rp.can_fetch("*", url)


def _meta(soup, *names):
    for n in names:
        t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if t and t.get("content"):
            return t["content"].strip()
    return ""


def _orgs(soup):
    """JSON-LD Organization-like objects on the page."""
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "", strict=False)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o)
            elif isinstance(o, dict):
                if isinstance(o.get("@graph"), list):
                    stack.extend(o["@graph"])
                t = o.get("@type", "")
                types = {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}
                if types & {"organization", "corporation", "localbusiness", "softwareapplication", "website"}:
                    yield o


def _names(v):
    vs = v if isinstance(v, list) else [v]
    return [x.get("name") if isinstance(x, dict) else x for x in vs if (isinstance(x, dict) and x.get("name")) or isinstance(x, str)]


def keywords(texts, name):
    """Distinctive phrases (title segments) and words, minus the company name and generic business words."""
    name_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
    phrases, words = [], {}
    for text in texts:
        for seg in re.split(r"\s*[|–—:•·,]\s*|\s+-\s+|\s*&\s*", text or ""):
            toks = [t for t in re.findall(r"[a-z][a-z0-9'-]+", seg.lower()) if t not in name_tokens]
            while toks and toks[0] in GENERIC:
                toks.pop(0)
            while toks and toks[-1] in GENERIC:
                toks.pop()
            if 2 <= len(toks) <= 3 and sum(t not in GENERIC for t in toks) >= 2:
                phrases.append(" ".join(toks))
            for t in toks:
                if t not in GENERIC and len(t) >= 5 and not t.isdigit() and "'" not in t:
                    words[t] = words.get(t, 0) + 1
    out = list(dict.fromkeys(phrases))
    out += [w for w, _ in sorted(words.items(), key=lambda kv: -kv[1]) if not any(w in p.split() for p in out)]
    return out[:MAX_KEYWORDS]


def build(company):
    """The card as a dict. Never raises: a failure comes back as status 'error: ...'."""
    card = {"status": "", "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "site_name": "", "description": "",
            "legal_name": "", "alt_names": [], "ticker": "", "people": [], "city": "", "keywords": [], "pages": []}
    if not company.domain:
        card["status"] = "no website"
        return card
    base = f"https://{root_domain(company.domain)}"
    texts = []
    try:
        if not _robots_ok(base, base + "/"):
            card["status"] = "blocked by robots.txt"
            return card
        home = http.get(base, interval=1.0, retries=1)
        base = f"{urlparse(home.url).scheme}://{urlparse(home.url).netloc}"
        pages = [(home.url, home.text)]
        soup = BeautifulSoup(home.text, "html.parser")
        about = next((urljoin(home.url, a["href"]) for a in soup.find_all("a", href=True)
                      if re.search(r"/(about|about-us|company|our-story)/?$", urlparse(urljoin(home.url, a["href"])).path, re.I)
                      and root_domain(urljoin(home.url, a["href"])) == root_domain(company.domain)), None)
        for url in [about] if about else [base + p for p in ABOUT_PATHS]:
            if not _robots_ok(base, url):
                continue
            try:
                r = http.get(url, interval=1.0, retries=0)
                pages.append((r.url, r.text))
                break
            except http.FetchError:
                continue
    except http.FetchError as e:
        card["status"] = f"error: {e}"[:200]
        return card

    for url, html in pages:
        soup = BeautifulSoup(html, "html.parser")
        card["pages"].append(url)
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        desc = _meta(soup, "og:description", "description")
        card["site_name"] = card["site_name"] or _meta(soup, "og:site_name")
        card["description"] = card["description"] or desc
        texts += [title, desc, _meta(soup, "og:title"), _meta(soup, "keywords")]
        for o in _orgs(soup):
            card["legal_name"] = card["legal_name"] or (o.get("legalName") or "")
            card["alt_names"] += [n for n in _names(o.get("alternateName", [])) if n]
            card["ticker"] = card["ticker"] or (o.get("tickerSymbol") or "")
            card["people"] += [n for n in _names(o.get("founder", [])) + _names(o.get("founders", [])) + _names(o.get("employee", [])) if n]
            addr = o.get("address")
            addr = addr[0] if isinstance(addr, list) and addr else addr
            if isinstance(addr, dict):
                card["city"] = card["city"] or (addr.get("addressLocality") or "")
            if o.get("description"):
                texts.append(o["description"])
    name = core_name(company.name)
    if card["site_name"]:                                   # the site's own name, e.g. SafetyCulture's site now says "Mitti"
        card["alt_names"].insert(0, card["site_name"])
    card["alt_names"] = [n for n in dict.fromkeys(card["alt_names"]) if core_name(n).lower() != name.lower() and len(n) <= 40][:5]
    card["people"] = list(dict.fromkeys(p.strip() for p in card["people"] if len(p.strip()) >= 5))[:10]
    card["keywords"] = keywords(texts, name)
    card["status"] = "ok" if card["keywords"] or card["people"] or card["ticker"] else "ok (little found)"
    return card


def ensure(store, company, refresh=False):
    """The stored card, rebuilt if missing, older than REFRESH_DAYS, or refresh=True."""
    card = store.profile(company.company_id)
    if card and not refresh:
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(card["built_at"])
        if age < dt.timedelta(days=REFRESH_DAYS) and (card["status"] == "no website") == (not company.domain):
            return card
    card = build(company)
    store.set_profile(company.company_id, card)
    return card
