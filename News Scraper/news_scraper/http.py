"""Polite HTTP: one requests session per thread, a per-host rate limit, and retries with backoff."""
import datetime as dt
import email.utils
import random
import re
import threading
import time
from urllib.parse import urlparse

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


class RateLimiter:
    """At most one request per `interval` seconds for each key (normally the host), across all threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next = {}

    def wait(self, key, interval):
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next.get(key, 0.0))
            self._next[key] = slot + interval
        if slot > now:
            time.sleep(slot - now)

    def push(self, key, interval):
        """Next request for key no earlier than `interval` seconds from now (never brings an existing slot forward)."""
        with self._lock:
            self._next[key] = max(self._next.get(key, 0.0), time.monotonic() + interval)


LIMITER = RateLimiter()
_local = threading.local()
_serial = {}                      # key -> lock, for hosts that allow only one request in flight (GDELT)
_serial_guard = threading.Lock()


def _serial_lock(key):
    with _serial_guard:
        return _serial.setdefault(key, threading.Lock())


def _session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return _local.s


def get(url, params=None, key=None, interval=1.0, timeout=25, retries=3, serial=False, method="GET", json=None):
    """GET (or `method`, with a `json` body) with a per-key rate limit. Retries 429/5xx and network errors with exponential backoff.
    serial=True: one request in flight for the key, and `interval` counts from when the last one finished."""
    key = key or urlparse(url).netloc
    err = None
    for attempt in range(retries + 1):
        try:
            if serial:
                with _serial_lock(key):
                    LIMITER.wait(key, 0)                   # wait until `interval` after the previous request finished
                    try:
                        r = _session().request(method, url, params=params, json=json, timeout=timeout)
                    finally:
                        LIMITER.push(key, interval * random.uniform(1.0, 1.2))
            else:
                LIMITER.wait(key, interval * random.uniform(1.0, 1.3))
                r = _session().request(method, url, params=params, json=json, timeout=timeout)
        except requests.RequestException as e:
            if _permanent(e):                              # a bad certificate or a missing domain fails the same way every time
                raise FetchError(str(e)) from e
            err, wait = e, None
        else:
            if r.status_code == 200:
                return r
            if r.status_code not in RETRY_STATUS:
                raise FetchError(f"HTTP {r.status_code} for {r.url[:120]}")
            err, wait = FetchError(f"HTTP {r.status_code}: {r.text[:120]}"), _retry_after(r)
            if wait is not None and wait > MAX_RETRY_AFTER:  # asked to come back much later: give up rather than hold a worker
                raise FetchError(f"HTTP {r.status_code} for {r.url[:120]} (asked to wait {wait:.0f}s)")
        if attempt < retries:
            # back off on the whole host, not just this thread: the next request for `key` from any thread waits too
            LIMITER.push(key, wait if wait is not None else min(90, interval * 2 * 2 ** attempt))
    raise FetchError(str(err))


MAX_RETRY_AFTER = 120             # seconds; a longer Retry-After means "not today"
_PERMANENT = re.compile(r"NameResolution|Failed to resolve|getaddrinfo|Name or service not known|nodename nor servname", re.I)


def _permanent(e):
    """Network errors a retry can't fix."""
    if isinstance(e, (requests.exceptions.SSLError, requests.exceptions.TooManyRedirects, requests.exceptions.InvalidURL,
                      requests.exceptions.MissingSchema, requests.exceptions.InvalidSchema)):
        return True
    return isinstance(e, requests.exceptions.ConnectionError) and bool(_PERMANENT.search(str(e)))


def _retry_after(r):
    """Seconds from a Retry-After header (a number or an HTTP date), or None."""
    v = (r.headers.get("Retry-After") or "").strip()
    if not v:
        return None
    if v.isdigit():
        return float(v)
    try:
        when = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())


_REASONS = [                      # (pattern in the requests/urllib3 message, short reason for people)
    (re.compile(r"CERTIFICATE_VERIFY_FAILED|SSLError|SSL:|certificate", re.I), "SSL certificate problem"),
    (re.compile(r"NameResolution|Failed to resolve|getaddrinfo|Name or service not known|nodename nor servname", re.I), "domain not found"),
    (re.compile(r"timed out|Timeout", re.I), "timed out"),
    (re.compile(r"TooManyRedirects|Exceeded \d+ redirects", re.I), "redirect loop"),
    (re.compile(r"refused|reset|aborted|RemoteDisconnected|ConnectionError|Max retries", re.I), "connection failed"),
]


def reason(err):
    """A short, readable reason for a failed fetch ('SSL certificate problem', 'HTTP 403'), never the raw traceback text."""
    msg = str(err)
    m = re.search(r"HTTP (\d{3})", msg)
    if m:
        return f"HTTP {m.group(1)}"
    return next((r for rx, r in _REASONS if rx.search(msg)), "could not load")


def tidy_status(status):
    """'error: HTTPSConnectionPool(...)' -> 'site unreachable: SSL certificate problem'. Other statuses pass through,
    so snapshots stored before this existed export cleanly too."""
    if isinstance(status, str) and status.startswith("error:"):
        return f"site unreachable: {reason(status)}"
    return status


def post(url, json=None, **kw):
    """POST a JSON body, with the same rate limit and retries as get()."""
    return get(url, method="POST", json=json, **kw)
