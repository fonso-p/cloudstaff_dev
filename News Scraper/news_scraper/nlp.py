"""Free NLP on top of the keyword rules: is the article about *this* company, what happened, and who did what to whom.

    python -m news_scraper nlp run   [--db data/news.db] [--scope company|segment|all] [--stages entities,events,embed,zeroshot]
                                     [--zs-all] [--limit N]
    python -m news_scraper nlp label [--db] [--out labels.csv] [--n 200]     # a sheet to label by hand
    python -m news_scraper nlp train --labels labels.csv [--db]              # SetFit + evidence combiner from the labels
    (export picks the results up automatically: nlp_* and zs_* columns, and the entity checks in `check`)

Four techniques, all CPU-only and free (dependency group `nlp` in pyproject.toml):
  entities   spaCy NER on the headline and lead. At export the company name is compared with the entity that contains it:
             a longer name ("Array Technologies" for Array Inc.), a person or place ("Clancy", "Barga"), or a hyphenated
             compound ("Big Post-Launch") means it is not our company.
  events     spaCy dependency parse + trigger words: the event (M&A, funding, layoffs, expansion, leadership, insolvency),
             who did it to whom (subject / object / agent, so "acquires" vs "acquired by"), the details (job count and %,
             place, executive title, amount) and the certainty (reported / announced / possible / denied).
  embed      MiniLM sentence embeddings: semantic fit between the article and the company's description, and grouping
             the same story reported by several outlets.
  zeroshot   An NLI model scores plain-English event descriptions against the headline and lead, for the articles the
             rules left as "Other". Slowest step (~1 s per article on a laptop CPU), so it runs on matched articles only
             unless --zs-all.
  train      After labelling (nlp label -> labels.csv): a SetFit few-shot classifier for the category and a logistic
             combiner for "about this company" that learns how much to trust each piece of evidence.

Scaling: results are cached per article (dedupe_key + a hash of the text used) in nlp_articles, so every article is
processed once however many companies or exports touch it, and re-processed only when its text is read later or a model
version changes (MODEL_VERSION). Models load once per process and run in batches. Nothing here needs a GPU; with one,
set device in _zs()/_st() and zero-shot gets ~20x faster.
"""
import datetime as dt
import hashlib
import json
import os
import re
import struct
from collections import Counter, defaultdict

MODEL_VERSION = "2026-11-13.4"           # bump to recompute everything
SPACY_MODEL = "en_core_web_sm"
ZS_MODEL = "MoritzLaurer/deberta-v3-xsmall-zeroshot-v1.1-all-33"
ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LEAD_CHARS = 900                         # of the article text, after the headline and summary
ZS_MIN = 0.6                             # zero-shot score needed to assign a category
FIT_LOW = 0.05                           # cosine below this: article and company description are unrelated (soft signal)
STORY_SIM, STORY_DAYS = 0.72, 10         # same story from several outlets
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(HERE, "data", "models")

TABLES = """
CREATE TABLE IF NOT EXISTS nlp_articles (
  dedupe_key TEXT PRIMARY KEY, text_hash TEXT, model_version TEXT, computed_at TEXT,
  entities TEXT, events TEXT, zeroshot TEXT, zs_scope TEXT, embedding BLOB);
"""

# ---------------------------------------------------------------- zero-shot label sets -> score categories
# label text -> (category in the Priority Score's terms, detail)
ZS_COMPANY = {
    "laying off staff or cutting jobs": ("Restructuring", "layoffs"),
    "going into administration, insolvency or closing down": ("Restructuring", "insolvency"),
    "acquiring another company or business": ("M&A", "acquirer"),
    "being acquired, bought or taken over by another company": ("M&A", "target"),
    "a private equity investment or buyout": ("PE buyout", ""),
    "raising a funding round from investors": ("Funding round", ""),
    "opening a new office or expanding into a new market": ("Expansion / new office", ""),
    "appointing a new executive or an executive leaving": ("Leadership change", ""),
    "quarterly or annual financial results": ("Other / Unclassified", "results"),
    "a product launch, partnership or award": ("Other / Unclassified", "product / award"),
}
ZS_SEGMENT = {
    "companies offshoring or outsourcing work": "Offshoring / outsourcing",
    "a shortage of staff, skills or workers": "Labour shortage",
    "rising costs, wages or cost pressure on businesses": "Cost pressure",
    "layoffs, redundancies or restructuring": "Restructuring / layoffs",
    "mergers, acquisitions or industry consolidation": "Consolidation / M&A",
    "a downturn, insolvencies or falling demand": "Downturn",
    "new regulation, compliance rules or reforms": "Regulation / compliance",
    "artificial intelligence or automation": "AI / automation",
    "growth, investment or expansion": "Growth / investment",
}
HYPOTHESIS = "This news is about {}."

# ---------------------------------------------------------------- event triggers (lemmas) -> category
TRIGGERS = {
    "M&A": {"acquire", "buy", "purchase", "merge", "takeover", "acquisition", "merger", "buyout", "sell", "divest", "offload", "stake"},
    "Funding round": {"raise", "secure", "funding", "investment", "round"},
    "Restructuring": {"cut", "slash", "axe", "shed", "eliminate", "layoff", "lay", "redundancy", "restructure", "restructuring", "downsize",
                      "close", "closure", "shut", "collapse", "liquidate", "liquidation", "administration", "administrator", "receivership",
                      "insolvency", "bankruptcy", "wind", "wind-down", "dissolve", "shutter"},
    "Expansion / new office": {"open", "expand", "expansion", "launch", "enter", "hire", "hiring", "grow", "double", "triple"},
    "Leadership change": {"appoint", "name", "hire", "promote", "join", "tap", "pick", "recruit", "welcome", "elevate", "step", "resign",
                          "exit", "depart", "quit", "retire", "leave", "oust", "sack", "fire", "replace", "succeed"},
}
# objects that make a generic trigger specific: "cut" is layoffs only with jobs; "open" is expansion only with an office
JOBS = re.compile(r"\b(jobs?|roles?|staff|workers|workforce|employees|positions?|headcount|people|redundanc\w*|layoffs?)\b", re.I)
PLACES_KIND = re.compile(r"\b(office|offices|hq|headquarters|hub|facility|site|store|stores|centre|center|campus|base|warehouse|depot|"
                         r"clinic|branch|branches|plant|factory|operations|market|team)\b", re.I)
