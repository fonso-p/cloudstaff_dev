"""Name, domain and text helpers shared across the scraper (search queries, company cards, registers, jobs, matching).

No matching decisions live here: "is this article about the company?" is identity.py.
"""
import re
from urllib.parse import urlparse

LEGAL = re.compile(r"\b(pty|pte|ltd|limited|inc|incorporated|llc|llp|plc|corp|corporation|co|company|gmbh|ag|sa|nv|bv)\b\.?", re.I)
NUMBERED = re.compile(r"^\s*(a\.?\s?c\.?\s?n\.?\s*)?[\d\s]{5,}", re.I)     # "12768640 CANADA INC.", "A.C.N. 633 889 433 Pty Ltd"
ENGLISH = {"the", "and", "of", "to", "in", "a", "is", "for", "that", "on", "with", "as", "it", "its", "by", "was", "are", "has", "have", "from", "will", "this", "at", "be"}
ENGLISH_MIN_WORDS, ENGLISH_MIN_SHARE = 60, 0.08
# social and video posts are not news (Nepali cricket videos matched "Boundaryline")
SOCIAL = {"instagram", "facebook", "linkedin", "tiktok", "youtube", "x", "x.com", "twitter", "threads", "reddit", "pinterest"}


def core_name(name):
    """'Orchard Medical Pty Ltd' -> 'Orchard Medical'."""
    n = LEGAL.sub(" ", name.replace(",", " ").replace("&amp;", "&"))
    return re.sub(r"\s+", " ", n).strip(" .-") or name.strip()


def root_domain(domain):
    """'https://www.xero.com/au/' -> 'xero.com'."""
    if not domain:
        return ""
    d = domain.lower().strip()
    d = urlparse(d if "//" in d else "//" + d).netloc or d
    return d.removeprefix("www.").split(":")[0]


def name_pattern(term):
    """Case-insensitive whole-word pattern; search it against lowercased text."""
    return re.compile(r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])")


def not_english(text):
    """True when a long enough text has almost none of the commonest English words (checked on the first 3,000 characters)."""
    words = re.findall(r"[a-z']+", (text or "").lower()[:3000])
    return len(words) >= ENGLISH_MIN_WORDS and sum(w in ENGLISH for w in words) / len(words) < ENGLISH_MIN_SHARE
