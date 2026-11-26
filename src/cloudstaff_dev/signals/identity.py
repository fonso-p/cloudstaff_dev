"""Is an article about this company? Everything that decides it, in one place.

    ident = Identity(company, card)                   # once per company: names, domain, ticker, card evidence, name type
    ident.score(title, summary, url, source)          # at scrape time: quick 0-1 score, decides what is stored
    judge(ident, title=..., summary=..., source=..., score=..., text=..., nlp=..., recurring=...)   # at export: does it count?

judge() returns an IdentityResult: counts (bool), rule (which rule decided), reason (why not, for review.csv), evidence,
points, mentions, the NLP entity check and the combiner's probability. Rules run in this order; the first objection wins:

  0. company's own website (newsroom) ..... always counts
  1. name rules (match.py's old verdict), on the article text if read, else the headline + summary (stricter):
       not english, not named                  text read only
       name used as word, common name unconfirmed       ambiguous names ("Deputy"): used as the company + CONFIRM points
       wrong case, passing mention, one word unconfirmed   distinctive names
  2. NLP entity rules (when `nlp run` results exist): nlp compound, nlp longer name, nlp wrong type (if < CONFIRM points)
  3. passing phrase: "Acme-backed", "like Acme"   unless the text names the company PASSING_PHRASE_MENTIONS+ times
  4. match score below min_match
  5. trained combiner (`nlp train`): accepts at >= COMBINER_ACCEPT, rejects at <= COMBINER_REJECT; never accepts below min_match

Identity evidence (points):  domain, ticker, legal/alt name, founder or executive = 2 each (strong)
                             a CSV context word = 2 (chosen by a person) · each card keyword phrase = 1
                             card single words = 1 in total · city/country = 1 · "Zip Co (ASX:ZIP)" = 2

Rule-based for the POC (no budget for an LLM). Common names are the weak spot. Measure any change with
eval/eval_identity.py; the unit cases are in tests/test_identity.py.
"""
import copy
import re
from dataclasses import dataclass, field

from cloudstaff_dev.common.company_keys import NUMBERED, core_name, name_pattern, not_english, root_domain

# ================================================================ thresholds (tune against eval/eval_identity.py)
MATCH = 0.6                    # scrape-time score at or above: counted as about the company (export's default min_match)
POSSIBLE = 0.4                 # scrape-time score at or above: stored at all
CONFIRM = 2                    # identity points that confirm the company
SMALL_COMPANY = 1000           # employees below this (and no ticker) = small: one-word, volume and NLP type rules apply
PASSING_MENTION_USES = 2       # a listed/compared name counts anyway if the text uses it this many times
PASSING_PHRASE_MENTIONS = 3    # "Acme-backed" counts anyway if the text names the company this many times
# too many articles for a small company, and too few of them confirm it: the name is a common word ("Clutch", clutch.co)
VOLUME_MIN, VOLUME_CONFIRMED = 15, 0.2
VOLUME_MIN_READ = 5            # read articles needed before judging how many confirm the company
VOLUME_MAX_WORDS = 2           # "Bank of Sydney" is specific; "Clutch", "Big Post" are not
COMBINER_ACCEPT, COMBINER_REJECT = 0.7, 0.3

# words that, right after a common-word name, show it is a job title and not the company: "Deputy Mayor", "Summit Chair"
ROLE = (r"(mayor|minister|secretary|director|chief|governor|sheriff|commissioner|pm|cm|fm|dg|premier|speaker|president|chair(man|woman)?|"
        r"head|principal|commander|inspector|superintendent|registrar|editor|general|attorney|king|queen|prime|vice|ceo|cfo|coo|cto|marshal|"
        r"warden|clerk|coach|captain|consul|ambassador|police|constable|officer|lieutenant|administrator|controller|treasurer|whip|leader|"
        r"chancellor|judge|prosecutor|ombudsman|registrar|manager|managing|national|state|district|county|city)")
VS = r"(?:[Vv][Ss]\.?|[Vv]ersus)"                    # "vs", "Vs.", "versus" (case-sensitive elsewhere, so [A-Z] means a capital)

# ---- NLP entity check vocab
# another company's naming: "Array Technologies" is not "Array Inc.", "Clutch Security" is not "Clutch"
ORG_SUFFIX = {"technologies", "technology", "tech", "systems", "solutions", "networks", "security", "software", "labs", "capital", "partners",
              "ventures", "village", "estate", "estates", "park", "centre", "center", "hospital", "university", "college", "school", "church",
              "bank", "media", "entertainment", "studios", "games", "motors", "airlines", "energy", "mining", "resources", "pharmaceuticals",
              "therapeutics", "biosciences", "foods", "gmbh", "ag", "sa"}       # not ltd/inc/corp…: our own suffix is stripped (GENERIC_NAME_WORDS)
