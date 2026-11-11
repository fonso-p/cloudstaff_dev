"""read_article(url) -> ReadResult. Never raises: every failure comes back as a status, so a caller can record it."""
import time
from dataclasses import asdict, dataclass

from . import google_news
from .extract import extract
from .fetch import ReadError, get

MIN_CHARS = 300          # less than this is usually a paywall, a cookie wall or a JavaScript-only page
MAX_CHARS = 40000


@dataclass
class ReadResult:
    url: str                 # the URL asked for
    final_url: str = ""      # the publisher's URL (after decoding Google News links and redirects)
    status: str = ""         # ok | too_short | blocked_robots | http_error | not_html | decode_failed | error
    method: str = ""         # jsonld | paragraphs | meta
    title: str = ""
    published: str = ""
    author: str = ""
    text: str = ""
    chars: int = 0
    seconds: float = 0.0
    error: str = ""

    def to_dict(self):
        return asdict(self)


def read_article(url, interval=1.0, respect_robots=True):
    t0 = time.time()
    res = ReadResult(url=url)
    try:
        real = google_news.decode(url) if google_news.is_google_news(url) else url
        res.final_url = real
        r = get(real, interval=interval, check_robots=respect_robots)
        res.final_url = r.url
        if "html" not in r.headers.get("content-type", "html").lower():
            raise ReadError("not_html", r.headers.get("content-type", ""))
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
        x = extract(r.text)
        res.title, res.published, res.author, res.method = x["title"], str(x["published"] or ""), x["author"] or "", x["method"]
        res.text = (x["text"] or "")[:MAX_CHARS]
        res.chars = len(res.text)
        res.status = "ok" if res.chars >= MIN_CHARS else "too_short"
    except ReadError as e:
        res.status, res.error = e.status, str(e)
    except Exception as e:                      # a broken page must not stop a batch
        res.status, res.error = "error", f"{type(e).__name__}: {e}"[:200]
    res.seconds = round(time.time() - t0, 2)
    return res
