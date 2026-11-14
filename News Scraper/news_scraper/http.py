"""Polite HTTP: one requests session per thread, a per-host rate limit, and retries with backoff."""
import random
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
        """Next request for key no earlier than `interval` seconds from now."""
        with self._lock:
            self._next[key] = time.monotonic() + interval


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


def get(url, params=None, key=None, interval=1.0, timeout=25, retries=3, serial=False):
    """GET with a per-key rate limit. Retries 429/5xx and network errors with exponential backoff.
    serial=True: one request in flight for the key, and `interval` counts from when the last one finished."""
    key = key or urlparse(url).netloc
    err = None
    for attempt in range(retries + 1):
        try:
            if serial:
                with _serial_lock(key):
                    LIMITER.wait(key, 0)                   # wait until `interval` after the previous request finished
                    try:
                        r = _session().get(url, params=params, timeout=timeout)
                    finally:
                        LIMITER.push(key, interval * random.uniform(1.0, 1.2))
            else:
                LIMITER.wait(key, interval * random.uniform(1.0, 1.3))
                r = _session().get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            err = e
        else:
            if r.status_code == 200:
                return r
            if r.status_code not in RETRY_STATUS:
                raise FetchError(f"HTTP {r.status_code} for {r.url[:120]}")
            err = FetchError(f"HTTP {r.status_code}: {r.text[:120]}")
        if attempt < retries:
            time.sleep(min(90, interval * 2 * 2 ** attempt))
    raise FetchError(str(err))
