"""HTTP for the article reader: per-host rate limit, robots.txt check, one session per thread.

Kept separate from news_scraper.http on purpose, so this package works on its own.
"""
import random
import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
ROBOTS_AGENT = "*"


class ReadError(Exception):
    def __init__(self, status, message=""):
        super().__init__(message or status)
        self.status = status


_lock = threading.Lock()
_next = {}
_robots = {}
_local = threading.local()


def _session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update({"User-Agent": UA, "Accept-Language": "en", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    return _local.s


def wait(host, interval):
    with _lock:
        now = time.monotonic()
        slot = max(now, _next.get(host, 0.0))
        _next[host] = slot + interval * random.uniform(1.0, 1.3)
    if slot > now:
        time.sleep(slot - now)


def allowed(url):
    """robots.txt check, cached per host. Unreadable robots.txt = allowed (the usual convention)."""
    p = urlparse(url)
    host = f"{p.scheme}://{p.netloc}"
    with _lock:
        rp = _robots.get(host)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = _session().get(host + "/robots.txt", timeout=10)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        with _lock:
            _robots[host] = rp
    return rp.can_fetch(ROBOTS_AGENT, url)


def get(url, interval=1.0, timeout=20, check_robots=True, **kw):
    if check_robots and not allowed(url):
        raise ReadError("blocked_robots", "robots.txt disallows this page")
    wait(urlparse(url).netloc, interval)
    try:
        r = _session().get(url, timeout=timeout, allow_redirects=True, **kw)
    except requests.RequestException as e:
        raise ReadError("http_error", f"{type(e).__name__}: {e}"[:200])
    if r.status_code != 200:
        raise ReadError("http_error", f"HTTP {r.status_code}")
    return r


def post(url, data, headers=None, interval=1.0, timeout=20):
    wait(urlparse(url).netloc, interval)
    try:
        r = _session().post(url, data=data, headers=headers or {}, timeout=timeout)
    except requests.RequestException as e:
        raise ReadError("http_error", f"{type(e).__name__}: {e}"[:200])
    if r.status_code != 200:
        raise ReadError("http_error", f"HTTP {r.status_code}")
    return r