GENERIC_NAME_WORDS = {"the", "a", "an", "group", "team", "staff", "ceo", "cfo", "coo", "cto", "boss", "chief", "founder", "founders", "co-founder",
                      "shares", "stock", "stocks", "share", "ltd", "limited", "pty", "inc", "llc", "plc", "corp", "corporation", "co", "company",
                      "holdings", "australia", "australian", "uk", "us", "nz", "'s", "’s", "s", "and", "&", "of"}
# NER types that make a one-word name "something else". PRODUCT and WORK_OF_ART are left out on purpose: spaCy tags well-known
# brands (Xero, Canva) as products. And the type rules apply to small companies only (entity_check(strict=...)).
BAD_TYPES = {"PERSON": "a person", "GPE": "a place", "LOC": "a place", "FAC": "a building or place", "EVENT": "an event",
             "NORP": "a nationality or group", "DATE": "a date"}

# ---- why a name rule rejected: (article text read, text not read)
REASONS = {
    "not english": ("article not in English", None),
    "not named": ("company not named in the article text", None),
    "name used as word": ("the name is only used as an ordinary word or job title (e.g. 'Deputy Mayor')",
                          "text not read: the name is only used as an ordinary word or job title (e.g. 'Deputy Mayor')"),
    "common name unconfirmed": ("common name, and nothing in the article text confirms it is this company",
                                "text not read: common name, and the headline does not confirm it is this company"),
    "wrong case": ("the name only appears in a different case (e.g. the ticker 'ROKT' or the word 'xero')",
                   "text not read: the name only appears in a different case (e.g. the ticker 'ROKT' or the word 'xero')"),
    "passing mention": ("passing mention: listed or compared with others, and barely mentioned in the text",
                        "text not read: passing mention (listed or compared with others)"),
    "one word unconfirmed": ("one-word name, and nothing in the article text confirms it is this company",
                             "text not read: one-word name, and the headline does not confirm it is this company"),
}

FEATURE_NAMES = ["identity_points", "entity_org", "entity_objects", "mention_count", "name_in_title", "fit", "ambiguous", "one_word", "text_read",
                 "zs_any_event", "passing_mention"]


def _words(name):
    return re.findall(r"[A-Za-z0-9&']+", name)


def auto_ambiguous(name, domain):
    """Why a name should be treated as common when the CSV doesn't say (spot checks on 100 Priority List companies):
    numbered companies, names of 3 characters or fewer ("ARG"), and one-word names that aren't the website's own name
    ("Clancy" at clancycorp.com.au, "Array" at arraynetworks.com, "Barga" at caesars.net.au). '' = distinctive."""
    if NUMBERED.match(name or ""):
        return "numbered company"
    core = core_name(name or "")
    if len(re.sub(r"[\W_]", "", core)) <= 3:
        return "short name"
    words = _words(core)
    label = re.sub(r"[^a-z0-9]", "", root_domain(domain).split(".")[0]) if domain else ""
    if len(words) == 1 and label and words[0].lower() != label:      # no website: nothing to compare, left as distinctive
        return "one-word name that is not the website's name"
    return ""