FUNDS = re.compile(r"\b(funding|investment|capital|round|series [a-e]|seed|financing|raise)\b", re.I)
EXEC = re.compile(r"\b(ceo|cfo|cto|coo|cmo|cro|cpo|chro|chief [a-z]+ officer|managing director|chair(man|woman|person)?|president|"
                  r"general manager|country manager|head of [a-z ]{3,30}|partner|director|vice president|vp|md|principal)\b", re.I)
INSOLV = re.compile(r"\b(administration|administrators?|receivers?|receivership|liquidat\w*|insolven\w*|bankrupt\w*|wind(ing|s)?[- ]?(up|down)|"
                    r"collapse[sd]?|ceases? trading|dissolve[sd]?|dissolution)\b", re.I)
BUSINESS_OBJ = re.compile(r"\b(stake|business|division|unit|arm|subsidiary|company|firm|practice|operations|portfolio|assets?|brand|chain|"
                          r"shareholding|interest in)\b", re.I)
# another company's naming: "Array Technologies" is not "Array Inc.", "Clutch Security" is not "Clutch"
ORG_SUFFIX = {"technologies", "technology", "tech", "systems", "solutions", "networks", "security", "software", "labs", "capital", "partners",
              "ventures", "village", "estate", "estates", "park", "centre", "center", "hospital", "university", "college", "school", "church",
              "inc", "corp", "corporation", "llc", "plc", "ltd", "limited", "gmbh", "ag", "sa", "bank", "media", "entertainment", "studios",
              "games", "motors", "airlines", "energy", "mining", "resources", "pharmaceuticals", "therapeutics", "biosciences", "foods"}
ORG_SUFFIX -= {"ltd", "limited", "inc", "corp", "corporation", "llc", "plc"}      # our own suffix is stripped already (GENERIC_NAME_WORDS)
PE = re.compile(r"\bprivate equity\b|\bpe[- ](firm|backed|owned)\b|\b(capital|partners|equity|investments)\b", re.I)
COUNT = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d+)\s*(?:jobs?|roles?|staff|workers|employees|positions?|people|redundancies)\b", re.I)
PCT = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s?(%|per ?cent)\b", re.I)
MONEY = re.compile(r"(?:A\$|US\$|NZ\$|\$|£|€)\s?\d[\d.,]*\s?(?:k|m|mn|bn|b|million|billion)?\b", re.I)
POSSIBLE = re.compile(r"\b(plans?|planning|planned|set to|in talks|considering|considers?|mulls?|mulling|reportedly|could|may|might|eyes|eyeing|"
                      r"weighs?|weighing|exploring|explores?|poised|nears?|nearing|rumou?r|likely|expected to|looks? to|seeks? to|aims? to|"
                      r"proposed|proposal|bid for|bids? to|offer for)\b", re.I)
DENIED = re.compile(r"\b(denies|denied|rules? out|ruled out|no plans|rejects?|rejected|scraps|scrapped|abandons?|abandoned|calls? off|"
                    r"called off|won'?t|will not|not (planning|going) to)\b", re.I)
COMPLETED = re.compile(r"\b(completes?|completed|closes?|closed|finalis\w+|finaliz\w+|wraps? up)\b", re.I)
GENERIC_NAME_WORDS = {"the", "a", "an", "group", "team", "staff", "ceo", "cfo", "coo", "cto", "boss", "chief", "founder", "founders", "co-founder",
                      "shares", "stock", "stocks", "share", "ltd", "limited", "pty", "inc", "llc", "plc", "corp", "corporation", "co", "company",
                      "holdings", "australia", "australian", "uk", "us", "nz", "'s", "’s", "s", "and", "&", "of"}
# NER types that make a one-word name "something else". PRODUCT and WORK_OF_ART are left out on purpose: spaCy tags well-known
# brands (Xero, Canva) as products. And the type rules apply to small companies only (see entity_check(strict=...)).
BAD_TYPES = {"PERSON": "a person", "GPE": "a place", "LOC": "a place", "FAC": "a building or place", "EVENT": "an event",
             "NORP": "a nationality or group", "DATE": "a date"}

_cache = {}


# ================================================================ models (loaded once per process)
def _spacy():
    if "spacy" not in _cache:
        import spacy
        _cache["spacy"] = spacy.load(SPACY_MODEL, disable=["lemmatizer"] if False else [])
    return _cache["spacy"]


def _zs():
    if "zs" not in _cache:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from transformers import pipeline
        import torch
        torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))
        _cache["zs"] = pipeline("zero-shot-classification", model=ZS_MODEL, device=-1)
    return _cache["zs"]


def _st():
    if "st" not in _cache:
        from sentence_transformers import SentenceTransformer
        _cache["st"] = SentenceTransformer(ST_MODEL, device="cpu")
    return _cache["st"]


# ================================================================ inputs
def article_text(title, summary, text):
    """What the NLP sees: headline, summary (when it isn't just the headline again) and the first LEAD_CHARS of the text."""
    t = (title or "").strip()
    s = (summary or "").strip()
    if s and (s.lower().startswith(t.lower()[:40]) or t.lower().startswith(s.lower()[:40])):
        s = ""
    lead = re.sub(r"\s+", " ", (text or "")[:LEAD_CHARS]).strip()
    return t, s, lead


def text_hash(title, summary, lead):
    return hashlib.sha1(f"{title}|{summary}|{lead}".encode("utf-8", "replace")).hexdigest()[:16]


