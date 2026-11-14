"""Is an article about this company? A 0-1 match score from where the name, domain and location appear.

Rule-based for the POC (no budget for an LLM). Common names are the weak spot: an article about a different
"Orchard Medical" scores the same as one about ours unless the domain or location is mentioned. A local LLM
(e.g. Ollama) can re-check the unclear 0.4-0.7 band later without changing anything else.
"""
import re
from urllib.parse import urlparse

LEGAL = re.compile(r"\b(pty|pte|ltd|limited|inc|incorporated|llc|llp|plc|corp|corporation|co|company|gmbh|ag|sa|nv|bv)\b\.?", re.I)
ENGLISH = {"the", "and", "of", "to", "in", "a", "is", "for", "that", "on", "with", "as", "it", "its", "by", "was", "are", "has", "have", "from", "will", "this", "at", "be"}
MATCH = 0.6      # at or above: counted as about the company
POSSIBLE = 0.4   # between POSSIBLE and MATCH: kept, flagged for review


def core_name(name):
    """'Orchard Medical Pty Ltd' -> 'Orchard Medical'."""
    n = LEGAL.sub(" ", name.replace(",", " ").replace("&amp;", "&"))
    return re.sub(r"\s+", " ", n).strip(" .-") or name.strip()


# social and video posts are not news (Nepali cricket videos matched "Boundaryline")
SOCIAL = {"instagram", "facebook", "linkedin", "tiktok", "youtube", "x", "x.com", "twitter", "threads", "reddit", "pinterest"}
NUMBERED = re.compile(r"^\s*(a\.?\s?c\.?\s?n\.?\s*)?[\d\s]{5,}", re.I)     # "12768640 CANADA INC.", "A.C.N. 633 889 433 Pty Ltd"
# too many articles for a small company, and too few of them confirm it: the name is a common word ("Clutch", clutch.co)
VOLUME_MIN, VOLUME_CONFIRMED = 15, 0.2
# the one-word and volume rules are for small companies only: Canva, Xero and Octopus Energy get lots of news whose
# headlines rarely carry a domain or city. Unknown size or a ticker = treated as not small.
SMALL_COMPANY = 1000


def auto_ambiguous(name, domain):
    """Why a name should be treated as common when the CSV doesn't say (spot checks on 100 Priority List companies):
    numbered companies, names of 3 characters or fewer ("ARG"), and one-word names that aren't the website's own name
    ("Clancy" at clancycorp.com.au, "Array" at arraynetworks.com, "Barga" at caesars.net.au). '' = distinctive."""
    if NUMBERED.match(name or ""):
        return "numbered company"
    core = core_name(name or "")
    if len(re.sub(r"[\W_]", "", core)) <= 3:
        return "short name"
    words = re.findall(r"[A-Za-z0-9&']+", core)
    label = re.sub(r"[^a-z0-9]", "", root_domain(domain).split(".")[0]) if domain else ""
    if len(words) == 1 and label and words[0].lower() != label:      # no website: nothing to compare, left as distinctive
        return "one-word name that is not the website's name"
    return ""


def root_domain(domain):
    if not domain:
        return ""
    d = domain.lower().strip()
    d = urlparse(d if "//" in d else "//" + d).netloc or d
    return d.removeprefix("www.").split(":")[0]


def _pat(term):
    return re.compile(r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])")


CONFIRM = 2      # identity points needed to confirm the company (see Matcher.evidence)
# words that, right after a common-word name, show it is a job title and not the company: "Deputy Mayor", "Summit Chair"
ROLE = (r"(mayor|minister|secretary|director|chief|governor|sheriff|commissioner|pm|cm|fm|dg|premier|speaker|president|chair(man|woman)?|"
        r"head|principal|commander|inspector|superintendent|registrar|editor|general|attorney|king|queen|prime|vice|ceo|cfo|coo|cto|marshal|"
        r"warden|clerk|coach|captain|consul|ambassador|police|constable|officer|lieutenant|administrator|controller|treasurer|whip|leader|"
        r"chancellor|judge|prosecutor|ombudsman|registrar|manager|managing|national|state|district|county|city)")