# ================================================================ per-company identity
class Identity:
    """What identifies one company in text, built once from the companies CSV row and the company card (website, filings).
    Treat as read-only: with_name_type() returns a changed copy."""

    def __init__(self, company, card=None):
        card = card or {}
        name = core_name(company.name)
        self.name = name
        all_names = {name, *company.aliases}
        self.names = [name_pattern(n) for n in all_names if len(n) >= 2]
        self.domain = root_domain(company.domain)
        self.places = [name_pattern(p) for p in company.places + company.context if len(p) >= 2]   # score(): location and context words
        self.context = [name_pattern(p) for p in company.context if len(p) >= 2]
        strong = [core_name(n) for n in [card.get("legal_name", ""), *card.get("alt_names", []), *card.get("people", [])]   # without "Pty Ltd"
                  if n and core_name(n).lower() != name.lower() and len(core_name(n)) >= 4]
        self.strong = [(n, name_pattern(n)) for n in dict.fromkeys(strong)]
        t = (company.ticker or card.get("ticker") or "").upper().split(":")[-1].strip()
        self.ticker = re.compile(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])") if len(t) >= 3 else None   # case-sensitive: "TEAM" not "team"
        self.listed = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in all_names if len(n) >= 2) +
                                 r")(?: (?:limited|ltd|inc|corp|corporation|co|company|plc|group|holdings)\.?)?\s*\((?:ASX|NZX|LSE|LON|NASDAQ|NYSE|TSX|OTCMKTS|SGX)\s?:\s?[A-Z0-9.]{1,6}\)",
                                 re.I)
        self.keywords = [(k, name_pattern(k)) for k in card.get("keywords", []) if not any(p.search(k.lower()) for p in self.names)]
        self.city = [name_pattern(p) for p in {*company.places, card.get("city", "")} if p and len(p) >= 2]
        # names that are this company when spaCy finds them as a longer entity ("Xero Limited", a trading name)
        self.known_names = [n for n in [name, *company.aliases, card.get("legal_name", ""), *card.get("alt_names", [])] if n]
        # ambiguous name: set in the CSV, else assumed when context words were given (someone saw the name was common)
        # or detected (auto_ambiguous), or set at export when a name pulls in many unconfirmed articles (common_name_flips)
        self.ambiguous_set = company.ambiguous is not None
        self.ambiguous_reason = ("set in the CSV" if self.ambiguous_set else "context words given" if company.context
                                 else auto_ambiguous(company.name, company.domain))
        self.ambiguous = company.ambiguous if self.ambiguous_set else bool(self.ambiguous_reason)
        emp = getattr(company, "employees", None)
        self.small = emp is not None and emp < SMALL_COMPANY and not (company.ticker or card.get("ticker"))
        self.single_word = len(_words(name)) == 1
        # a one-word name, even the website's own ("Accora" at accora.care, "Atkar" at atkar.com.au), is often also a place,
        # surname or word: at least 1 point of identity evidence is needed (location, keyword, domain…)
        self.one_word = self.small and self.single_word and not self.ambiguous_set
        # case-sensitive name forms ("Deputy"), to tell the company from the ordinary word ("deputy") or a title ("Deputy Mayor")
        self.cased = [re.compile(r"(?<![\w])" + re.escape(n) + r"(?![\w])") for n in all_names if len(n) >= 2]
        self.as_title = [re.compile(r"(?<![\w])" + re.escape(n) + r"\s+" + ROLE + r"\b", re.I) for n in all_names if len(n) >= 2]

    @property
    def name_type(self):
        return f"ambiguous ({self.ambiguous_reason})" if self.ambiguous else "distinctive"

    def with_name_type(self, ambiguous, reason):
        new = copy.copy(self)
        new.ambiguous, new.ambiguous_reason = ambiguous, reason
        return new

    def named_in(self, text):
        low = (text or "").lower()
        return any(p.search(low) for p in self.names)

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
        if any(p.search(low) for p in self.context):
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
        return self.named_in(raw) and self.company_uses(raw, minus_titles=False) == 0

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

    def passing_phrase(self, title):
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

    @staticmethod
    def solid_points(pts, found):
        """Identity points without the one that single website keywords give: for a one-word name a lone generic word
        is not confirmation ("designed" confirmed Kid Koala, "steam" confirmed immutable Linux)."""
        return pts - (1 if any(f.startswith("keyword ") and " " not in f[8:] for f in found) else 0)

    def name_rule(self, title, text, pts, found):
        """Step 1 of judge(): the rule that rejects the article, or ''. text = article text if read, else ''.
        Ambiguous names: the name must be used as the company (not "Deputy Mayor" or "deputy") and CONFIRM points are needed.
        Distinctive names: a mention is enough, except in a different case, a passing mention in a list or comparison (needs the
        text to use the name PASSING_MENTION_USES+ times, or CONFIRM points), or a small company's one-word name with no evidence."""
        read = bool(text)
        body = f"{title} {text}" if read else ""
        if read:
            if not_english(body):
                return "not english"
            if not (self.named_in(body) or (self.domain and self.domain in body.lower())):
                return "not named"
        if self.ambiguous:
            if self.company_uses(body if read else title) == 0:
                return "name used as word"
            return "common name unconfirmed" if pts < CONFIRM else ""
        if self.wrong_case(body) if read else (self.wrong_case(title) and pts < CONFIRM):
            return "wrong case"
        if self.passing_mention(title) and pts < CONFIRM and (not read or self.company_uses(body, minus_titles=False) < PASSING_MENTION_USES):
            return "passing mention"
        if self.one_word and self.solid_points(pts, found) < 1:
            return "one word unconfirmed"
        return ""

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