def inputs(store, scope="all"):
    """{dedupe_key: (title, summary, lead, scope, matched)} for every stored article (one row per story)."""
    q = store.db.execute
    out = {}
    if scope in ("company", "all"):
        texts = {(r[0], r[1]): r[2] for r in q("SELECT company_id, dedupe_key, text FROM article_texts WHERE status='ok' AND company_id NOT LIKE 'seg:%'")}
        for cid, key, title, summary, score in q("SELECT company_id, dedupe_key, title, summary, match_score FROM articles"):
            t, s, lead = article_text(title, summary, texts.get((cid, key), ""))
            prev = out.get(key)
            if prev is None or (lead and not prev[2]):
                out[key] = (t, s, lead, "company", (score or 0) >= 0.6 or (prev[4] if prev else False))
            elif (score or 0) >= 0.6:
                out[key] = (*prev[:4], True)
    if scope in ("segment", "all"):
        texts = {(r[0], r[1]): r[2] for r in q("SELECT company_id, dedupe_key, text FROM article_texts WHERE status='ok' AND company_id LIKE 'seg:%'")}
        for sid, key, title, summary in q("SELECT segment_id, dedupe_key, title, summary FROM segment_articles"):
            t, s, lead = article_text(title, summary, texts.get((sid, key), ""))
            prev = out.get(key)
            if prev is None or (lead and not prev[2]):
                out[key] = (t, s, lead, "segment", True)
    return out


# ================================================================ entities + events (spaCy)
def _spans(doc):
    return [{"text": e.text, "label": e.label_, "start": e.start_char, "end": e.end_char} for e in doc.ents]


def _subtree_text(tok):
    return "".join(t.text_with_ws for t in tok.subtree).strip()


def _children(tok, deps):
    return [c for c in tok.children if c.dep_ in deps]


def _prep_obj(tok, preps):
    """Object of 'tok <prep> X' for the given prepositions, e.g. ('by',) -> the agent."""
    for c in tok.children:
        if c.dep_ in ("prep", "agent") and c.text.lower() in preps:
            objs = _children(c, ("pobj",))
            if objs:
                return _subtree_text(objs[0])
    return ""


def _sentence_events(sent, where):
    """Events in one sentence: category, trigger, who (subject / object / agent), details, certainty."""
    text = sent.text
    found = []
    for tok in sent:
        lemma = tok.lemma_.lower()
        cat = next((c for c, trig in TRIGGERS.items() if lemma in trig), None)
        if not cat or tok.pos_ not in ("VERB", "NOUN", "PROPN", "AUX"):
            continue
        subj = next((_subtree_text(c) for c in _children(tok, ("nsubj", "nsubjpass"))), "")
        passive = bool(_children(tok, ("nsubjpass",))) or bool(_children(tok, ("auxpass",)))
        obj = next((_subtree_text(c) for c in _children(tok, ("dobj", "attr", "oprd"))), "")
        agent = _prep_obj(tok, ("by",))
        if tok.pos_ == "NOUN":                                   # "acquisition of Y by X", "X's acquisition of Y"
            obj = obj or _prep_obj(tok, ("of",))
            poss = _children(tok, ("poss",))
            subj = subj or (_subtree_text(poss[0]) if poss else "")
            if tok.head.pos_ == "VERB" and not subj:            # "X completes acquisition of Y"
                subj = next((_subtree_text(c) for c in _children(tok.head, ("nsubj",))), "")
        if agent and not passive:                               # headline passive without "is": "Clermont acquired by Riveron"
            passive = True
        ev = {"category": cat, "trigger": tok.text, "lemma": lemma, "where": where, "subject": subj[:80], "object": obj[:80],
              "agent": agent[:80], "passive": passive, "detail": "", "place": "", "person": "", "exec": "", "count": "", "pct": "",
              "amount": "", "direction": ""}
        window = _subtree_text(tok.head if tok.dep_ != "ROOT" else tok) or text
        # --- make generic triggers specific, and pull out the details
        if cat == "Restructuring":
            if lemma in ("cut", "slash", "axe", "shed", "eliminate", "downsize") and not JOBS.search(obj):
                continue                                             # the thing cut must be jobs: "cuts internal valuation" is not layoffs
            if lemma == "lay" and not JOBS.search(obj + " " + window):
                continue
            if lemma in ("close", "closure", "shut") and (not PLACES_KIND.search(obj + " " + window)
                                                          or re.search(r"(stock|shares?|market|session|trading|week|day)", window, re.I)):
                continue
            if lemma == "wind" and not re.search(r"\bwind(s|ing)? (up|down)\b", window, re.I):
                continue
            ev["detail"] = "insolvency" if INSOLV.search(window) or lemma in ("collapse", "liquidate", "liquidation", "administration",
                                                                                  "administrator", "receivership", "insolvency", "bankruptcy") \
                else "closure" if lemma in ("close", "closure", "shut") else "layoffs"
            m = COUNT.search(text)
            ev["count"] = m.group(1) if m else ""
            m = PCT.search(text)
            ev["pct"] = m.group(1) + "%" if m else ""
        elif cat == "Expansion / new office":
            if lemma in ("open", "launch", "enter", "grow", "double", "triple") and not PLACES_KIND.search(obj + " " + window):
                continue
            if lemma in ("hire", "hiring") and not re.search(r"\d", window):
                continue
            kind = PLACES_KIND.search(obj + " " + window)
            ev["detail"] = kind.group(1).lower() if kind else "expansion"
            place = next((e.text for e in sent.ents if e.label_ in ("GPE", "LOC") and e.start_char >= tok.idx), "")
            ev["place"] = place
        elif cat == "Funding round":
            if lemma in ("raise", "secure") and not (FUNDS.search(window) or MONEY.search(window)):
                continue
            if lemma == "round" and not re.search(r"(funding|series [a-e]|seed|financing)", window, re.I):
                continue                                             # "Rounding error" is not a funding round
            if lemma in ("funding", "investment") and tok.pos_ != "NOUN":
                continue
            m = MONEY.search(text)
            ev["amount"] = m.group(0) if m else ""
            ev["agent"] = ev["agent"] or _prep_obj(tok, ("from",)) or re.sub(r"^.*\bled by\s+", "", text)[:80] if re.search(r"\bled by\b", text) else ev["agent"]
        elif cat == "M&A":
            if lemma == "buy" and re.search(r"\b(shares?|stocks?|rating|to buy\b.*\b(now|today))", window, re.I):
                continue
            if lemma == "stake" and not re.search(r"\bstake in\b", window, re.I):
                continue
            if lemma == "acquisition" and re.search(r"\b(talent|customer|user|data|land) acquisition\b", window, re.I):
                continue
            if lemma in ("sell", "divest", "offload") and not BUSINESS_OBJ.search(obj + " " + window):
                continue                                             # "to sell 3.39 million shares" is not a divestment
            ev["detail"] = "sale" if lemma in ("sell", "divest", "offload") else "stake" if lemma == "stake" else "merger" if lemma in ("merge", "merger") else "acquisition"
            buyer = agent if passive else subj                       # only the acquirer's name says whether this is PE
            if buyer and PE.search(buyer) and lemma not in ("sell", "divest", "offload"):
                ev["category"] = "PE buyout"
            m = MONEY.search(text)
            ev["amount"] = m.group(0) if m else ""
            if lemma == "stake":
                ev["object"] = _prep_obj(tok, ("in",))[:80] or ev["object"]
        elif cat == "Leadership change":
            out_words = {"step", "resign", "exit", "depart", "quit", "retire", "leave", "oust", "sack", "fire"}
            ev["direction"] = "out" if lemma in out_words else "in"
            if lemma == "step" and not re.search(r"\bstep(s|ped|ping)? (down|aside|back)\b", window, re.I):
                continue
            if not (EXEC.search(window) or EXEC.search(text)):
                continue                                             # a leadership change names a role: "named a Leader in Gartner" is not one
            ex = EXEC.search(window) or EXEC.search(text)
            ev["exec"] = ex.group(0) if ex else ""
            ev["person"] = next((e.text for e in sent.ents if e.label_ == "PERSON"), "")
        # --- certainty
        if DENIED.search(text):
            ev["certainty"] = "denied"
        elif COMPLETED.search(text) and lemma not in ("close", "closure"):
            ev["certainty"] = "completed"
        elif POSSIBLE.search(text) or any(c.dep_ == "aux" and c.lemma_ in ("could", "may", "might", "would") for c in tok.children):
            ev["certainty"] = "possible"
        elif tok.tag_ == "VB" and tok.dep_ in ("xcomp", "ROOT", "advcl") and any(c.tag_ == "TO" for c in tok.children) \
                or re.search(r"\bto " + re.escape(tok.text.lower()) + r"\b", text.lower()):
            ev["certainty"] = "announced"
        else:
            ev["certainty"] = "reported"
        found.append(ev)
    # one event per (category, detail) in a sentence: keep the one that names a subject or object
    best = {}
    for e in found:
        k = (e["category"], e["detail"])
        if k not in best or (not (best[k]["subject"] or best[k]["object"]) and (e["subject"] or e["object"])):
            best[k] = e
    return list(best.values())


