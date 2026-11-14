"""Sort an article into the Priority Score's news categories, with keyword rules (no LLM in the POC).

Category names and strengths are read from the scoring settings (scoring_settings.json, kind "news" and
"recency"), so they stay in step with the model. The first rule that matches wins, so the more specific
categories come first (a PE buyout is also an acquisition).
"""
import json
import re

EXEC = r"(ceo|cfo|cto|coo|cmo|cro|cpo|chief [a-z]+ officer|managing director|chair(man|woman|person)?|president|general manager|country manager|head of [a-z]+)"
PLACES = (r"(the )?(us|u\.s\.|usa|united states|america|uk|u\.k\.|united kingdom|britain|australia|new zealand|nz|europe|asia|apac|emea|canada|"
          r"singapore|japan|india|philippines|ireland|germany|france|the middle east|latin america|southeast asia)")
PE_FIRMS = (r"(kkr|blackstone|carlyle|tpg|bain capital|advent international|eqt|permira|cvc|thoma bravo|vista equity|silver lake|hg capital|"
            r"warburg pincus|pacific equity partners|bgh capital|quadrant private equity|anchorage capital|adamantem|five v)")

# Each category is a list of patterns (case-insensitive), joined with OR. The first category that matches wins.
RULES = [
    ("PE buyout", [
        r"private equity", r"\bbuy-?out\b", r"majority stake",
        r"acquired by [\w&.' -]{0,40}(capital|partners|equity|investments)\b",
        r"\btak(e|es|en|ing) private\b|\bgo(es|ing)? private\b",                                 # take-private deals
        PE_FIRMS + r"\b.{0,40}\b(buy|buys|acquire|acquires|takeover|bid|stake)\b",               # a named PE firm buying
    ]),
    ("Funding round", [
        r"\braise[sd]?\b.{0,40}(\$|£|€|\bm\b|million|billion|funding)", r"funding round|round of funding", r"\bseries [a-e]\b",
        r"(pre-?)?seed (round|funding)", r"capital raise", r"secures? .{0,30}(funding|investment)", r"(investment|round) led by",
        r"\b(mega|capital|equity|funding|growth|venture|seed) raise\b",                         # "mega raise", "seed raise"
        r"[$£€][\d.,]+\s*(k|m|mn|bn|b|million|billion)\b\s+raise\b",                            # "$320 million raise"
        r"\b(lands?|bags?|nabs?|clos(es|ed)|complet(es|ed)) .{0,30}(funding|investment round|capital raise)",
    ]),
    ("Restructuring", [
        r"restructur", r"lay-?offs?\b|lays off|laying off|laid\s*-?\s*off", r"job cuts?\b", r"redundanc", r"downsiz",
        r"\b(cuts?|cutting|slash(es|ed|ing)?|shed(s|ding)?|axe[sd]?|axing|trims?|trimm(ed|ing)|eliminat(es|ed|ing)|culls?)\b.{0,40}"
        r"\b(jobs?|roles?|staff|workers|employees|workforce|positions|headcount)\b",              # "slashes 22% of its workforce"
        r"\b(swings?|wields?|takes?) (the )?axe\b",
        r"\breorgani[sz]ation\b|\bre-?orgs?\b",
        r"\b(clos(es|ed|ing)|closure of|shut(s|ting)?( down)?)\b.{0,30}\b(office|offices|operations|plant|factory|site|stores?|branch(es)?|division|unit)\b",
        r"(into|enters?|placed in|collapses? into) (voluntary )?administration|administrators? appointed|appoints? (voluntary )?(administrators|receivers|liquidators)",
        r"receivership|liquidat|insolven|bankrupt|chapter 11|ceases? trading",
    ]),
    ("M&A", [
        r"\bacquires?\b|\bacquired\b|\bacquisition\b", r"\bmerger\b|\bmerges?\b", r"takeover", r"to buy\b|\bbuys\b|agreed to purchase",
        r"\b(snaps?|snapped|scoops?|scooped|gobbles?|gobbled) up\b|\bswoops? on\b",
        r"\btak(e|es|ing) (a )?([\w-]+ )?(stake|shareholding) in\b|minority investment in|complet(es|ed) (its |an )?investment in",
        r"\b(sells?|sold|selling|divests?|divested|offloads?|offloaded) (its |a |the |their )?([\w-]+ )?(stake|business|division|unit|arm|subsidiary|shareholding)\b",
        r"stake sale|\bdivest", r"\bspin-?off\b|\bspun off\b|\bdemerg",
    ]),
    ("Leadership change", [
        r"\bappoint(s|ed|ment)\b", r"\bnames? .{0,30}(ceo|cfo|cto|coo|chief|managing director|chair)",
        r"\b(new|incoming|interim|acting) (ceo|cfo|cto|coo|chief|managing director|chair|president)",
        r"steps? down|stepping down|resign(s|ed|ation)?\b", r"joins as|to succeed", r"\b(promoted|elevated) to\b",
        r"\b(hires?|hired|taps?|tapped|names?|named|picks?|picked|poach(es|ed)?|recruits?|recruited|brings? in|welcomes?)\b.{0,50}"
        r"\bas (its |the |a )?(new |interim |acting |incoming )?" + EXEC + r"\b",                       # "taps X as CFO"
        EXEC + r"\b.{0,40}\b(exits?|departs?|quits?|leaves|leaving|to leave|retires?|retiring|ousted|sacked|fired|replaced)\b",
        r"\b(exits?|departs?|leaves|quits?|retires?)\b.{0,40}\bafter (\d+|two|three|four|five|six|seven|eight|nine|ten) years\b",
        r"\b(leadership|executive|board|management) (shake-?up|reshuffle|overhaul|changes?)\b",
    ]),
    ("Expansion / new office", [
        r"expand(s|ed)? (into|to|in|its|operations|presence|footprint|team)", r"expansion (into|to|in|plans?|drive|push)\b",
        r"\bus expansion|global expansion|international expansion|overseas expansion",
        r"opens? (a |its |their )?(new |second |first |larger |flagship )?(office|hq|headquarters|hub|facility|site|store|centre|center|campus|base|warehouse)",
        r"\b(new|second|larger|bigger|flagship) (office|hq|headquarters|hub|campus|base|warehouse)\b",
        r"\b(launch(es|ed)?|debuts?|arrives?|lands?|rolls? out) in " + PLACES + r"\b",                # replaces "launches in <anything>"
        r"enters? (the )?[\w .&-]{0,25}market",                                                       # now allows "U.S."
        r"to (create|hire) \d+|hiring \d+",
        r"hiring (spree|push|drive|blitz)|recruitment drive|(ramps?|steps?) up (its )?hiring|"
        r"(boosts?|grows?|doubles?|triples?) (its )?(headcount|workforce|team|staff)\b",
    ]),
]
_RULES = [(cat, re.compile("|".join(f"(?:{p})" for p in pats), re.I)) for cat, pats in RULES]
# a rule that matched is ignored when one of these also matches (common false positives)
NOT = {
    "Funding round": re.compile(r"price target|\bstocks?\b|\bshares?\b|\brating\b|analyst|-backed\b|\bbacked\b|\bbackers?\b|"
                                r"raises? (prices?|concerns?|questions?|awareness|the bar|eyebrows|alarm|fees?)", re.I),
    "M&A": re.compile(r"talent acquisition|customer acquisition|user acquisition|data acquisition|stocks? to buy|\bbuy rating|shares to buy|should you buy|"
                      r"(snaps?|snapped|scoops?|scooped) up (\w+ )?(shares|stocks?|bargains|tickets|awards?)|sells? (its |the )?(\w+ )?(home|house|mansion|property)", re.I),
    "Restructuring": re.compile(r"\b(cuts?|slash(es|ed)?) (prices?|fees?|rates?|bills?|tax(es)?|costs? for customers)\b|hiring (staff|workers|employees)|"
                                r"cut (staff|workers'?) (hours|pay)|closes? (the )?(gap|deal|round|day|week|session)", re.I),
    "Leadership change": re.compile(r"\b(deputy|vice) (pm|prime minister|mayor|premier|minister|governor|sheriff)\b", re.I),
    "Expansion / new office": re.compile(r"helps? .{0,40}expand|how to expand|tips", re.I),
}
# SEO company-profile pages (Tracxn, CB Insights and the like): not news, dropped entirely
PROFILE = re.compile(r"list of investors|funding rounds? &|how much did .{0,40}raise|funding & key investors|company profile|"
                     r"competitors (&|and) alternatives|revenue,? valuation|valuation & funding|org chart|employee count|"
                     r"\b(stock|share) price (today|quote|history)|\bstock quote\b|seasonal returns chart|interactive stock chart|\b[A-Z]{1,6}\d{6}[PC]\d{8}\b", re.I)
