"""Job signals: how many roles a company is advertising, read from its own website. Keyless, matched by domain.

    python -m news_scraper jobs --companies companies.csv [--db data/news.db] [--workers 6] [--limit N]

For each company with a website (robots.txt respected):
  1. find the careers page: a link on the home page ("Careers", "Jobs", "Join us"…) or a common path (/careers, /jobs…)
  2. look on the careers page (and the home page) for an applicant tracking system (ATS) with a public job feed:
       Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR, Recruitee, Personio, Rippling, Pinpoint, Breezy,
       Teamtailor, Workday, UltiPro, Paylocity, JobAdder
     and read every open role from it (title, department, location, date posted)
  3. otherwise read schema.org JobPosting data (what Google for Jobs uses) from the careers page and the job pages it links to
  4. careers pages with nothing readable are rendered in headless Chromium and checked again (browser_pass)
  Job boards (SEEK, Indeed, LinkedIn) are noted in `method` but never read.

Each run stores a snapshot (job_snapshots) and the roles seen (job_postings). Exported as one "Hiring" event per company in
signal_events.csv, plus open_roles / job_postings_30d / hiring_spike in company_summary.csv. A hiring spike needs an earlier
snapshot to compare with, so it is blank after the first run.
"""
import datetime as dt
import email.utils
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from cloudstaff_dev.signals import http
from cloudstaff_dev.common.company_keys import root_domain
from cloudstaff_dev.signals.profile import _robots_ok

TABLES = """
CREATE TABLE IF NOT EXISTS job_snapshots (
  company_id TEXT NOT NULL, checked_at TEXT NOT NULL, status TEXT, method TEXT, careers_url TEXT, board_url TEXT,
  n_open INTEGER, n_30d INTEGER, n_dated INTEGER, departments TEXT, note TEXT,
  PRIMARY KEY (company_id, checked_at));
CREATE TABLE IF NOT EXISTS job_postings (
  company_id TEXT NOT NULL, posting_key TEXT NOT NULL, title TEXT, department TEXT, location TEXT, posted_at TEXT, url TEXT,
  first_seen TEXT, last_seen TEXT,
  PRIMARY KEY (company_id, posting_key));
"""
CAREER_TEXT = re.compile(r"\b(careers?|jobs?|join (us|our team|the team)|work (with|for) us|vacancies|(job|career|employment) opportunities|"
                         r"we'?re hiring|open (roles|positions)|current (vacancies|openings))\b", re.I)
# a URL path *segment* that names a careers page. Whole segments only: "job-costing", "jobsite-delivery" or a 2021 "jobsaver"
# blog post are not careers pages (on the 500-company sample about 1 in 5 "careers pages" were product pages, blog posts or
# the home page that a guessed /careers path redirected to)
CAREER_SEG = re.compile(r"^(careers?|jobs?|join(-?us|-our-team|-the-team|-our-people)?|work-(with|for)-us|vacanc(y|ies)|employment|"
                        r"(job|career|employment)-opportunities|opportunities|we-?re-hiring|hiring|current-(vacancies|openings|opportunities)|"
                        r"open-(roles|positions)|your-career|life-at-[\w-]+|working-(with|at|for)-[\w-]+)$", re.I)


CAREER_HOST = re.compile(r"^(careers?|jobs?|join|work|hiring|talent)\.", re.I)      # careers.hgv.com, jobs.example.com.au


def _careerish(url):
    """True when the URL is a job system's, is on a careers subdomain, or one of its path segments names a careers page."""
    u = urlparse(url)
    return (any(rx.search(url) for _, rx, _ in ATS_RX) or bool(CAREER_HOST.match(u.netloc.lower()))
            or any(CAREER_SEG.match(s) for s in u.path.lower().split("/") if s))


def _is_home(url, home_url):
    """The site's home page (same host, root path). A careers subdomain's root is not the home page."""
    u, h = urlparse(url), urlparse(home_url)
    return u.netloc.lower().removeprefix("www.") == h.netloc.lower().removeprefix("www.") and not u.path.strip("/")
CAREER_PATHS = ["/careers", "/jobs", "/careers/", "/join-us", "/work-with-us", "/join-our-team", "/about/careers", "/company/careers", "/vacancies"]
# a link from a careers landing page to its job list
HOP_TEXT = re.compile(r"(open (roles|positions|jobs)|view (all |our )?(jobs|roles|positions|vacancies|openings)|current (openings|vacancies|opportunities|jobs)|"
                      r"see (all |our )?(jobs|roles|openings)|(search|browse|find) (all |our )?(jobs|roles|vacancies|openings)|job search|all (openings|jobs)|"
                      r"job openings|explore (jobs|roles|opportunities))", re.I)