# ================================================================ NLP entity check (spaCy entities from `nlp run`)
def _norm_words(s):
    s = re.sub(r"['’]s", "", (s or "").lower())                    # "Canva's" is Canva
    return [w for w in re.findall(r"[a-z0-9&-]+", s) if w not in GENERIC_NAME_WORDS]


def longer_entity(names, title, entities):
    """Normalised text of the headline entity that contains the company name but is longer than it, else ''.
    Counted per company across its articles: a name that keeps recurring ("array technologies") is another company."""
    low = (title or "").lower()
    for p in names:
        m = p.search(low)
        if m:
            a, b = m.span()
            for e in entities:
                if e["in"] == "title" and e["start"] <= a and e["end"] >= b:
                    extra = [w for w in _norm_words(e["text"]) if w not in _norm_words(title[a:b])]
                    return " ".join(_norm_words(e["text"])) if extra else ""
    return ""


def entity_check(names, title, lead, entities, known_names=(), recurring=frozenset(), one_word=False, is_actor=False, strict=False):
    """How the company name sits in the text. names: regexes for the name, aliases and strong names (Identity).
    Returns (verdict, note): 'org' (named as an organisation), 'ok' (no objection), or a reject reason:
      compound     part of a hyphenated word ("Big Post-Launch")
      longer name  inside a longer name, only when that longer name recurs across the company's articles (recurring),
                   carries another company's suffix ("Array Technologies"), or is a person or place ("Lindsay Clancy's",
                   "Accora Village"). A descriptor ("Armstrong Ambulance Service") or headline-case NER noise ("Canva Offers
                   Layoff Package") is not held against the article.
      wrong type   a one-word name tagged as a person or place ("Clancy", "Barga"); two-word firms are often named after
                   people (Shaw Gibbs). Never when the name is the actor of a business event (is_actor).
      strict       small companies only (Identity.small): the compound, longer-name and type rules. Well-known companies
                   skip them: "Ex-Canva staff" and Reuters' "BRIEF-Atlassian Q1 Revenue" are real news, their names are tagged
                   inconsistently ("Xero" as a product, "Xero Limited" as a person) and a longer name is usually their own
                   product ("Xero Launches", "Canva Education")."""
    known = {" ".join(_norm_words(n)) for n in known_names if n}
    verdict = ("ok", "")
    for where, text in (("lead", lead), ("title", title)):
        if not text:
            continue
        low = text.lower()
        for p in names:
            m = p.search(low)
            if not m:
                continue
            a, b = m.span()
            if strict and (re.match(r"-\w", text[b:b + 2]) or re.search(r"\w-$", text[:a])):
                return "compound", f"part of a hyphenated word in the {where}: '{text[max(0, a - 12):b + 12].strip()}'"
            ents = [e for e in entities if e["in"] == where and e["start"] <= a and e["end"] >= b]
            if not ents:
                continue
            e = ents[0]
            norm = " ".join(_norm_words(e["text"]))
            extra = [w for w in _norm_words(e["text"]) if w not in _norm_words(text[a:b])]
            if extra and norm not in known:
                if strict and (norm in recurring or set(extra) & ORG_SUFFIX or e["label"] in BAD_TYPES):
                    return "longer name", f"part of a longer name in the {where}: '{e['text']}'"
                continue                                             # one-off longer ORG in a headline: no opinion
            if strict and e["label"] in BAD_TYPES and not extra and one_word and not is_actor:
                return "wrong type", f"named as {BAD_TYPES[e['label']]} in the {where} ('{e['text']}')"
            if e["label"] == "ORG" or is_actor:
                verdict = ("org", f"named as an organisation in the {where}")
    return verdict


def features(pts, entity_verdict, mentions, in_title, fit, ambiguous, one_word, text_read, zs_any, passing):
    """The combiner's inputs, in FEATURE_NAMES order (nlp.train fits on these)."""
    return [pts, 1 if entity_verdict == "org" else 0, 1 if entity_verdict not in ("ok", "org", "") else 0, min(mentions, 10), 1 if in_title else 0,
            fit if fit is not None else 0.0, 1 if ambiguous else 0, 1 if one_word else 0, 1 if text_read else 0, 1 if zs_any else 0, 1 if passing else 0]


# ================================================================ the decision
@dataclass
class NlpSignals:
    """What judge() uses from the cached `nlp run` results for one article."""
    entities: list
    is_actor: bool = False          # the company is the subject/object of an extracted business event
    fit: float | None = None        # cosine between the article and the company description
    zs_any: bool = False            # zero-shot found a scored event category