def analyse(title, summary, lead):
    """(entities, events) for one article: entities with offsets in the headline and lead, events with who-did-what."""
    nlp = _spacy()
    head = nlp(title or "")
    ents = [{**e, "in": "title"} for e in _spans(head)]
    events = []
    for sent in head.sents:
        events += _sentence_events(sent, "title")
    body = " ".join(x for x in (summary, lead) if x)
    if body:
        doc = nlp(body)
        ents += [{**e, "in": "lead"} for e in _spans(doc)]
        for i, sent in enumerate(doc.sents):
            if i >= 6:
                break
            events += _sentence_events(sent, "lead")
    return ents, events


# ================================================================ company-level checks (at export, no model needed)
def _norm_words(s):
    s = re.sub(r"['’]s", "", (s or "").lower())                    # "Canva's" is Canva
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
    """How the company name sits in the text. names: regexes for the name and aliases (match.Matcher.names).
    Returns (verdict, note): 'org' (named as an organisation), 'ok' (no objection), or a reject reason:
      compound     part of a hyphenated word ("Big Post-Launch")
      longer name  inside a longer name, only when that longer name recurs across the company's articles (recurring),
                   carries another company's suffix ("Array Technologies"), or is a person or place ("Lindsay Clancy's",
                   "Accora Village"). A descriptor ("Armstrong Ambulance Service") or headline-case NER noise ("Canva Offers
                   Layoff Package") is not held against the article.
      wrong type   a one-word name tagged as a person or place ("Clancy", "Barga"); two-word firms are often named after
                   people (Shaw Gibbs). Never when the name is the actor of a business event (is_actor).
      strict       small companies only (match.Matcher.small): the compound, longer-name and type rules. Well-known companies
                   skip them: "Ex-Canva staff" and Reuters' "BRIEF-Atlassian Q1 Revenue" are real news, their names are tagged inconsistently ("Xero" as a product, "Xero Limited"
                   as a person) and a longer name is usually their own product ("Xero Launches", "Canva Education")."""
    known = {" ".join(_norm_words(n)) for n in known_names if n}
    verdict = ("ok", "")
    for field, text in (("lead", lead), ("title", title)):
        if not text:
            continue
        low = text.lower()
        for p in names:
            m = p.search(low)
            if not m:
                continue
            a, b = m.span()
            if strict and (re.match(r"-\w", text[b:b + 2]) or re.search(r"\w-$", text[:a])):
                return "compound", f"part of a hyphenated word in the {field}: '{text[max(0, a - 12):b + 12].strip()}'"
            ents = [e for e in entities if e["in"] == field and e["start"] <= a and e["end"] >= b]
            if not ents:
                continue
            e = ents[0]
            norm = " ".join(_norm_words(e["text"]))
            extra = [w for w in _norm_words(e["text"]) if w not in _norm_words(text[a:b])]
            if extra and norm not in known:
                if strict and (norm in recurring or set(extra) & ORG_SUFFIX or e["label"] in BAD_TYPES):
                    return "longer name", f"part of a longer name in the {field}: '{e['text']}'"
                continue                                             # one-off longer ORG in a headline: no opinion
            if strict and e["label"] in BAD_TYPES and not extra and one_word and not is_actor:
                return "wrong type", f"named as {BAD_TYPES[e['label']]} in the {field} ('{e['text']}')"
            if e["label"] == "ORG" or is_actor:
                verdict = ("org", f"named as an organisation in the {field}")
    return verdict