OTHER = "Other / Unclassified"

DEFAULT_STRENGTH = {"Funding round": 1.0, "PE buyout": 1.0, "M&A": 0.8, "Expansion / new office": 0.7, "Restructuring": 0.5,
                    "Leadership change": 0.3, OTHER: 0.3, "None": 0.0}
DEFAULT_RECENCY = [(30, 1.0), (90, 0.7), (180, 0.4), (None, 0.0)]


def load_settings(path):
    """Strengths and recency factors from scoring_settings.json; falls back to the agreed defaults."""
    if not path:
        return DEFAULT_STRENGTH, DEFAULT_RECENCY
    rows = json.load(open(path, encoding="utf-8"))
    strength = {r["label"]: float(r["value"]) for r in rows if r["kind"] == "news"} or DEFAULT_STRENGTH
    rec = []
    for r in (r for r in rows if r["kind"] == "recency"):
        m = re.search(r"(\d+)\D*$", r["label"])
        rec.append((None if r["label"].lower().startswith("over") or not m else int(m.group(1)), float(r["value"])))
    return strength, rec or DEFAULT_RECENCY


def classify(title, summary):
    """Category name, or None for a company-profile page that is not news (the caller drops it)."""
    if PROFILE.search(title or ""):
        return None
    text = f"{title or ''}. {summary or ''}"
    for cat, pat in _RULES:
        if pat.search(text) and not (cat in NOT and NOT[cat].search(text)):
            return cat
    return OTHER


def recency_factor(age_days, recency):
    for limit, factor in recency:
        if limit is None or age_days <= limit:
            return factor
    return 0.0