VS = r"(?:[Vv][Ss]\.?|[Vv]ersus)"                    # "vs", "Vs.", "versus" (case-sensitive elsewhere, so [A-Z] means a capital)


class Matcher:
    """Two jobs:
    score()   - at scrape time, a quick 0-1 score from the headline/summary (decides what is stored).
    verdict() - at export, whether an article counts, using identity evidence from the company card and the CSV.

    Identity evidence (points):  domain, ticker, legal/alt name, founder or executive = 2 each (strong)
                                 a CSV context word = 2 (chosen by a person) · each card keyword phrase = 1
                                 card single words = 1 in total · city/country = 1
    CONFIRM (2) points confirm the company.
    """

    def __init__(self, company, card=None):
        card = card or {}
        name = core_name(company.name)
        self.name = name
        self.names = [_pat(n) for n in {name, *company.aliases} if len(n) >= 2]
        self.domain = root_domain(company.domain)
        self.places = [_pat(p) for p in company.places + company.context if len(p) >= 2]   # score(): location and context words, a small boost
        self.context = [_pat(p) for p in company.context if len(p) >= 2]
        strong = [core_name(n) for n in [card.get("legal_name", ""), *card.get("alt_names", []), *card.get("people", [])]   # without "Pty Ltd"
                  if n and core_name(n).lower() != name.lower() and len(core_name(n)) >= 4]
        self.strong = [(n, _pat(n)) for n in dict.fromkeys(strong)]
        t = (company.ticker or card.get("ticker") or "").upper().split(":")[-1].strip()
        self.ticker = re.compile(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])") if len(t) >= 3 else None   # case-sensitive: "TEAM" not "team"
        self.listed = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in {name, *company.aliases} if len(n) >= 2) +
                                 r")(?: (?:limited|ltd|inc|corp|corporation|co|company|plc|group|holdings)\.?)?\s*\((?:ASX|NZX|LSE|LON|NASDAQ|NYSE|TSX|OTCMKTS|SGX)\s?:\s?[A-Z0-9.]{1,6}\)",
                                 re.I)
        self.keywords = [(k, _pat(k)) for k in card.get("keywords", []) if not any(p.search(k.lower()) for p in self.names)]
        self.city = [_pat(p) for p in {*company.places, card.get("city", "")} if p and len(p) >= 2]
        # ambiguous name: set in the CSV, else assumed when context words were given (someone saw the name was common)
        # or detected (auto_ambiguous), or set at export when a name pulls in many unconfirmed articles (VOLUME_MIN)
        self.ambiguous_set = company.ambiguous is not None
        self.ambiguous_reason = ("set in the CSV" if self.ambiguous_set else "context words given" if company.context
                                 else auto_ambiguous(company.name, company.domain))
        self.ambiguous = company.ambiguous if self.ambiguous_set else bool(self.ambiguous_reason)
        # a one-word name, even the website's own ("Accora" at accora.care, "Atkar" at atkar.com.au), is often also a place,
        # surname or word: at least 1 point of identity evidence is needed (location, keyword, domain…)
        emp = getattr(company, "employees", None)
        self.small = emp is not None and emp < SMALL_COMPANY and not (company.ticker or card.get("ticker"))
        self.one_word = self.small and len(re.findall(r"[A-Za-z0-9&']+", name)) == 1 and not self.ambiguous_set
        # case-sensitive name forms ("Deputy"), to tell the company from the ordinary word ("deputy") or a title ("Deputy Mayor")
        self.cased = [re.compile(r"(?<![\w])" + re.escape(n) + r"(?![\w])") for n in {name, *company.aliases} if len(n) >= 2]
        self.as_title = [re.compile(r"(?<![\w])" + re.escape(n) + r"\s+" + ROLE + r"\b", re.I) for n in {name, *company.aliases} if len(n) >= 2]

    # ---------------------------------------------------------------- evidence
    def evidence(self, text):
        """(points, list of what was found) for identity evidence in a piece of text."""
        raw, low = text or "", (text or "").lower()
        found, pts = [], 0
        if self.domain and self.domain in low:
            found.append(f"domain {self.domain}"); pts += 2
        if self.ticker and self.ticker.search(raw):
            found.append("ticker"); pts += 2
        for n, p in self.strong:
            if p.search(low):
                found.append(n); pts += 2
                break
        ctx = [p.pattern for p in self.context if p.search(low)]
        if ctx:
            found.append("context word"); pts += 2
        kws = [k for k, p in self.keywords if p.search(low)]
        if kws:                                   # each phrase ("employee scheduling") = 1; single words together = at most 1
            found += [f"keyword {k}" for k in kws[:3]]
            pts += sum(" " in k for k in kws) + (1 if any(" " not in k for k in kws) else 0)
        if any(p.search(low) for p in self.city):
            found.append("location"); pts += 1
        if self.listed.search(raw):                # "Zip Co (ASX:ZIP)": the name itself, then an exchange ticker
            found.append("listed-company name"); pts += 2
        return pts, found

    def company_uses(self, raw, minus_titles=True):
        """How often the name appears as the company: capitalised as in the name, and (for ambiguous names) not followed
        by a job title. "Deputy CEO" is a title, but "Xero CEO" is Xero's CEO, so titles are only subtracted when asked.
        A strong identity term (legal name, alt name, domain, ticker) counts as a use too ("Deputechnologies appoints…")."""
        uses = sum(len(p.findall(raw)) for p in self.cased)
        titles = sum(len(p.findall(raw)) for p in self.as_title) if minus_titles else 0
        low = (raw or "").lower()
        strong = sum(len(p.findall(low)) for _, p in self.strong) + (low.count(self.domain) if self.domain else 0) \
            + (len(self.ticker.findall(raw)) if self.ticker else 0)
        return max(uses - titles, 0) + strong

    def wrong_case(self, raw):
        """The name is present, but never written the company's way: "ROKT" (an ETF ticker) for Rokt, "xero" for Xero.
        Ignored for headlines written in capitals, where case says nothing."""
        raw = raw or ""
        letters = [c for c in raw[:300] if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
            return False
        named = any(p.search(raw.lower()) for p in self.names)
        return named and self.company_uses(raw, minus_titles=False) == 0

    def passing_mention(self, title):
        """The headline lists or compares the company with others: "Adobe, Canva, CapCut…", "Adobe Express vs Canva"."""
        t = title or ""
        for p in self.cased:
            for m in p.finditer(t):
                before, after = t[max(0, m.start() - 40): m.start()], t[m.end(): m.end() + 40]
                # compared with another named product/company: "Adobe Express vs Canva", "Xero Vs. QuickBooks", "Canva alternatives"
                if re.search(r"[A-Z][\w.&'-]*\s+" + VS + r"\s*$", before) or re.match(r"\s+" + VS + r"\s+[A-Z]", after) \
                        or re.match(r"\s+alternatives?\b", after, re.I) or re.search(r"\balternatives? to\s*$", before, re.I):
                    return True
                # comma-joined to another capitalised name, with at least one more separator: a list of 3+
                adjacent = re.search(r"[A-Z][\w&.'-]*,\s*$", before) or re.match(r"\s*,\s*[A-Z]", after)
                if adjacent and len(re.findall(r",|\band\b|&|\+", before[-25:] + " " + after[:25])) >= 2:
                    return True
        return False

    @staticmethod
    def _solid(pts, found):
        """Identity points without the one that single website keywords give: for a one-word name a lone generic word
        is not confirmation ("designed" confirmed Kid Koala, "steam" confirmed immutable Linux)."""
        return pts - (1 if any(f.startswith("keyword ") and " " not in f[8:] for f in found) else 0)

    def passing_lexical(self, title):
        """The headline uses the company as a reference point, not as its subject: "Acme-backed start-up", "an Acme veteran",
        "like Acme", "the Acme tower". Returns the matched phrase or ''."""
        t = title or ""
        n = re.escape(self.name)
        for pat in (rf"{n}[- ]backed\b", rf"\bbacked by (the )?(\w+ ){{0,2}}{n}\b",
                    rf"\b{n} (veteran|alum|alumni|alumnus|couple|tower|central|williams|stake|account|integration|partner program)\b",
                    rf"\b(ex|former)[- ]{n} (exec|executive|engineer|employee|staffer|boss|chief)\b.*\b(joins|named|appointed|launches)\b",
                    rf"\b(like|replace[sd]?|replacing|without|open-source|compete with|alternative to|rival to) {n}\b"):
            m = re.search(pat, t, re.I)
            if m:
                return m.group(0)
        return ""

    def verdict(self, title, summary, source, text=None, extra=0):
        """(counts, reason if not, evidence found). text = the article text if it was read, else None.
        extra: identity points found elsewhere (e.g. NLP: the name is tagged as an organisation).

        Ambiguous names ("Deputy"): the name must be used as the company (not "Deputy Mayor" or "deputy"), and
        CONFIRM points of identity evidence are needed, from the text if read, else from the headline and summary.
        Distinctive names ("Atlassian"): a mention is enough, except a passing mention in a list or comparison,
        which needs the text (company named 2+ times) or CONFIRM points to count.
        """
        if source == "newsroom":
            return True, "", ["company's own website"]
        head = f"{title or ''} {summary or ''}"
        if text:
            body = f"{title or ''} {text}"
            words = re.findall(r"[a-z']+", body.lower()[:3000])
            if len(words) >= 60 and sum(w in ENGLISH for w in words) / len(words) < 0.08:
                return False, "article not in English", []
            pts, found = self.evidence(body)
            pts += extra
            named = any(p.search(body.lower()) for p in self.names) or (self.domain and self.domain in body.lower())
            if not named:
                return False, "company not named in the article text", found
            if self.ambiguous:
                if self.company_uses(body) == 0:
                    return False, "the name is only used as an ordinary word or job title (e.g. 'Deputy Mayor')", found
                if pts < CONFIRM:
                    return False, "common name, and nothing in the article text confirms it is this company", found
            elif self.wrong_case(body):
                return False, "the name only appears in a different case (e.g. the ticker 'ROKT' or the word 'xero')", found
            elif self.passing_mention(title) and self.company_uses(body, minus_titles=False) < 2 and pts < CONFIRM:
                return False, "passing mention: listed or compared with others, and barely mentioned in the text", found
            elif self.one_word and self._solid(pts, found) < 1:
                return False, "one-word name, and nothing in the article text confirms it is this company", found
            return True, "", found
        # not read (failed, paywalled, or reading switched off): stricter, the headline has to do the work
        pts, found = self.evidence(head)
        pts += extra
        if self.ambiguous:
            if self.company_uses(title or "") == 0:
                return False, "text not read: the name is only used as an ordinary word or job title (e.g. 'Deputy Mayor')", found
            if pts < CONFIRM:
                return False, "text not read: common name, and the headline does not confirm it is this company", found
            return True, "", found
        if self.wrong_case(title) and pts < CONFIRM:
            return False, "text not read: the name only appears in a different case (e.g. the ticker 'ROKT' or the word 'xero')", found
        if self.passing_mention(title) and pts < CONFIRM:
            return False, "text not read: passing mention (listed or compared with others)", found
        if self.one_word and self._solid(pts, found) < 1:
            return False, "text not read: one-word name, and the headline does not confirm it is this company", found
        return True, "", found

    # ---------------------------------------------------------------- quick score (scrape time)
    def score(self, title, summary, url, source):
        if source == "newsroom":
            return 1.0                                     # the company's own website
        title_l, text = (title or "").lower(), f"{title or ''} {summary or ''}".lower()
        s = 0.0
        if any(p.search(title_l) for p in self.names):
            s += 0.6
        elif any(p.search(text) for p in self.names):
            s += 0.4
        if (self.domain and (self.domain in text or root_domain(url) == self.domain)) or any(p.search(text) for _, p in self.strong) \
                or (self.ticker and self.ticker.search(f"{title or ''} {summary or ''}")):
            s += 0.3
        if any(p.search(text) for p in self.places) or any(p.search(text) for _, p in self.keywords):
            s += 0.15
        return round(min(s, 1.0), 2)
