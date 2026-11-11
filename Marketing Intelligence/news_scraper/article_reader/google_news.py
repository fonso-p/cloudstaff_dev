"""Turn a Google News link (news.google.com/rss/articles/CBMi...) into the publisher's real URL.

Google News RSS links are not plain redirects: they open a JavaScript page. Older IDs contain the URL in
base64; newer ones have to be resolved through the same internal call the Google News page makes
(batchexecute "Fbv4je"). Unofficial: Google can change it, in which case the reader reports
status "decode_failed" and moves on.
"""
import base64
import json
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .fetch import ReadError, get, post

GN_ID = re.compile(r"news\.google\.com/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)")


def is_google_news(url):
    return bool(url and GN_ID.search(url))


def _from_base64(gid):
    """Older IDs: the URL is inside the base64 payload."""
    try:
        raw = base64.urlsafe_b64decode(gid + "=" * (-len(gid) % 4))
    except (ValueError, base64.binascii.Error):
        return None
    m = re.search(rb"https?://[\x21-\x7e]+", raw)
    if m and not raw.startswith(b"\x08\x13\x22\x00") and b"AU_yqL" not in raw[:12]:
        url = m.group(0).decode("ascii", "ignore")
        return re.split(r"[\x00-\x1f\xd2]", url)[0]
    return None


def decode(url):
    m = GN_ID.search(url or "")
    if not m:
        return url
    gid = m.group(1)
    direct = _from_base64(gid)
    if direct:
        return direct
    # newer IDs: read the signature and timestamp from the article page, then ask Google for the real URL
    page = get(f"https://news.google.com/rss/articles/{gid}", interval=1.2, check_robots=False)
    div = BeautifulSoup(page.text, "html.parser").select_one("c-wiz > div[jscontroller]")
    if div is None or not div.get("data-n-a-sg"):
        raise ReadError("decode_failed", "Google News page had no signature")
    sig, ts = div["data-n-a-sg"], div["data-n-a-ts"]
    inner = (f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
             f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{ts},"{sig}"]')
    payload = json.dumps([[["Fbv4je", inner, None, "generic"]]])
    r = post("https://news.google.com/_/DotsSplashUi/data/batchexecute", data="f.req=" + quote(payload),
             headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}, interval=1.2)
    try:
        body = json.loads(r.text.split("\n\n", 1)[1])[:-2]
        real = json.loads(body[0][2])[1]
    except (IndexError, ValueError, TypeError):
        raise ReadError("decode_failed", "unexpected batchexecute response")
    if not str(real).startswith("http"):
        raise ReadError("decode_failed", "no URL in response")
    return real
