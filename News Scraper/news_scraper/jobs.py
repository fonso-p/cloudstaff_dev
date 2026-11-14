"""Job signals: how many roles a company is advertising, read from its own website. Keyless, matched by domain.

    python -m news_scraper jobs --companies companies.csv [--db data/news.db] [--workers 6] [--limit N]

For each company with a website (robots.txt respected):
  1. find the careers page: a link on the home page ("Careers", "Jobs", "Join us"…) or a common path (/careers, /jobs…)
  2. look on the careers page (and the home page) for an applicant tracking system (ATS) with a public job feed:
       Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR, Recruitee, Personio
     and read every open role from it (title, department, location, date posted)
  3. otherwise read schema.org JobPosting data (what Google for Jobs uses) from the careers page and the job pages it links to
  ATS without a public feed (JobAdder, Employment Hero, Workday…) and links to job boards (SEEK, Indeed, LinkedIn) are noted
  in `method` but not read.

Each run stores a snapshot (job_snapshots) and the roles seen (job_postings). Exported as one "Hiring" event per company in
signal_events.csv, plus open_roles / job_postings_30d / hiring_spike in company_summary.csv. A hiring spike needs an earlier
snapshot to compare with, so it is blank after the first run.
"""
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import http
from .match import root_domain
from .profile import _robots_ok

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
CAREER_TEXT = re.compile(r"\b(careers?|jobs?|join (us|our team|the team)|work (with|for) us|vacancies|opportunities|we'?re hiring|open (roles|positions))\b", re.I)
CAREER_PATHS = ["/careers", "/jobs", "/careers/", "/join-us", "/work-with-us", "/join-our-team", "/about/careers", "/company/careers", "/vacancies"]
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
]
ATS_RX = [(n, re.compile(p, re.I), feed) for n, p, feed in ATS]
SKIP_IDS = {"embed", "api", "v1", "jobs", "careers", "www", "app", "apply", "static", "assets", "js"}
# found but not readable without a key or a browser
NO_FEED = [("jobadder", r"jobadder\.com"), ("employment hero", r"(jobs|careers)\.employmenthero\.com|employmenthero\.com/jobs"),
           ("workday", r"myworkdayjobs\.com"), ("seek", r"seek\.com\.au|seek\.co\.nz"), ("indeed", r"indeed\.com"),
           ("linkedin jobs", r"linkedin\.com/(company/[^\"']+/jobs|jobs)"), ("breezy", r"breezy\.hr"), ("teamtailor", r"teamtailor\.com"),
           ("pageup", r"pageuppeople\.com"), ("livehire", r"livehire\.com"), ("jazzhr", r"applytojob\.com"), ("icims", r"icims\.com")]
NO_FEED_RX = [(n, re.compile(p, re.I)) for n, p in NO_FEED]
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
def read_ats(name, board):
    """Open roles from an ATS feed, as a list of posting dicts. Raises http.FetchError."""
    feed = next(f for n, _, f in ATS_RX if n == name)
    url = feed.format(board)
    r = http.get(url, interval=1.0, retries=1)
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
    return []


def find_ats(html):
    """[(ats name, board id)] found in a page's links, iframes and scripts."""
    found = []
    for name, rx, _ in ATS_RX:
        for m in rx.finditer(html or ""):
            board = m.group(1).strip(".-")
            if board.lower() not in SKIP_IDS and (name, board) not in found:
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
        snap["status"] = f"error: {e}"[:200]
        return snap
    pages = [(home.url, home.text)]
    soup = BeautifulSoup(home.text, "html.parser")
    links = [(urljoin(home.url, a["href"]), a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)]
    careers = [u for u, t in links if (CAREER_TEXT.search(t) or CAREER_TEXT.search(urlparse(u).path.replace("-", " ").replace("/", " ")))
               and (_same_site(u, domain) or any(rx.search(u) for _, rx, _ in ATS_RX))]
    careers = list(dict.fromkeys(careers))
    candidates = careers[:2] or [base + p for p in CAREER_PATHS]
    for url in candidates:
        if any(rx.search(url) for _, rx, _ in ATS_RX):          # the careers link goes straight to the ATS
            snap["careers_url"] = url
            pages.append((url, url))
            break
        if not _robots_ok(base, url):
            continue
        try:
            r = http.get(url, interval=1.0, retries=0)
        except http.FetchError:
            continue
        snap["careers_url"] = r.url
        pages.append((r.url, r.text))
        # one more hop: a "View open roles" link from the careers page to a jobs page or the ATS
        sub = BeautifulSoup(r.text, "html.parser")
        more = [urljoin(r.url, a["href"]) for a in sub.find_all("a", href=True)
                if re.search(r"(open (roles|positions)|view (all )?(jobs|roles|positions|vacancies)|current (openings|vacancies|opportunities)|see (all )?(jobs|roles))",
                             a.get_text(" ", strip=True), re.I)]
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


def run_jobs(companies, db_path, workers=6, log=print):
    from .store import Store
    store = Store(db_path)
    ensure_tables(store)
    for c in companies:
        store.upsert_company(c)
    now = dt.datetime.now(dt.timezone.utc)
    log(f"Checking careers pages for {len(companies)} companies · {workers} workers")
    status = Counter()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(check_company, c): c for c in companies}
        for i, f in enumerate(as_completed(futs), 1):
            c = futs[f]
            try:
                snap = f.result()
            except Exception as e:                       # one bad page must not stop the run
                snap = {"status": f"error: {e}"[:200], "method": "", "careers_url": "", "board_url": "", "postings": [], "note": ""}
            save(store, c.company_id, snap, now)
            status[snap["status"].split(":")[0]] += 1
            if i % 25 == 0 or i == len(companies):
                log(f"  {i}/{len(companies)} companies · {dict(status)}")
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