OWN_JOB = re.compile(r"/(jobs?|careers?|positions?|vacanc\w*|openings?|job-[a-z]{2}|requisitions?|opportunit\w*)/", re.I)   # /job-en/ too
JOB_PAGE = re.compile(r"/(jobs?|careers?|positions?|vacanc(y|ies)|opportunit(y|ies)|openings?|roles?)/[^/?#]{3,}", re.I)
MAX_JOB_PAGES = 25

# ATS with a public JSON/XML feed: (name, regex capturing the board id, feed url template)
ATS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)",
     "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true"),
    ("lever", r"jobs\.lever\.co/([A-Za-z0-9_.-]+)", "https://api.lever.co/v0/postings/{}?mode=json"),
    ("lever", r"jobs\.eu\.lever\.co/([A-Za-z0-9_.-]+)", "https://api.eu.lever.co/v0/postings/{}?mode=json"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", "https://api.ashbyhq.com/posting-api/job-board/{}"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)", "https://apply.workable.com/api/v1/widget/accounts/{}"),
    ("workable", r"https?://([A-Za-z0-9-]+)\.workable\.com", "https://apply.workable.com/api/v1/widget/accounts/{}"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", "https://api.smartrecruiters.com/v1/companies/{}/postings?limit=100"),
    ("bamboohr", r"https?://([A-Za-z0-9-]+)\.bamboohr\.com", "https://{}.bamboohr.com/careers/list"),
    ("recruitee", r"https?://([A-Za-z0-9-]+)\.recruitee\.com", "https://{}.recruitee.com/api/offers/"),
    ("personio", r"https?://([A-Za-z0-9-]+)\.jobs\.personio\.(?:de|com)", "https://{}.jobs.personio.de/xml"),
    # added Nov 2026 after a 500-company sample: each checked against a live board
    ("rippling", r"ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", "https://api.rippling.com/platform/api/ats/v1/board/{}/jobs"),
    ("pinpoint", r"https?://([A-Za-z0-9-]+)\.pinpointhq\.com", "https://{}.pinpointhq.com/postings.json"),
    ("breezy", r"https?://([A-Za-z0-9-]+)\.breezy\.hr", "https://{}.breezy.hr/json"),
    ("teamtailor", r"https?://([A-Za-z0-9-]+)\.teamtailor\.com", "https://{}.teamtailor.com/jobs.rss"),
    # board = "tenant|wdN|site", read with a POST (Workday's own careers site uses the same call)
    ("workday", r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)",
     "https://{0}.{1}.myworkdayjobs.com/wday/cxs/{0}/{2}/jobs"),
    # board = "tenant|board guid", POST
    ("ultipro", r"recruiting\d*\.ultipro\.com/([A-Za-z0-9]+)/JobBoard/([0-9a-fA-F-]{36})",
     "https://recruiting.ultipro.com/{0}/JobBoard/{1}/JobBoardView/LoadSearchResults"),
    # the board page itself carries the job list (Paylocity: window.pageData JSON; JobAdder: an HTML list)
    ("paylocity", r"recruiting\.paylocity\.com/recruiting/jobs/(?:All|List)/([0-9a-fA-F-]{36})",
     "https://recruiting.paylocity.com/recruiting/jobs/All/{}"),
    ("jobadder", r"clientapps\.jobadder\.com/(\d+/[A-Za-z0-9_-]+)", "https://clientapps.jobadder.com/{}"),
]
ATS_RX = [(n, re.compile(p, re.I), feed) for n, p, feed in ATS]
SKIP_IDS = {"embed", "api", "v1", "jobs", "careers", "www", "app", "apply", "static", "assets", "js", "career", "help", "support"}
# found but not readable without a key, a browser, or getting past a bot check
NO_FEED = [("jobadder", r"jobadder\.com"), ("employment hero", r"(jobs|careers)\.employmenthero\.com|employmenthero\.com/jobs"),
           ("workday", r"myworkdayjobs\.com"), ("seek", r"seek\.com\.au|seek\.co\.nz"), ("indeed", r"indeed\.com"),
           ("linkedin jobs", r"linkedin\.com/(company/[^\"']+/jobs|jobs)"), ("breezy", r"breezy\.hr"), ("teamtailor", r"teamtailor\.com"),
           ("pageup", r"pageuppeople\.com"), ("livehire", r"livehire\.com"), ("jazzhr", r"applytojob\.com"), ("icims", r"icims\.com"),
           ("dayforce", r"dayforcehcm\.com"), ("isolvedhire", r"isolvedhire\.com"), ("sentrient", r"sentrient\.online"),
           ("adp", r"workforcenow\.adp\.com"), ("ukg ready", r"entertimeonline\.com"), ("jobvite", r"jobvite\.com"), ("jobdiva", r"jobdiva\.com"),
           ("paylocity", r"paylocity\.com"), ("ultipro", r"ultipro\.com")]