def role_of(names, event):
    """The company's role in an event, from where its name appears: subject / object / agent."""
    def has(s):
        return bool(s) and any(p.search(s.lower()) for p in names)
    subj, obj, agent = has(event.get("subject")), has(event.get("object")), has(event.get("agent"))
    cat, passive, detail = event["category"], event.get("passive"), event.get("detail")
    if cat in ("M&A", "PE buyout"):
        if detail == "sale":
            return "seller" if subj else "buyer" if agent or has(event.get("agent")) else "asset sold" if obj else ""
        if passive:
            return "target" if subj else "acquirer" if agent else ""
        return "acquirer" if subj else "target" if obj else ""
    if cat == "Funding round":
        return "investor" if agent else "raising" if subj or obj else ""
    if cat == "Leadership change":
        return "employer" if subj or obj else ""
    if cat in ("Restructuring", "Expansion / new office"):
        return "subject" if subj or obj or agent else ""
    return ""


def confident(event, role, title=""):
    """May this event set the category of an article the rules called 'Other'? Only with concrete detail and the company in the
    leading role. Spot checks: "expands partnership" (not an office), a share buyback (not a funding round) and "named a Leader
    in Gartner" all produced an event with no such detail."""
    cat, d = event["category"], event
    if not role or d.get("certainty") in ("possible", "denied"):
        return False
    if cat == "Restructuring":
        return bool(d["count"] or d["pct"]) or d["detail"] == "insolvency"
    if cat == "Expansion / new office":
        return d["detail"] in ("office", "offices", "hq", "headquarters", "hub", "facility", "store", "stores", "centre", "center", "campus",
                               "warehouse", "depot", "clinic", "branch", "branches", "plant", "factory") or bool(d["place"] and d["detail"] != "expansion")
    if cat == "Funding round":
        return bool(d["amount"]) and bool(re.search(r"(funding|series [a-e]|seed|round|financing|raises?|raised|secures?)", title, re.I))             and not re.search(r"(buy-?back|share|dividend|tax|valuation)", title, re.I)
    if cat in ("M&A", "PE buyout"):
        return role in ("acquirer", "target", "buyer", "seller") and d["detail"] in ("acquisition", "merger", "sale") and bool(d["object"] or d["agent"])
    if cat == "Leadership change":
        return bool(d["exec"] and d["person"])
    return False


def describe(event, role=""):
    """One line for the sheet: 'acquirer of Calculo Tax Audit (completed)', '1,271 jobs (22%) cut', 'new office in Manila'."""
    cat, d = event["category"], event
    if cat in ("M&A", "PE buyout"):
        other = d["agent"] if role in ("target", "asset sold", "seller") and d["agent"] else d["object"] if role in ("acquirer", "buyer", "") else d["subject"]
        s = f"{role or d['detail']}" + (f" · {other}" if other else "")
    elif cat == "Funding round":
        s = "raised " + (d["amount"] or "funding") + (f" from {d['agent']}" if d["agent"] else "")
    elif cat == "Restructuring":
        s = d["detail"] + (f" · {d['count']} jobs" if d["count"] else "") + (f" ({d['pct']})" if d["pct"] else "")
    elif cat == "Expansion / new office":
        s = d["detail"] + (f" in {d['place']}" if d["place"] else "")
    elif cat == "Leadership change":
        s = (d["exec"] or "executive") + (" out" if d["direction"] == "out" else " in") + (f" · {d['person']}" if d["person"] else "")
    else:
        s = cat
    if d.get("certainty") and d["certainty"] != "reported":
        s += f" ({d['certainty']})"
    return s[:120]


# ================================================================ embeddings
def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def unpack(blob):
    import numpy as np
    return np.frombuffer(blob, dtype="float32") if blob else None


def cosine(a, b):
    import numpy as np
    if a is None or b is None:
        return None
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / d) if d else None


def company_vector(card, company):
    """Embedding of what the company is: website description + keywords + industry + trading names."""
    parts = [card.get("description", ""), " ".join(card.get("keywords", [])), " ".join(card.get("alt_names", [])[:5]),
             getattr(company, "industry", "") or ""]
    text = " ".join(p for p in parts if p).strip()
    return _st().encode([text])[0] if text else None


def story_groups(rows, vectors):
    """Group rows (dicts with _key, published_at) that are the same story: cosine >= STORY_SIM within STORY_DAYS.
    Returns {_key: story_id}. Greedy, per call (caller passes one company's rows)."""
    ids, reps = {}, []                                             # reps: (story_id, vector, date)
    for r in sorted(rows, key=lambda x: x["published_at"]):
        v = vectors.get(r["_key"])
        d = dt.date.fromisoformat(r["published_at"][:10])
        sid = None
        if v is not None:
            for rid, rv, rd in reps:
                if abs((d - rd).days) <= STORY_DAYS and (cosine(v, rv) or 0) >= STORY_SIM:
                    sid = rid
                    break
        if sid is None:
            sid = len(reps) + 1
            reps.append((sid, v, d))
        ids[r["_key"]] = sid
    return ids


# ================================================================ run
def ensure_tables(store):
    with store.lock, store.db:
        store.db.executescript(TABLES)


def load(store, keys=None):
    """{dedupe_key: row dict} of cached results (entities/events/zeroshot parsed, embedding as numpy)."""
    ensure_tables(store)
    out = {}
    for key, th, ver, ents, evs, zs, zscope, emb in store.db.execute(
            "SELECT dedupe_key, text_hash, model_version, entities, events, zeroshot, zs_scope, embedding FROM nlp_articles"):
        if keys is not None and key not in keys:
            continue
        out[key] = {"text_hash": th, "version": ver, "entities": json.loads(ents or "[]"), "events": json.loads(evs or "[]"),
                    "zeroshot": json.loads(zs) if zs else None, "zs_scope": zscope, "embedding": unpack(emb)}
    return out