@dataclass
class IdentityResult:
    counts: bool
    rule: str                       # what decided: a REASONS key, an NLP/combiner rule, or for counted articles
    reason: str = ""                # "evidence", "name only", "company website", "combiner"; reason = why not ('' if counted)
    evidence: list = field(default_factory=list)
    points: int = 0
    mentions: int = 0
    entity_check: str = ""          # "verdict: note" from entity_check, '' without NLP results
    about_p: float | str = ""       # the combiner's probability, '' without a trained combiner
    features: list | None = None    # combiner inputs (only with NLP results)


def judge(ident, *, title, summary, source, score, text="", nlp=None, recurring=frozenset(), min_match=MATCH, combiner=None):
    """Does this stored article count as news about the company? See the module docstring for the rule order.
    text: the article text if it was read, else ''. nlp: NlpSignals or None. recurring: longer headline names that recur
    across this company's articles (another company). combiner: the dict from nlp.about_company_model(), or None."""
    title, summary, text = title or "", summary or "", text or ""
    read = bool(text)
    pts, found = ident.evidence(f"{title} {text}" if read else f"{title} {summary}")
    mentions = ident.company_uses(f"{title} {summary} {text}", minus_titles=False)
    verdict, note = "", ""
    if nlp is not None:
        lead = f"{summary} {text[:600]}".strip()
        verdict, note = entity_check(ident.names + [p for _, p in ident.strong], title, lead, nlp.entities, ident.known_names, recurring,
                                     one_word=ident.single_word, is_actor=nlp.is_actor, strict=ident.small)
    feats = features(pts, verdict, mentions, ident.named_in(title), nlp.fit, ident.ambiguous, ident.one_word, read, nlp.zs_any,
                     ident.passing_mention(title)) if nlp is not None else None
    res = IdentityResult(True, "", "", found, pts, mentions, f"{verdict}: {note}" if note else verdict, "", feats)

    if source == "newsroom":
        res.rule, res.evidence = "company website", ["company's own website"]
        return res

    def reject(rule, reason):
        res.counts, res.rule, res.reason = False, rule, reason

    rule = ident.name_rule(title, text, pts, found)
    if rule:
        reject(rule, REASONS[rule][0 if read else 1])
        if rule == "not english":
            res.evidence = []
    elif verdict in ("compound", "longer name") or (verdict == "wrong type" and pts < CONFIRM):
        reject(f"nlp {verdict}", note)
    elif (phrase := ident.passing_phrase(title)) and mentions < PASSING_PHRASE_MENTIONS:
        reject("passing phrase", f"passing mention: '{phrase}'")
    below_min = score < min_match
    if below_min and res.counts:
        reject("match score", f"low match score ({score})")
    elif below_min:
        res.reason = res.reason or f"low match score ({score})"
    if res.counts:
        res.rule = "evidence" if found else "name only"

    if combiner and feats:
        p = round(float(combiner["model"].predict_proba([feats])[0][1]), 3)
        res.about_p = p
        if p >= COMBINER_ACCEPT and not res.counts and not below_min:
            res.counts, res.rule, res.reason = True, "combiner", ""
            res.evidence = [*found, f"combiner p={p}"]
        elif p <= COMBINER_REJECT and res.counts:
            reject("combiner", f"combiner says not this company (p={p})")
    return res


def common_name_flips(identities, counted):
    """Company-level pass after a first judging: a small company's short "distinctive" name with many matches that almost
    nothing confirms is really a common word ("Clutch"). counted: {company_id: [counted third-party rows with text_status and
    evidence]}. Returns {company_id: reason}; apply with Identity.with_name_type(True, reason) and judge again."""
    flips = {}
    for cid, rows in counted.items():
        ident = identities[cid]
        if not ident.small or ident.ambiguous or ident.ambiguous_set or len(ident.name.split()) > VOLUME_MAX_WORDS or len(rows) < VOLUME_MIN:
            continue
        # judged on articles whose text was read: a headline alone rarely carries a domain or a city, so unread articles say
        # nothing either way (Tyro Payments was flagged when no text had been read)
        read = [r for r in rows if r["text_status"] == "ok"]
        if len(read) >= VOLUME_MIN_READ and sum(bool(r["evidence"]) for r in read) / len(read) < VOLUME_CONFIRMED:
            flips[cid] = f"{len(rows)} matches, few confirm the company"
    return flips