# job detail links on a job system's own pages, read from the rendered careers page when there is no feed:
# the anchor text is the job title (no date)
ATS_JOB_LINK = re.compile(r"https?://[^/]*(isolvedhire\.com/jobs/\d+|jobs\.jobvite\.com/[^/]+/job/\w+|icims\.com/jobs/\d+/|"
                          r"dayforcehcm\.com/.*/Posting/View/\d+|employmenthero\.com/jobs/position/|livehire\.com/careers/[^/]+/job/|"
                          r"applytojob\.com/apply/\w+|pageuppeople\.com/.*/(jobDetails|job)\b|sentrient\.online/.*Job)", re.I)
NO_FEED_RX = [(n, re.compile(p, re.I)) for n, p in NO_FEED]
JOB_BOARDS = {"seek", "indeed", "linkedin jobs"}       # job boards, not the company's own job system: never read


def _job_system(url):
    """The URL is on a company's own job system that has no public feed (iSolvedHire, Dayforce, PageUp…), not a job board."""
    host = urlparse(url).netloc
    return any(rx.search(host) for n, rx in NO_FEED_RX if n not in JOB_BOARDS)
# the careers page says there is nothing open: a real zero, unlike a page whose list we can't see
_NO_VAC_STRICT = re.compile(r"\bno (current |open )*(vacanc|openings|positions|roles|jobs|opportunities)|\bnot (currently )?(hiring|recruiting)\b|"
                            r"\b(don'?t|do not) (currently )?have any (current |open )*(vacanc|openings|positions|roles|jobs)", re.I)


def ensure_tables(store):
    with store.lock, store.db:
        store.db.executescript(TABLES)


def _date(v):
    """ISO date (YYYY-MM-DD) from ISO strings, epoch milliseconds, or None."""
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            return dt.datetime.fromtimestamp(int(v) / (1000 if int(v) > 10**11 else 1), dt.timezone.utc).date().isoformat()
        return dt.date.fromisoformat(str(v)[:10]).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _p(title, department="", location="", posted=None, url="", pid=""):
    return {"title": (title or "").strip()[:200], "department": (department or "").strip()[:80], "location": (location or "").strip()[:120],
            "posted_at": _date(posted), "url": url or "", "id": str(pid or "")}


# ---------------------------------------------------------------- ATS feeds
def _workday_date(text, today=None):
    """'Posted Today' / 'Posted Yesterday' / 'Posted 4 Days Ago' / 'Posted 30+ Days Ago' -> ISO date.
    30+ days is set to 31 days ago: older than the 30-day window, which is all the score needs."""
    today = today or dt.date.today()
    t = (text or "").lower()
    if "today" in t:
        return today.isoformat()
    if "yesterday" in t:
        return (today - dt.timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)(\+)?\s*days?", t)
    if m:
        return (today - dt.timedelta(days=31 if m.group(2) else int(m.group(1)))).isoformat()
    return None


def _dmy(text):
    """'27th October, 2026' -> '2026-10-27'."""
    try:
        return dt.datetime.strptime(re.sub(r"(\d+)(st|nd|rd|th)", r"\1", (text or "").replace(",", "")).strip(), "%d %B %Y").date().isoformat()
    except ValueError:
        return None


MAX_PAGES = 10          # paged feeds (Workday, UltiPro): at most 10 pages of 20-50 roles