def run(db_path, scope="all", stages=("entities", "events", "embed", "zeroshot"), zs_all=False, limit=None, log=print):
    from .store import Store
    store = Store(db_path)
    ensure_tables(store)
    arts = inputs(store, scope)
    have = load(store, set(arts))
    todo = [(k, v) for k, v in arts.items()
            if k not in have or have[k]["text_hash"] != text_hash(*v[:3]) or have[k]["version"] != MODEL_VERSION]
    todo = todo[:limit] if limit else todo
    log(f"NLP: {len(arts)} stories in scope '{scope}', {len(todo)} to (re)process · stages {', '.join(stages)}")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    t0 = dt.datetime.now()

    if "entities" in stages or "events" in stages:
        for i, (key, (title, summary, lead, sc, matched)) in enumerate(todo, 1):
            ents, evs = analyse(title, summary, lead)
            with store.lock, store.db:
                store.db.execute("""INSERT INTO nlp_articles(dedupe_key, text_hash, model_version, computed_at, entities, events, zeroshot, zs_scope, embedding)
                    VALUES(?,?,?,?,?,?,NULL,NULL,NULL) ON CONFLICT(dedupe_key) DO UPDATE SET text_hash=excluded.text_hash,
                    model_version=excluded.model_version, computed_at=excluded.computed_at, entities=excluded.entities, events=excluded.events,
                    zeroshot=CASE WHEN nlp_articles.text_hash=excluded.text_hash THEN nlp_articles.zeroshot END,
                    zs_scope=CASE WHEN nlp_articles.text_hash=excluded.text_hash THEN nlp_articles.zs_scope END,
                    embedding=CASE WHEN nlp_articles.text_hash=excluded.text_hash THEN nlp_articles.embedding END""",
                                 (key, text_hash(title, summary, lead), MODEL_VERSION, now, json.dumps(ents, ensure_ascii=False),
                                  json.dumps(evs, ensure_ascii=False)))
            if i % 500 == 0:
                log(f"  entities+events {i}/{len(todo)} · {(dt.datetime.now() - t0).seconds}s")
        log(f"  entities+events done: {len(todo)} stories · {(dt.datetime.now() - t0).seconds}s")

    if "embed" in stages:
        rows = [(k, " ".join(x for x in v[:3] if x)) for k, v in arts.items()
                if k in {t[0] for t in todo} or have.get(k, {}).get("embedding") is None]
        if rows:
            st = _st()
            for i in range(0, len(rows), 256):
                chunk = rows[i:i + 256]
                vecs = st.encode([t for _, t in chunk], batch_size=64)
                with store.lock, store.db:
                    store.db.executemany("UPDATE nlp_articles SET embedding=? WHERE dedupe_key=?", [(_pack(v), k) for (k, _), v in zip(chunk, vecs)])
            log(f"  embeddings: {len(rows)} stories · {(dt.datetime.now() - t0).seconds}s")

    if "zeroshot" in stages:
        rows = [(k, v) for k, v in arts.items() if (zs_all or v[4])
                and (k in {t[0] for t in todo} or have.get(k, {}).get("zeroshot") is None or have[k].get("zs_scope") != v[3])]
        if rows:
            log(f"  zero-shot on {len(rows)} stories (matched ones{' and all others' if zs_all else ''}) · ~1 s each on a laptop CPU")
            zs = _zs()
            for i in range(0, len(rows), 16):
                chunk = rows[i:i + 16]
                by_scope = defaultdict(list)
                for k, v in chunk:
                    by_scope[v[3]].append((k, v))
                for sc, items in by_scope.items():
                    labels = list(ZS_COMPANY if sc == "company" else ZS_SEGMENT)
                    texts = [" ".join(x for x in v[:3] if x)[:600] for _, v in items]
                    res = zs(texts, candidate_labels=labels, hypothesis_template=HYPOTHESIS, multi_label=True, batch_size=16)
                    res = res if isinstance(res, list) else [res]
                    with store.lock, store.db:
                        store.db.executemany("UPDATE nlp_articles SET zeroshot=?, zs_scope=? WHERE dedupe_key=?",
                                             [(json.dumps({l: round(s, 3) for l, s in zip(r["labels"], r["scores"])}), sc, k)
                                              for (k, _), r in zip(items, res)])
                if (i // 16) % 10 == 0:
                    log(f"  zero-shot {min(i + 16, len(rows))}/{len(rows)} · {(dt.datetime.now() - t0).seconds}s")
            log(f"  zero-shot done · {(dt.datetime.now() - t0).seconds}s")
    return len(todo)


def zs_best(zs, scope="company"):
    """(category, detail, label, score) of the best zero-shot label, or (None, ..) below ZS_MIN."""
    if not zs:
        return None, "", "", 0.0
    label, score = max(zs.items(), key=lambda kv: kv[1])
    if score < ZS_MIN:
        return None, "", label, score
    if scope == "company":
        cat, detail = ZS_COMPANY.get(label, ("Other / Unclassified", ""))
        return cat, detail, label, score
    return ZS_SEGMENT.get(label), "", label, score


# ================================================================ labelling sheet + training
LABEL_COLS = ["dedupe_key", "company_id", "company_name", "bucket", "title", "lead", "url", "rule_category", "nlp_event", "zs_label", "zs_score",
              "entity_check", "rule_verdict", "about_company", "category", "notes"]
CATEGORIES = ["Funding round", "PE buyout", "M&A", "Expansion / new office", "Restructuring", "Leadership change", "Other / Unclassified"]


def label_sheet(events, review, out_path, n=200, seed=7):
    """A CSV to label by hand: about_company (yes/no) and category. Rows are sampled where the signals disagree first,
    then at random, so the labels teach the combiner the most."""
    import random
    random.seed(seed)
    rows = [{**e, "rule_verdict": "counted"} for e in events] + [{**r, "rule_verdict": "review"} for r in review]
    for r in rows:
        zs_cat = r.get("zs_category") or ""
        ev = r.get("nlp_event") or ""
        rc = r.get("category") or ""
        ec = (r.get("nlp_entity_check") or "").split(":")[0]
        if r["rule_verdict"] == "counted" and ec not in ("", "ok", "org"):
            r["bucket"] = "counted but entity check objects"
        elif r["rule_verdict"] == "review" and ec == "org" and "common name" in (r.get("check") or ""):
            r["bucket"] = "review but named as an organisation"
        elif rc == "Other / Unclassified" and (zs_cat and zs_cat != rc or ev):
            r["bucket"] = "rules say Other, NLP sees an event"
        elif rc != "Other / Unclassified" and ev and ev.split(":")[0] != rc:
            r["bucket"] = "rules and NLP disagree on the event"
        else:
            r["bucket"] = "agree"
    by = defaultdict(list)
    for r in rows:
        by[r["bucket"]].append(r)
    picked = []
    per = max(10, n // max(1, len(by)))
    for b, rs in sorted(by.items(), key=lambda kv: kv[0] == "agree"):
        random.shuffle(rs)
        picked += rs[:per]
    picked = picked[:n]
    import csv
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_COLS, extrasaction="ignore")
        w.writeheader()
        for r in picked:
            w.writerow({**r, "dedupe_key": r.get("_key", ""), "company_name": r.get("company_name", ""), "lead": (r.get("lead") or "")[:300], "rule_category": r.get("category", ""),
                        "zs_label": r.get("zs_label", ""), "entity_check": r.get("nlp_entity_check", ""), "about_company": "", "category": "", "notes": ""})
    return Counter(r["bucket"] for r in picked)


def train(labels_path, features_by_key, log=print):
    """From a labelled sheet: (1) a logistic combiner for about_company over the evidence features the export computes,
    (2) a SetFit classifier for the category when every class has 8+ examples. Saves to data/models/. Returns a report."""
    import csv
    rows = [r for r in csv.DictReader(open(labels_path, encoding="utf-8-sig")) if (r.get("about_company") or "").strip()]
    report = {"labelled": len(rows)}
    if len(rows) < 20:
        report["note"] = f"only {len(rows)} labelled rows; label at least 20 (ideally 200) before training"
        return report
    os.makedirs(MODEL_DIR, exist_ok=True)
    # ---- 1. about-company combiner
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict
    X, y, keys = [], [], []
    for r in rows:
        f = features_by_key.get((r["company_id"], r["dedupe_key"]))
        if f is None:
            continue
        X.append(f)
        y.append(1 if r["about_company"].strip().lower().startswith("y") else 0)
        keys.append(r["dedupe_key"])
    X, y = np.array(X, dtype=float), np.array(y)
    if len(set(y)) == 2 and len(y) >= 20:
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        pred = cross_val_predict(clf, X, y, cv=min(5, int(min(Counter(y).values()))))
        tp, fp, fn = int(((pred == 1) & (y == 1)).sum()), int(((pred == 1) & (y == 0)).sum()), int(((pred == 0) & (y == 1)).sum())
        report["about_company"] = {"n": int(len(y)), "positives": int(y.sum()), "cv_precision": round(tp / max(tp + fp, 1), 3),
                                   "cv_recall": round(tp / max(tp + fn, 1), 3)}
        clf.fit(X, y)
        import pickle
        pickle.dump({"model": clf, "features": FEATURE_NAMES, "trained_at": dt.datetime.now().isoformat(timespec="seconds"), "n": int(len(y))},
                    open(os.path.join(MODEL_DIR, "about_company.pkl"), "wb"))
        report["about_company"]["weights"] = {n: round(float(w), 2) for n, w in zip(FEATURE_NAMES, clf.coef_[0])}
    else:
        report["about_company"] = f"need both yes and no labels (have {dict(Counter(y))})"
    # ---- 2. SetFit category classifier
    cat_rows = [r for r in rows if (r.get("category") or "").strip() in CATEGORIES and r["about_company"].strip().lower().startswith("y")]
    counts = Counter(r["category"].strip() for r in cat_rows)
    report["category_counts"] = dict(counts)
    if len(counts) >= 2 and min(counts.values()) >= 8:
        from datasets import Dataset
        from setfit import SetFitModel, Trainer, TrainingArguments
        texts = [f"{r['title']}. {r.get('lead', '')}"[:600] for r in cat_rows]
        labels = [r["category"].strip() for r in cat_rows]
        ds = Dataset.from_dict({"text": texts, "label": labels})
        model = SetFitModel.from_pretrained(ST_MODEL, labels=sorted(set(labels)))
        args = TrainingArguments(batch_size=16, num_epochs=1, num_iterations=10)
        trainer = Trainer(model=model, args=args, train_dataset=ds)
        trainer.train()
        model.save_pretrained(os.path.join(MODEL_DIR, "setfit_category"))
        # leave-out estimate: train on 80%, test on 20%
        from sklearn.model_selection import train_test_split
        tr, te = train_test_split(list(range(len(texts))), test_size=0.2, random_state=1, stratify=labels)
        m2 = SetFitModel.from_pretrained(ST_MODEL, labels=sorted(set(labels)))
        Trainer(model=m2, args=args, train_dataset=Dataset.from_dict({"text": [texts[i] for i in tr], "label": [labels[i] for i in tr]})).train()
        pred = m2.predict([texts[i] for i in te])
        acc = sum(p == labels[i] for p, i in zip(pred, te)) / len(te)
        report["category"] = {"n": len(texts), "holdout_accuracy": round(acc, 3), "classes": sorted(set(labels))}
    else:
        report["category"] = f"need 8+ labelled 'yes' rows per category to train SetFit (have {dict(counts)})"
    return report


FEATURE_NAMES = ["identity_points", "entity_org", "entity_objects", "mention_count", "name_in_title", "fit", "ambiguous", "one_word", "text_read",
                 "zs_any_event", "passing_mention"]


def features(pts, entity_verdict, mentions, in_title, fit, ambiguous, one_word, text_read, zs_any, passing):
    return [pts, 1 if entity_verdict == "org" else 0, 1 if entity_verdict not in ("ok", "org", "") else 0, min(mentions, 10), 1 if in_title else 0,
            fit if fit is not None else 0.0, 1 if ambiguous else 0, 1 if one_word else 0, 1 if text_read else 0, 1 if zs_any else 0, 1 if passing else 0]


def about_company_model():
    p = os.path.join(MODEL_DIR, "about_company.pkl")
    if os.path.exists(p):
        import pickle
        return pickle.load(open(p, "rb"))
    return None


def category_model():
    p = os.path.join(MODEL_DIR, "setfit_category")
    if os.path.isdir(p):
        from setfit import SetFitModel
        return SetFitModel.from_pretrained(p)
    return None


# ================================================================ headline event classifier (trained on written examples)
EVENT_MODEL = "sentence-transformers/all-mpnet-base-v2"     # 12 ms per headline on a laptop CPU; best of three models tried
EVENT_VETO, EVENT_ADD, EVENT_OVERRIDE = 0.8, 0.75, 0.9
# The classifier may add an event the rules missed, except Expansion: on unseen companies its Expansion additions were mostly
# wrong ("rolling out delivery robots across the UK", "adopts software across Australian sites").
EVENT_ADD_SKIP = {"Expansion / new office"}
PROBS_TABLE = """
CREATE TABLE IF NOT EXISTS nlp_event_probs (
  company_id TEXT NOT NULL, dedupe_key TEXT NOT NULL, version TEXT, probs TEXT, PRIMARY KEY (company_id, dedupe_key));
"""


class EventClassifier:
    """Logistic regression over sentence embeddings of headlines, trained on the hand-written examples in event_examples.py
    (and nothing else: on 672 labelled stories, adding the real labels did not generalise across companies).
    The company name is replaced by "Acme" before embedding, so the model reads the event, not the brand."""

    def __init__(self):
        import pickle
        import random
        from .event_examples import CITIES, EXAMPLES, NAMES, PEOPLE
        blob = json.dumps(EXAMPLES, sort_keys=True) + EVENT_MODEL
        self.version = hashlib.sha1(blob.encode()).hexdigest()[:10]
        path = os.path.join(MODEL_DIR, f"event_clf_{self.version}.pkl")
        self._st = None
        if os.path.exists(path):
            self.clf = pickle.load(open(path, "rb"))
            return
        from sklearn.linear_model import LogisticRegression
        rnd = random.Random(0)
        X, y = [], []
        for cat, templates in EXAMPLES.items():
            for t in templates:
                for _ in range(4):
                    X.append(t.format(Co="Acme", Co2=rnd.choice(NAMES), P=rnd.choice(PEOPLE), City=rnd.choice(CITIES)))
                    y.append(cat)
        self.clf = LogisticRegression(max_iter=3000, C=10).fit(self._encode(X), y)
        os.makedirs(MODEL_DIR, exist_ok=True)
        pickle.dump(self.clf, open(path, "wb"))

    def _encode(self, texts):
        if self._st is None:
            from sentence_transformers import SentenceTransformer
            self._st = SentenceTransformer(EVENT_MODEL, device="cpu")
        return self._st.encode(texts, batch_size=64, normalize_embeddings=True)

    def probs(self, masked_titles):
        if not masked_titles:
            return []
        P = self.clf.predict_proba(self._encode(masked_titles))
        return [{c: round(float(v), 4) for c, v in zip(self.clf.classes_, p)} for p in P]


def mask_name(title, names):
    """The headline with the company name (any of the name regexes) replaced by 'Acme'."""
    out = title or ""
    for p in names:
        out = re.sub(p.pattern, "Acme", out, flags=re.I)
    return out


def event_probs(store, items):
    """{(company_id, dedupe_key): probs} for items [(company_id, dedupe_key, masked_title)], computed once and cached."""
    with store.lock, store.db:
        store.db.executescript(PROBS_TABLE)
    if "event_clf" not in _cache:
        _cache["event_clf"] = EventClassifier()
    clf = _cache["event_clf"]
    have = {(c, k): json.loads(p) for c, k, v, p in store.db.execute("SELECT company_id, dedupe_key, version, probs FROM nlp_event_probs")
            if v == clf.version}
    todo = [(c, k, t) for c, k, t in items if (c, k) not in have]
    if todo:
        for (c, k, _), p in zip(todo, clf.probs([t for _, _, t in todo])):
            have[(c, k)] = p
        with store.lock, store.db:
            store.db.executemany("INSERT OR REPLACE INTO nlp_event_probs VALUES(?,?,?,?)",
                                 [(c, k, clf.version, json.dumps(have[(c, k)])) for c, k, _ in todo])
    return have


def combine_event(rule_cat, probs, other="Other / Unclassified"):
    """(category, basis, confidence) from the keyword rules and the classifier: each can overrule the other when sure.
    Confidence, measured on two labelled sets (672 stories from the build companies; 193 from 12 unseen companies):
      high    rules and classifier agree            60 of 61 right, and 16 of 18 on unseen companies
      medium  rules say event, classifier not sure   7 of 14, and 2 of 9
      low     classifier only                        9 of 10, and 3 of 5"""
    top, score = max(probs.items(), key=lambda kv: kv[1])
    if rule_cat != other:
        if probs.get(other, 0) >= EVENT_VETO and probs.get(rule_cat, 0) < 0.1:
            return other, "classifier veto", ""                      # the rules matched a word; the headline is about something else
        if top not in (other, rule_cat) and score >= EVENT_OVERRIDE:
            return top, "classifier", "medium"                       # "appoints new executives as part of leadership restructure"
        return rule_cat, "rules", "high" if top == rule_cat else "medium"
    if top != other and score >= EVENT_ADD and top not in EVENT_ADD_SKIP:
        return top, "classifier", "low"
    return other, "", ""