def read_ats(name, board):
    """Open roles from an ATS feed, as a list of posting dicts. Raises http.FetchError."""
    feed = next(f for n, _, f in ATS_RX if n == name)
    url = feed.format(*board.split("|"))
    if name == "workday":
        tenant, wd, site = board.split("|")
        out, total = [], None
        for page in range(MAX_PAGES):
            d = http.post(url, json={"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": ""}, interval=1.0, retries=1).json()
            total = d.get("total") if total is None else total
            jobs = d.get("jobPostings") or []
            out += [_p(j.get("title"), "", j.get("locationsText"), _workday_date(j.get("postedOn")),
                       f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{j.get('externalPath', '')}", (j.get("bulletFields") or [""])[0])
                    for j in jobs]
            if not jobs or len(out) >= (total or 0):
                break
        return out
    if name == "ultipro":
        out = []
        for page in range(MAX_PAGES):
            d = http.post(url, json={"opportunitySearch": {"Top": 50, "Skip": page * 50, "QueryString": "", "Filters": [],
                                                           "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}]}},
                          interval=1.0, retries=1).json()
            opps = d.get("opportunities") or []
            for o in opps:
                loc = (o.get("Locations") or [{}])[0]
                city = ((loc.get("Address") or {}).get("City")) or loc.get("LocalizedName") or ""
                out.append(_p(o.get("Title"), o.get("JobCategoryName"), city, o.get("PostedDate"),
                              url.split("/JobBoardView")[0] + f"/OpportunityDetail?opportunityId={o.get('Id')}", o.get("Id")))
            if len(opps) < 50 or len(out) >= (d.get("totalCount") or 0):
                break
        return out
    r = http.get(url, interval=1.0, retries=1)
    if name == "paylocity":
        m = re.search(r"window\.pageData\s*=\s*(\{.*?\});\s*</script>", r.text, re.S)
        if not m:
            raise http.FetchError("paylocity page has no job data")
        return [_p(j.get("JobTitle"), j.get("HiringDepartment"), j.get("LocationName"), j.get("PublishedDate"),
                   f"https://recruiting.paylocity.com/Recruiting/Jobs/Details/{j.get('JobId')}", j.get("JobId"))
                for j in json.loads(m.group(1)).get("Jobs") or [] if not j.get("IsInternal")]
    if name == "jobadder":
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for it in soup.select(".job_items"):
            a = it.select_one("a.viewjob") or it.find("a", href=True)
            if not a:
                continue
            facts = [li.get_text(" ", strip=True) for li in it.select("ul.list li")]
            out.append(_p(a.get_text(" ", strip=True), facts[0] if facts else "", facts[2] if len(facts) > 2 else "",
                          _dmy(it.select_one("sub").get_text(" ", strip=True) if it.select_one("sub") else ""),
                          urljoin(r.url, a["href"]), a["href"].rstrip("/").split("/")[-2]))
        return out
    if name == "teamtailor":
        root = ET.fromstring(r.content)
        return [_p(i.findtext("title"), "", "", _rss_date(i.findtext("pubDate")), i.findtext("link"), i.findtext("guid") or i.findtext("link"))
                for i in root.iter("item")]
    if name == "personio":
        root = ET.fromstring(r.content)
        return [_p(p.findtext("name"), p.findtext("department"), p.findtext("office"), p.findtext("createdAt"), "", p.findtext("id"))
                for p in root.iter("position")]
    d = r.json()
    if name == "greenhouse":
        return [_p(j.get("title"), ", ".join(x.get("name", "") for x in j.get("departments") or []), (j.get("location") or {}).get("name"),
                   j.get("first_published") or j.get("updated_at"), j.get("absolute_url"), j.get("id")) for j in d.get("jobs", [])]
    if name == "lever":
        return [_p(j.get("text"), (j.get("categories") or {}).get("department") or (j.get("categories") or {}).get("team"),
                   (j.get("categories") or {}).get("location"), j.get("createdAt"), j.get("hostedUrl"), j.get("id")) for j in d]
    if name == "ashby":
        return [_p(j.get("title"), j.get("department") or j.get("team"), j.get("location"), j.get("publishedAt"), j.get("jobUrl"), j.get("id"))
                for j in d.get("jobs", []) if j.get("isListed", True)]
    if name == "workable":
        return [_p(j.get("title"), j.get("department"), ", ".join(x for x in [j.get("city"), j.get("country")] if x),
                   j.get("published_on") or j.get("created_at"), j.get("url") or j.get("shortlink"), j.get("shortcode")) for j in d.get("jobs", [])]
    if name == "smartrecruiters":
        return [_p(j.get("name"), (j.get("department") or {}).get("label"), (j.get("location") or {}).get("city"), j.get("releasedDate"),
                   f"https://jobs.smartrecruiters.com/{board}/{j.get('id')}", j.get("id")) for j in d.get("content", [])]
    if name == "bamboohr":
        return [_p(j.get("jobOpeningName"), j.get("departmentLabel"), (j.get("location") or {}).get("city"), None,
                   f"https://{board}.bamboohr.com/careers/{j.get('id')}", j.get("id")) for j in d.get("result", [])]
    if name == "recruitee":
        return [_p(j.get("title"), j.get("department"), j.get("city") or j.get("location"), j.get("published_at") or j.get("created_at"),
                   j.get("careers_url"), j.get("id")) for j in d.get("offers", [])]
    if name == "rippling":
        return [_p(j.get("name"), (j.get("department") or {}).get("label"), (j.get("workLocation") or {}).get("label"), None,
                   j.get("url"), j.get("uuid")) for j in (d if isinstance(d, list) else d.get("items") or [])]
    if name == "pinpoint":
        return [_p(j.get("title"), ((j.get("job") or {}).get("department") or {}).get("name"), (j.get("location") or {}).get("name"), None,
                   j.get("url"), j.get("id")) for j in d.get("data", [])]
    if name == "breezy":
        return [_p(j.get("name"), (j.get("department") or ""), (j.get("location") or {}).get("name"), j.get("published_date"),
                   j.get("url"), j.get("id")) for j in d]
    return []


def _rss_date(v):
    try:
        return email.utils.parsedate_to_datetime(v).date().isoformat() if v else None
    except (TypeError, ValueError):
        return None


def find_ats(html):
    """[(ats name, board id)] found in a page's links, iframes and scripts."""
    found = []
    for name, rx, _ in ATS_RX:
        for m in rx.finditer(html or ""):
            board = "|".join(g.strip(".-") for g in m.groups())          # several parts for Workday and UltiPro
            if board.split("|")[0].lower() not in SKIP_IDS and (name, board) not in found:
                found.append((name, board))
    return found


# ---------------------------------------------------------------- schema.org JobPosting
def jobpostings(html, page_url):
    """JobPosting objects in a page's JSON-LD, still open (validThrough not passed)."""
    out, today = [], dt.date.today().isoformat()
    soup = BeautifulSoup(html or "", "html.parser")
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
                if isinstance(o.get("itemListElement"), list):
                    stack.extend(x.get("item", x) if isinstance(x, dict) else x for x in o["itemListElement"])
                t = o.get("@type", "")
                if "JobPosting" in (t if isinstance(t, list) else [t]):
                    until = _date(o.get("validThrough"))
                    if until and until < today:
                        continue
                    loc = o.get("jobLocation")
                    loc = loc[0] if isinstance(loc, list) and loc else loc
                    addr = (loc or {}).get("address") if isinstance(loc, dict) else None
                    city = addr.get("addressLocality", "") if isinstance(addr, dict) else ""
                    out.append(_p(o.get("title"), o.get("occupationalCategory") if isinstance(o.get("occupationalCategory"), str) else "",
                                  city, o.get("datePosted"), o.get("url") or page_url, o.get("identifier") if isinstance(o.get("identifier"), str) else ""))
    return out


# ---------------------------------------------------------------- one company
def _same_site(url, domain):
    host = urlparse(url).netloc.lower()
    return host == domain or host.endswith("." + domain)


def check_company(company):
    """Snapshot dict: status, method, careers_url, board_url, postings, note. Never raises."""
    snap = {"status": "", "method": "", "careers_url": "", "board_url": "", "postings": [], "note": ""}
    if not company.domain:
        snap["status"] = "no website"
        return snap
    domain = root_domain(company.domain)
    base = f"https://{domain}"
    try:
        if not _robots_ok(base, base + "/"):
            snap["status"] = "blocked by robots.txt"
            return snap
        home = http.get(base, interval=1.0, retries=1)
    except http.FetchError as e:
        snap["status"] = f"site unreachable: {http.reason(e)}"
        return snap
    pages = [(home.url, home.text)]
    soup = BeautifulSoup(home.text, "html.parser")
    links = [(urljoin(home.url, a["href"]), a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)]
    # a careers link: short link text that names careers ("Careers", "Join our team"), or a URL with a careers path segment
    careers = [u for u, t in links if ((len(t) <= 40 and CAREER_TEXT.search(t)) or _careerish(u))
               and (_same_site(u, domain) or any(rx.search(u) for _, rx, _ in ATS_RX) or _job_system(u))
               and not _is_home(u, home.url)]
    careers = list(dict.fromkeys(careers))
    candidates = careers[:2] or [base + p for p in CAREER_PATHS]
    for url in candidates:
        if any(rx.search(url) for _, rx, _ in ATS_RX):          # the careers link goes straight to the ATS
            snap["careers_url"] = url
            pages.append((url, url))
            break
        if _job_system(url):                                    # a job system without a feed: the browser pass renders it
            snap["careers_url"] = url
            pages.append((url, url))
            break
        if not _robots_ok(base, url):
            continue
        try:
            r = http.get(url, interval=1.0, retries=0)
        except http.FetchError:
            continue
        # a redirect to the home page, or to a page that isn't about careers (WordPress sends an unknown /careers to the
        # closest-sounding post), is not a careers page
        if _is_home(r.url, home.url) or (urlparse(r.url).path.rstrip("/") != urlparse(url).path.rstrip("/") and not _careerish(r.url)):
            continue
        snap["careers_url"] = r.url
        pages.append((r.url, r.text))
        # one more hop: a "View open roles" link from the careers page to a jobs page or the ATS
        sub = BeautifulSoup(r.text, "html.parser")
        more = [urljoin(r.url, a["href"]) for a in sub.find_all("a", href=True) if HOP_TEXT.search(a.get_text(" ", strip=True))]
        for m in more[:1]:
            if any(rx.search(m) for _, rx, _ in ATS_RX):
                pages.append((m, m))
            elif _same_site(m, domain) and m != r.url and _robots_ok(base, m):
                try:
                    r2 = http.get(m, interval=1.0, retries=0)
                    pages.append((r2.url, r2.text))
                except http.FetchError:
                    pass
        break

    # 1) an ATS with a public feed
    for url, html in pages:
        for name, board in find_ats(f"{url} {html}"):
            try:
                posts = read_ats(name, board)
            except (http.FetchError, ValueError, ET.ParseError) as e:
                snap["note"] = f"{name} '{board}' feed failed: {e}"[:200]
                continue
            snap.update(status="ok", method=f"ats:{name}", board_url=f"{name}:{board}", postings=posts)
            return snap
    # 2) JobPosting data on the careers page and the job pages it links to
    if snap["careers_url"] and len(pages) > 1:
        posts = []
        for url, html in pages[1:]:
            posts += jobpostings(html, url)
        if not posts:
            job_links = []
            for url, html in pages[1:]:
                s2 = BeautifulSoup(html, "html.parser")
                job_links += [urljoin(url, a["href"]) for a in s2.find_all("a", href=True)]
            job_links = [u for u in dict.fromkeys(job_links) if _same_site(u, domain) and JOB_PAGE.search(urlparse(u).path)
                         and urlparse(u).path.rstrip("/") != urlparse(snap["careers_url"]).path.rstrip("/")]
            for u in job_links[:MAX_JOB_PAGES]:
                if not _robots_ok(base, u):
                    continue
                try:
                    posts += jobpostings(http.get(u, interval=1.0, retries=0).text, u)
                except http.FetchError:
                    continue
        if posts:
            seen, uniq = set(), []
            for p in posts:
                k = (p["title"].lower(), p["location"].lower(), p["url"])
                if k not in seen:
                    seen.add(k)
                    uniq.append(p)
            snap.update(status="ok", method="jobposting", postings=uniq)
            return snap
    # 3) nothing readable: say what was seen
    blob = " ".join(f"{u} {h}" for u, h in pages)
    seen = [n for n, rx in NO_FEED_RX if rx.search(blob)]
    if seen:
        snap.update(status="not readable", method="seen: " + ", ".join(seen),
                    note="jobs are listed on a system or job board without a public feed")
    elif snap["careers_url"] and any(_NO_VAC_STRICT.search(BeautifulSoup(h, "html.parser").get_text(" ", strip=True)) for _, h in pages[1:]):
        snap.update(status="ok", method="careers page says no vacancies", postings=[],
                    note="the careers page says there are no open roles")
    elif snap["careers_url"]:
        snap.update(status="no roles found", method="careers page", note="careers page found, but no job feed or JobPosting data")
    else:
        snap.update(status="no careers page", method="")
    return snap


# ---------------------------------------------------------------- headless browser pass (JavaScript careers pages)
BOT_CHECK = re.compile(r"just a moment|challenges\.cloudflare\.com|cf-turnstile|captcha|access denied|attention required", re.I)
JUNK_TITLE = re.compile(r"^(apply( now)?|view( job| role| details)?|read more|learn more|more|details|jobs?|careers?|search|login|sign ?in|\d+)$", re.I)


def needs_browser(snap):
    """A careers page was found but nothing could be read from its plain HTML."""
    if not snap.get("careers_url"):
        return False
    if snap["status"] == "no roles found":
        return True
    # a job system without a feed: worth rendering, unless the only thing seen was a job board (SEEK, Indeed, LinkedIn)
    return snap["status"] == "not readable" and any(n.strip() not in JOB_BOARDS for n in snap["method"].replace("seen:", "").split(","))


def render(page, url, wait_ms=6000):
    """(final url, html of the page and its frames, URLs it requested, [(href, text)] links). Never raises past a page error."""
    reqs = []
    page.on("request", lambda r: reqs.append(r.url))
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=wait_ms)       # many sites never go fully idle: carry on after wait_ms
    except Exception:
        pass
    html, links = [], []
    for fr in page.frames:
        try:
            html.append(fr.content())
            links += fr.eval_on_selector_all("a[href]", "els => els.map(e => [e.href, (e.innerText || '').trim().slice(0, 200)])")
        except Exception:
            continue
    return page.url, "\n".join(html), reqs, links


def from_rendered(snap, company, final_url, html, reqs, links):
    """Re-run the feed / JobPosting checks on the rendered page, then job-system job links. Updates snap; True if roles found."""
    domain = root_domain(company.domain)
    base = f"https://{domain}"
    blob = f"{final_url} {html} {' '.join(reqs)} {' '.join(h for h, _ in links)}"
    for name, board in find_ats(blob):                                 # 1) a feed the plain HTML didn't show
        try:
            posts = read_ats(name, board)
        except (http.FetchError, ValueError, ET.ParseError):
            continue
        snap.update(status="ok", method=f"ats:{name} (rendered)", board_url=f"{name}:{board}", postings=posts, note="")
        return True
    posts = jobpostings(html, final_url)                               # 2) JobPosting data in the rendered page
    if not posts:                                                      # 3) job links on the company's own job system
        seen = {}
        for h, t in links:
            t = re.sub(r"\s+", " ", (t or "").strip().split("\n")[0]).strip()     # first line of a job card = the title
            if ATS_JOB_LINK.search(h) and 3 <= len(t) <= 120 and not JUNK_TITLE.match(t) and h not in seen:
                seen[h] = _p(t, "", "", None, h, h)
        posts = list(seen.values())
        if posts:
            snap.update(status="ok", method=f"job links on {urlparse(posts[0]['url']).netloc} (rendered)", postings=posts, note="")
            return True
    if not posts:                                                      # 4) same-site job pages the rendered page links to
        job_links = [h for h, _ in links if _same_site(h, domain) and JOB_PAGE.search(urlparse(h).path)
                     and urlparse(h).path.rstrip("/") != urlparse(final_url).path.rstrip("/")]
        for u in list(dict.fromkeys(job_links))[:MAX_JOB_PAGES]:
            if not _robots_ok(base, u):
                continue
            try:
                posts += jobpostings(http.get(u, interval=1.0, retries=0).text, u)
            except http.FetchError:
                continue
    if posts:
        uniq = list({(p["title"].lower(), p["location"].lower(), p["url"]): p for p in posts}.values())
        snap.update(status="ok", method="jobposting (rendered)", postings=uniq, note="")
        return True
    # 5) job links on the company's own careers site with a job id (careers.wipfli.com/jobs/tax/us/tax-manager/5455):
    #    the id keeps out pages like /careers/benefits. Only the list's first page is seen, so the count can be low.
    own = {}
    for h, t in links:
        h = h.split("#")[0]
        path = urlparse(h).path
        t = re.sub(r"\s+", " ", (t or "").strip().split("\n")[0]).strip()
        if (_same_site(h, domain) and OWN_JOB.search(path) and re.search(r"/\d{3,}(/|$|-)", path)
                and 3 <= len(t) <= 120 and not JUNK_TITLE.match(t) and h not in own):
            own[h] = _p(t, "", "", None, h, h)
    if len(own) >= 1:
        snap.update(status="ok", method="job links on own site (rendered)", postings=list(own.values()),
                    note="counted from the job list's first page: there may be more")
        return True
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if BOT_CHECK.search(html[:20000]) and len(text) < 2000:
        snap["note"] = "rendered: the page shows a bot check, not read"
    elif _NO_VAC_STRICT.search(text):
        snap.update(status="ok", method="careers page says no vacancies (rendered)", postings=[], note="the careers page says there are no open roles")
        return True
    else:
        snap["note"] = (snap["note"] + "; " if snap["note"] else "") + "rendered in a browser: no job list found"
    return False


def browser_pass(todo, log=print):
    """todo: [(company, snap)]. Renders each careers page in headless Chromium, one at a time. Needs the `browser` dependency
    group and `python -m playwright install chromium`; without them the pass is skipped with a note."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("  playwright not installed: browser pass skipped (uv sync, then python -m playwright install chromium)")
        return Counter()
    found = Counter()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=http.UA, locale="en-AU")
        for i, (c, snap) in enumerate(todo, 1):
            u = snap["careers_url"]
            if not _robots_ok(f"https://{urlparse(u).netloc}", u):
                snap["note"] = "rendered: blocked by robots.txt"
                found[False] += 1
                continue
            page = ctx.new_page()
            try:
                final, html, reqs, links = render(page, u)
                ok = from_rendered(snap, c, final, html, reqs, links)
                # nothing on the landing page: follow one "Open positions" / "Search jobs" link and look again
                hop = next((h for h, t in links if HOP_TEXT.search(t or "") and h.split("#")[0].rstrip("/") != final.rstrip("/")
                            and (_same_site(h, root_domain(c.domain)) or _job_system(h) or any(rx.search(h) for _, rx, _ in ATS_RX))), None)
                if not ok and hop and _robots_ok(f"https://{urlparse(hop).netloc}", hop):
                    ok = from_rendered(snap, c, *render(page, hop))
                found[ok] += 1
            except Exception as e:                              # a page that won't load must not stop the pass
                snap["note"] = f"rendered: {type(e).__name__}: {str(e)[:120]}"
                found[False] += 1
            finally:
                page.close()
            if i % 25 == 0 or i == len(todo):
                log(f"  browser {i}/{len(todo)} · roles or a real zero found for {found[True]}")
        browser.close()
    return found


# ---------------------------------------------------------------- store + run
def save(store, company_id, snap, now):
    posts = snap["postings"]
    today = now.date()
    dated = [p for p in posts if p["posted_at"]]
    n30 = sum((today - dt.date.fromisoformat(p["posted_at"])).days <= 30 for p in dated)
    depts = Counter(p["department"] or "Other" for p in posts)
    stamp = now.isoformat(timespec="seconds")
    with store.lock, store.db:
        store.db.execute("INSERT OR REPLACE INTO job_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (company_id, stamp, snap["status"], snap["method"], snap["careers_url"], snap["board_url"],
                          len(posts) if snap["status"] == "ok" else None, n30 if snap["status"] == "ok" else None, len(dated),
                          json.dumps(dict(depts.most_common()), ensure_ascii=False), snap["note"]))
        for p in posts:
            key = p["id"] or p["url"] or f"{p['title']}|{p['location']}"
            store.db.execute("""INSERT INTO job_postings VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(company_id, posting_key) DO UPDATE SET title=excluded.title, department=excluded.department,
                location=excluded.location, posted_at=COALESCE(excluded.posted_at, job_postings.posted_at), url=excluded.url,
                last_seen=excluded.last_seen""",
                             (company_id, key[:300], p["title"], p["department"], p["location"], p["posted_at"], p["url"], stamp, stamp))


def run_jobs(companies, db_path, workers=6, log=print, browser=True):
    from cloudstaff_dev.signals.store import Store
    store = Store(db_path)
    ensure_tables(store)
    for c in companies:
        store.upsert_company(c)
    now = dt.datetime.now(dt.timezone.utc)
    log(f"Checking careers pages for {len(companies)} companies · {workers} workers")
    status, snaps = Counter(), []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(check_company, c): c for c in companies}
        for i, f in enumerate(as_completed(futs), 1):
            c = futs[f]
            try:
                snap = f.result()
            except Exception as e:                       # one bad page must not stop the run
                snap = {"status": "check failed", "method": "", "careers_url": "", "board_url": "", "postings": [],
                        "note": f"{type(e).__name__}: {e}"[:200]}
            snaps.append((c, snap))
            status[snap["status"].split(":")[0]] += 1
            if i % 25 == 0 or i == len(companies):
                log(f"  {i}/{len(companies)} companies · {dict(status)}")
    todo = [(c, s) for c, s in snaps if needs_browser(s)]
    if browser and todo:
        log(f"Rendering {len(todo)} careers pages that showed no jobs in plain HTML (headless Chromium)")
        browser_pass(todo, log)
        status = Counter(s["status"].split(":")[0] for _, s in snaps)
        log(f"  after the browser pass · {dict(status)}")
    for c, snap in snaps:
        save(store, c.company_id, snap, now)
    methods = Counter(r[0] for r in store.db.execute("SELECT method FROM job_snapshots WHERE checked_at=?", (now.isoformat(timespec='seconds'),)))
    log("Methods: " + " · ".join(f"{m or '-'} {n}" for m, n in methods.most_common()))
    return status


# ---------------------------------------------------------------- export
SPIKE_MIN_DAYS, SPIKE_MAX_DAYS = 21, 120     # compare with a snapshot this old
SPIKE_RATIO, SPIKE_MIN_ADDED = 1.5, 3        # at least 1.5x and +3 roles


def job_rows(store, company_id, today):
    """(summary fields, events) for one company from its latest snapshot."""
    ensure_tables(store)
    snaps = store.db.execute("SELECT checked_at, status, method, careers_url, board_url, n_open, n_30d, n_dated, departments, note "
                             "FROM job_snapshots WHERE company_id=? ORDER BY checked_at DESC", (company_id,)).fetchall()
    if not snaps:
        return {"jobs_status": "not checked"}, []
    checked, status, method, careers, board, n_open, n30, n_dated, depts, note = snaps[0]
    status = http.tidy_status(status)
    fields = {"jobs_status": status, "jobs_method": method, "careers_url": careers or "", "open_roles": n_open if n_open is not None else ""}
    if status != "ok":
        # unknown, not zero: many careers pages load their roles with JavaScript, which a plain fetch can't see.
        # Only a job feed that lists no roles (status ok, 0 open) is a real zero.
        fields["job_postings_30d"] = ""
        return fields, []
    # job_postings_30d: roles posted in the last 30 days when the feed gives dates, else all open roles
    fields["job_postings_30d"] = n30 if n_dated and n_dated >= max(1, n_open // 2) else n_open
    fields["jobs_dates_known"] = "yes" if n_dated and n_dated >= max(1, n_open // 2) else "no"
    when = dt.datetime.fromisoformat(checked)
    earlier = [s for s in snaps[1:] if s[1] == "ok" and SPIKE_MIN_DAYS <= (when - dt.datetime.fromisoformat(s[0])).days <= SPIKE_MAX_DAYS]
    spike = ""
    if earlier:
        prev = earlier[0][5] or 0
        spike = "Yes" if n_open >= max(prev * SPIKE_RATIO, prev + SPIKE_MIN_ADDED) else "No"
        fields["open_roles_before"] = prev
    fields["hiring_spike"] = spike
    d = json.loads(depts or "{}")
    top = ", ".join(f"{k} {v}" for k, v in list(d.items())[:4])
    title = f"{n_open} open role{'s' if n_open != 1 else ''}" + (f" ({top})" if top and n_open else "") + \
            (f", {n30} posted in the last 30 days" if fields["jobs_dates_known"] == "yes" else "") + \
            (" (hiring spike: up from " + str(fields['open_roles_before']) + ")" if spike == "Yes" else "")
    ev = {"signal_type": "jobs", "category": "Hiring spike" if spike == "Yes" else ("Hiring" if n_open else "No open roles"),
          "published_at": checked[:10], "title": title, "publisher": method.replace("ats:", "") + " (careers page)",
          "url": careers or board or "", "source": "jobs", "evidence": "company's own careers page", "count": n_open}
    return fields, [ev]
