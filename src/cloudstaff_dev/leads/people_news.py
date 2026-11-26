"""People in the news: a lead's people (Apollo contacts, owners and directors not in Apollo) found by name in the
articles the scraper stored for that lead (headline + summary + full text), with what is worth using from each mention.

Review output only for now (nothing is scored or shown on the dashboard):
    python -m cloudstaff_dev.leads.people_news apollo_emea
-> <grades>/people_in_news_<list>_<date>.xlsx with sheets
    People    one row per person: best snippet, title the articles give them, how many articles
    Mentions  one row per person x article: type, quote, topic, snippet, the text around the name, the full article text
    Notes     how each column is worked out

Reads the grades JSON (run `grade` first) for the people, and <work>/news.db for the articles. Local only.
Personal data: only the name, the title an article states and the article's own words are kept.
"""

import argparse
import datetime as dt
import json
import re
import sqlite3
from collections import Counter, defaultdict
from urllib.parse import urlparse

import pandas as pd

from .config import L, use
from .rules import OWN_SITE_SOURCE

HONORIFIC = r"(?:mr|mrs|ms|miss|mx|dr|sir|dame|lord|lady|prof|professor|rev|cllr)\.?"
POSTNOMINAL = r"(?:mbe|obe|cbe|frcn|rgn|rmn|phd|msc|ba|bsc)"
ROLE_WORDS = (r"chief [a-z]+ officer|ceo|cfo|coo|cto|cio|ciso|cmo|cro|chro|managing director|md|founder|co-founder|owner|"
              r"chair(?:man|woman|person)?|president|director|partner|head|manager|lead|principal|proprietor|"
              r"vice[- ]president|vp|officer|nominated individual|registered manager|matron|trustee|executive")
ROLE = re.compile(rf"\b({ROLE_WORDS})\b", re.I)
SAY = r"(?:said|says|say|commented|comments|added|adds|explained|explains|noted|notes|told|stated|states|remarked|according to)"

# mention types, in the order they are preferred when picking the best mention (first = most useful)
TYPES = [
    ("Departure", r"\b(steps? down|stepped down|stepping down|leav(es|ing)|left (the|his|her|their) (role|post|company|business)|"
                  r"departs?|departure|retir(es|ed|ing|ement)|succeeded by|replac(es|ed|ing))\b"),
    ("Appointment", r"\b(appoint(s|ed|ment)?|joins|joined|joining|promot(ed|ion)|named (as )?(new|the)|welcomes?|new (ceo|cfo|coo|"
                    r"managing director|chief|head|director|chair)|has hired|takes? (over|the helm))\b"),
    ("Ownership / deal", r"\b(acqui(res?|red|sition)|bought|sold|sale of|buy-?out|management buyout|mbo|invest(s|ed|ment|or)|private equity|"
                         r"stake|family[- ]owned|owned by|owner of|founded|co-?founded|merger|portfolio)\b"),
    ("Award", r"\b(awards?|shortlisted|finalist|winner|won (the|a|an)|recogni[sz]ed|honoured|accolade)\b"),
]
TYPE_RANK = {"Quote": 0, "Departure": 1, "Appointment": 2, "Ownership / deal": 3, "Award": 4, "Author": 5, "Mention": 6}

# topics worth a conversation for Cloudstaff (offshore staffing): keyword lists, so every tag can be traced back
THEMES = {
    "Offshoring / outsourcing": r"\b(offshor\w*|outsourc\w*|overseas (staff|team|recruit\w*)|international recruit\w*|nearshor\w*|bpo)\b",
    "Staffing / recruitment": r"\b(recruit\w*|hiring|hire[sd]?|vacanc\w*|retention|retain\w*|shortage\w*|workforce|staffing|talent|skills? gap|"
                              r"agency staff|turnover|headcount|team (of|has grown|growth))\b",
    "Costs / efficiency": r"\b(costs?|budget\w*|inflation|wages?|national living wage|national insurance|margins?|efficien\w*|"
                          r"productiv\w*|afford\w*|funding pressure\w*|savings?)\b",
    "Growth / expansion": r"\b(expan\w*|growth|growing|grow|new (home|office|site|service|location|market)s?|opening|opens|scal(e|ing)|"
                          r"acqui\w*|launch\w*)\b",
    "Technology / AI": r"\b(ai|artificial intelligence|automat\w*|digital\w*|software|technolog\w*|data|cloud|platform)\b",
    "Compliance / quality": r"\b(cqc|regulat\w*|complian\w*|inspection\w*|rated (good|outstanding)|quality|standards|ofsted|"
                            r"gdpr|iso ?27001|cyber essentials)\b",
}
THEME_BONUS = {"Offshoring / outsourcing": 2, "Staffing / recruitment": 1.5, "Costs / efficiency": 1.5, "Growth / expansion": 1}

SOURCE_LABEL = {"own": "Own website", "investor": "Owner / investor site", "press": "Third-party press"}


# ---------------------------------------------------------------- text helpers
def clean(s):
    s = str(s or "").replace(" ", " ").replace("�", "'")
    s = re.sub(r"[‘’‛]", "'", s)
    s = re.sub(r"[“”„]", '"', s)
    return re.sub(r"[ \t]+", " ", s)


def sentences(text):
    """(start, end, sentence) spans. Splits on . ! ? (and line breaks) followed by a capital or a quote."""
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?\"'])\s+(?=[\"'A-Z(])|\n+", text):
        if m.start() > start:
            out.append((start, m.start(), text[start:m.start()].strip()))
        start = m.end()
    if start < len(text):
        out.append((start, len(text), text[start:].strip()))
    return [s for s in out if s[2]]


def name_parts(name):
    w = re.sub(rf"^{HONORIFIC}\s+", "", str(name or "").strip(), flags=re.I)
    w = [x for x in re.split(r"[\s]+", w) if x and not re.fullmatch(POSTNOMINAL, x.strip(",."), re.I)]
    return (w[0], w[-1]) if len(w) >= 2 else None


def name_pattern(first, last):
    """'Jane Smith', 'Dr Jane A. Smith', 'Jane Anne Smith-Jones' style matches of first ... last (at most 2 words between)."""
    f, l = re.escape(first), re.escape(last)
    return re.compile(rf"\b{f}\b(?:\s+[A-Z][\w'.-]*){{0,2}}\s+{l}\b", re.I)


def domain(u):
    try:
        d = urlparse(u if "//" in str(u) else f"//{u}").netloc.lower()
    except ValueError:
        return ""
    return d[4:] if d.startswith("www.") else d


# ---------------------------------------------------------------- one mention
def stated_title(text, m, company_names):
    """The title the article gives the person: 'Jane Smith, Chief Executive of Acme,' / 'Acme CEO Jane Smith'."""
    after = text[m.end():m.end() + 160]
    a = re.match(r"\s*(?:\((?P<p>[^)]{2,80})\)|,\s*(?:the\s+)?(?P<t>[^,.;:\"()]{2,110}))", after)
    cand = None
    if a:
        cand = (a.group("p") or a.group("t") or "").strip()
    if not cand or not ROLE.search(cand):
        before = re.split(r"[.!?\n:]\s", text[max(0, m.start() - 90):m.start()])[-1]   # stay inside the sentence
        b = re.search(rf"((?:[A-Z][\w&'.-]*\s+){{0,5}}(?:{ROLE_WORDS})(?:\s+(?:and|&)\s+(?:{ROLE_WORDS}))?)\s*,?\s*$", before, re.I)
        cand = b.group(1).strip() if b else None
    if not cand or not ROLE.search(cand) or len(cand.split()) > 14:
        return None, None
    org = None
    o = re.search(r"\b(?:of|at|for)\s+(?:the\s+)?([A-Z][\w&'.-]*(?:\s+(?:[A-Z][\w&'.-]*|&|and|of))*)", cand)
    if o:
        org = re.sub(r"\s+(of|and|&)$", "", o.group(1).strip())
    elif company_names:                                           # 'Acme CEO Jane Smith'
        for n in company_names:
            if n and n.lower() in cand.lower():
                org = n
                break
    cand = re.sub(r"^(?:for|by|and|with|from|as)\s+", "", re.sub(r"\s+", " ", cand), flags=re.I)   # 'For home manager' -> 'home manager'
    return cand, org


QUOTED = re.compile(r'"([^"]{20,900})"')
SAY_RE = re.compile(rf"\b{SAY}\b", re.I)


def quote_for(text, spans, k, surname):
    """A quote attributed to the person in sentence k (which names them):
    - quoted words that start in sentence k ('Jane Smith said: "We ... ' may run on past the sentence end);
    - after an attribution ending in ':' the next sentence;
    - the quote that ends just before it ('"..." Smith said.' / '"..." - Jane Smith, Owner');
    - else the sentence itself as reported speech ('Smith said the move would ...')."""
    a, b, s = spans[k]
    said = bool(SAY_RE.search(s))
    # '... Social Care." \u2013 Karim Nanji, Proprietor' (quote closed by a dash attribution inside this sentence)
    j = text.rfind('"', a, b)
    if j != -1 and re.match(r'"\s*[-\u2013\u2014]\s*', text[j:j + 6]) and re.search(rf"\b{re.escape(surname)}\b", text[j:b], re.I):
        o = text.rfind('"', max(0, j - 1200), j)
        if o != -1 and j - o > 25:
            return text[o + 1:j]
    dash = bool(re.match(r"\s*[-\u2013\u2014]\s*[A-Z]", s))
    if not (said or dash):
        return None
    if said and '"' in s:
        o = a + text[a:b].index('"')
        c = text.find('"', o + 1, o + 1200)
        if c != -1 and c - o > 25:
            return text[o + 1:c]
    if said and s.rstrip().endswith(":"):
        m = re.search(r'"([^"]{20,900})"', text[b:b + 700])          # the first quote after 'said:'
        if m:
            return m.group(1)
        if k + 1 < len(spans):
            return spans[k + 1][2]
    head = text[max(0, a - 1200):a].rstrip()
    if re.search(r'[.,!?]?"[,]?$', head):
        q = head.rstrip(",")[:-1]
        o = q.rfind('"')
        if o != -1 and len(q) - o > 22:
            return q[o + 1:]
    if said and len(s) > 60 and re.search(rf"\b{re.escape(surname)}\b[^.]{{0,40}}\b{SAY}\b|\b{SAY}\b[^.]{{0,40}}\b{re.escape(surname)}\b", s, re.I):
        return s
    return None


def find_mentions(person, art, company_names, lead_domains):
    """Every place the person is named in one article -> one summary row (or None)."""
    parts = name_parts(person["name"])
    if not parts:
        return None
    first, last = parts
    head, summ, body = clean(art["title"]), clean(art["summary"]), clean(art["text"])
    text = "\n".join(x for x in (head, summ if summ and summ[:60] not in body else "", body) if x)
    pat = name_pattern(first, last)
    full = list(pat.finditer(text))
    if not full:
        return None
    spans = sentences(text)
    idx = lambda pos: next((k for k, (a, b, _) in enumerate(spans) if a <= pos < b), max(0, len(spans) - 1))
    # sentences about the person: the full-name ones, plus later surname-only ones (after the first full mention)
    hit = sorted({idx(m.start()) for m in full})
    first_pos = full[0].start()
    sur = re.compile(rf"\b{re.escape(last)}\b(?!['’]s\s+(?:company|business))", re.I)
    for k, (a, b, s) in enumerate(spans):
        if a > first_pos and k not in hit and sur.search(s) and len(last) > 2:
            hit.append(k)
    hit = sorted(set(hit))

    title, org = None, None
    for m in full:
        title, org = stated_title(text, m, company_names)
        if title:
            break

    quote, quote_k = None, None
    for k in hit:
        q = quote_for(text, spans, k, last)
        if q:
            quote, quote_k = re.sub(r"^[\s'\"]+|[\s'\",]+$", "", q), k
            break

    around = " ".join(spans[k][2] for k in sorted({j for k in hit for j in (k - 1, k, k + 1) if 0 <= j < len(spans)}))
    types = [t for t, p in TYPES if re.search(p, " ".join(spans[k][2] for k in hit), re.I)]
    if quote:
        types.insert(0, "Quote")
    author = str(art.get("author") or "")
    is_author = (pat.search(author) is not None) or bool(re.search(rf"\b{re.escape(first)}\s+{re.escape(last)}\s+is\s+(the\s+)?"
                                                                   rf"({ROLE_WORDS})", body[-600:], re.I))
    if is_author:
        types.append("Author")
    if not types:
        types = ["Mention"]
    kind = min(types, key=TYPE_RANK.get)

    theme_text = quote or around
    themes = [t for t, p in THEMES.items() if re.search(p, theme_text, re.I)]

    # snippet: the quote; else the best sentence about the person (+ the next one when short)
    if quote:
        snippet = quote if quote_k is not None and quote == spans[quote_k][2] else f'"{quote}"'
    else:
        typed = [k for k in hit if any(re.search(p, spans[k][2], re.I) for t, p in TYPES if t == kind)] or hit
        k = typed[0]
        snippet = spans[k][2]
        if len(snippet) < 140 and k + 1 < len(spans):
            snippet += " " + spans[k + 1][2]
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet) > 450:
        snippet = snippet[:447].rsplit(" ", 1)[0] + "..."

    d = domain(art["url"])
    if art["source"] == OWN_SITE_SOURCE or (d and any(d == x or d.endswith("." + x) for x in lead_domains if x)):
        src = "own"
    elif re.search(r"\bportfolio\b|/portfolio|private equity|\binvestments?\b|\bcapital\b", f"{d} {art['url']} {body[:1500]}", re.I) \
            and not any(x and x in text.lower() for x in ("news.", "times", "journal")):
        src = "investor" if re.search(r"capital|partners|equity|invest|portfolio", d) else "press"
    else:
        src = "press"

    in_headline = bool(pat.search(head) or re.search(rf"\b{re.escape(last)}\b", head, re.I))
    pos = max(0, first_pos - 700)
    context = text[pos:first_pos + 900].strip()
    if len(hit) > 1 and spans[hit[-1]][1] > first_pos + 900:
        context += " [...] " + " ".join(spans[k][2] for k in hit[-3:])
    return {
        "kind": kind, "all_types": ", ".join(dict.fromkeys(types)), "themes": ", ".join(themes),
        "quote": quote, "snippet": snippet, "title_in_article": title, "org_in_article": org,
        "in_headline": in_headline, "times_named": len(full) + max(0, len(hit) - len({idx(m.start()) for m in full})),
        "source_type": SOURCE_LABEL[src], "context": context,
        "full_text": text[:32000], "text_status": art["text_status"] or "not read",
    }


def score(r, as_of):
    """Higher = more worth showing: type, a relevant topic, third-party press, named in the headline, recency."""
    s = {"Quote": 5, "Departure": 4.5, "Appointment": 4.5, "Ownership / deal": 3.5, "Award": 3, "Author": 2, "Mention": 1}[r["kind"]]
    s += max((THEME_BONUS.get(t.strip(), 0) for t in str(r["themes"]).split(",")), default=0) if r["kind"] in ("Quote", "Author") else 0
    s += {"Third-party press": 1, "Owner / investor site": 0.5, "Own website": 0}[r["source_type"]]
    s += 0.5 if r["in_headline"] else 0
    s -= 1 if r["match_score"] is not None and r["match_score"] < 0.6 else 0
    try:
        age = (as_of - dt.date.fromisoformat(str(r["published"])[:10])).days
        s += 1 if age <= 90 else 0.5 if age <= 365 else 0
    except ValueError:
        pass
    return round(s, 2)


# ---------------------------------------------------------------- run
def people_by_lead(rows):
    out = {}
    for r in rows:
        ppl, seen = [], set()

        def add(name, src, **kw):
            p = name_parts(name)
            key = tuple(x.lower() for x in p) if p else None
            if key and key not in seen:
                seen.add(key)
                ppl.append({"name": name, "person_source": src, **kw})

        for c in r.get("contacts") or []:
            add(c["name"], "Apollo contact", apollo_title=c.get("title"), seniority=c.get("seniority"),
                owner_role=c.get("owner_role"), officer_role=c.get("officer_role"), email=c.get("email"), linkedin=c.get("linkedin"))
        for k, lab in (("owners_to_find", "Owner not in Apollo"), ("officers_to_find", "Director not in Apollo")):
            for x in json.loads(r.get(k) or "[]"):
                add(x["name"], lab, owner_role=(x.get("role") + (f" ({x['band']})" if x.get("band") else "")) if k == "owners_to_find" else None,
                    officer_role=x.get("officer") if k == "owners_to_find" else x.get("role"))
        out[r["account_id"]] = ppl
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("list", nargs="?", default="apollo_emea")
    ap.add_argument("--parents", action="store_true", default=True, help="also search the parent company's articles (marked)")
    a = ap.parse_args(argv)
    use(a.list)
    D = json.load(open(L.grades_json, encoding="utf-8"))
    as_of = dt.date.fromisoformat(str(D["meta"]["as_of"])[:10])
    rows = D["rows"]
    people = people_by_lead(rows)

    con = sqlite3.connect(str(L.jobs_db))
    con.row_factory = sqlite3.Row
    arts = defaultdict(list)
    for x in con.execute("""SELECT a.company_id, a.dedupe_key, a.source, a.title, a.url, a.publisher, a.published_at, a.summary,
                                   a.match_score, t.text, t.status AS text_status, t.author
                            FROM articles a LEFT JOIN article_texts t USING (company_id, dedupe_key)"""):
        arts[x["company_id"]].append(dict(x))

    out = []
    for r in rows:
        if r.get("grade") == "Duplicate":
            continue
        cid = "apollo-" + r["account_id"][3:]
        names = [n for n in {r.get("company_name"), r.get("apollo_name"), r.get("registered_name")} if n]
        lead_domains = {r.get("website_domain"), r.get("email_domain")}
        pools = [(cid, False)]
        if a.parents and r.get("parent_id"):
            pools.append((r["parent_id"], True))
        for pool, is_parent in pools:
            for art in arts.get(pool, []):
                for p in people.get(r["account_id"], []):
                    m = find_mentions(p, art, names + ([r.get("parent_name")] if is_parent else []), lead_domains)
                    if not m:
                        continue
                    out.append({
                        "company": r["company_name"], "account_id": r["account_id"], "grade": r.get("grade"),
                        "market": r.get("lead_list"), "ownership": r.get("ownership"),
                        "person": p["name"], "person_source": p["person_source"], "apollo_title": p.get("apollo_title"),
                        "owner_role": p.get("owner_role"), "officer_role": p.get("officer_role"),
                        "published": str(art["published_at"] or "")[:10], "headline": clean(art["title"]),
                        "publisher": art["publisher"], "url": art["url"], "match_score": art["match_score"],
                        "parent_article": r.get("parent_name") if is_parent else None, **m,
                    })
    if not out:
        raise SystemExit("no people found in the stored articles")
    df = pd.DataFrame(out)
    df["worth"] = [score(x, as_of) for x in df.to_dict("records")]
    words = lambda s: set(re.findall(r"[a-z]+", s.lower())) - {"of", "and", "the", "at", "for"} if isinstance(s, str) else set()
    df["title_differs"] = [bool(words(t) and words(at) and not words(t) & words(at))
                           for t, at in zip(df["title_in_article"], df["apollo_title"])]
    df = df.sort_values(["grade", "company", "person", "worth", "published"], ascending=[True, True, True, False, False])
    df["rank_for_person"] = df.groupby(["account_id", "person"]).cumcount() + 1
    df["show"] = df["rank_for_person"] <= 2

    # one row per person
    g = df.groupby(["account_id", "person"], sort=False)
    best = g.head(1).set_index(["account_id", "person"])
    ppl = pd.DataFrame({
        "company": best["company"], "grade": best["grade"], "market": best["market"],
        "person_source": best["person_source"], "apollo_title": best["apollo_title"],
        "owner_role": best["owner_role"], "officer_role": best["officer_role"],
        "title_from_news": g["title_in_article"].agg(lambda s: Counter(x for x in s if x).most_common(1)[0][0] if s.notna().any() else None),
        "org_from_news": g["org_in_article"].agg(lambda s: Counter(x for x in s if x).most_common(1)[0][0] if s.notna().any() else None),
        "articles": g.size(), "types": g["kind"].agg(lambda s: ", ".join(sorted(set(s), key=TYPE_RANK.get))),
        "themes": g["themes"].agg(lambda s: ", ".join(sorted({t.strip() for x in s for t in str(x).split(",") if t.strip()}))),
        "newest": g["published"].max(),
        "best_type": best["kind"], "best_snippet": best["snippet"], "best_source": best["source_type"],
        "best_date": best["published"], "best_headline": best["headline"], "best_url": best["url"], "worth": best["worth"],
        "right_person? (Y/N)": "", "useful? (Y/N)": "", "review note": "",
    }).reset_index()
    ppl = ppl.sort_values(["worth", "grade"], ascending=[False, True])

    mcols = ["company", "grade", "person", "person_source", "apollo_title", "title_in_article", "org_in_article", "title_differs",
             "kind", "all_types", "themes", "worth", "rank_for_person", "show", "snippet", "quote", "published", "headline",
             "publisher", "source_type", "parent_article", "url", "match_score", "in_headline", "times_named", "text_status",
             "owner_role", "officer_role", "market", "ownership", "account_id", "context", "full_text"]
    notes = pd.DataFrame([
        ("What this is", f"Every person we hold for a lead (Apollo contacts, owners and directors not in Apollo) found by full name in the "
                         f"articles stored for that lead (headline + summary + full text). Built {dt.date.today()} from {L.grades_json.name} "
                         f"(graded {as_of}) and the scraper's news.db. Review only: nothing here is scored or on the dashboard."),
        ("Matching", "First + last name, allowing up to two middle names/initials and Dr/Mr/MBE etc. After the first full-name mention, "
                     "sentences naming only the surname count too (for 'Smith added...'). Only the lead's own articles (and its parent's, "
                     "marked in parent_article) are searched, so a name match there is very likely the same person, but check common names."),
        ("kind", "Best type of mention, in this order: Quote (quoted words or 'said' attributed to them) > Departure > Appointment > "
                 "Ownership / deal > Award > Author (they wrote it / 'X is CEO of Y' footer) > Mention. all_types lists every type found."),
        ("themes", "Keyword topics in the quote (or the sentences about the person): " + "; ".join(THEMES)),
        ("title_in_article / org_in_article", "The title the article gives them ('Jane Smith, Chief Executive of Acme' or 'Acme CEO Jane Smith') "
                                              "and the organisation in it. An org other than the lead can mean a parent group. "
                                              "title_differs = shares no word with the Apollo title."),
        ("source_type", "Own website (the company's newsroom/blog or its domain), Owner / investor site (a capital/equity/portfolio domain), "
                        "Third-party press (anything else)."),
        ("worth", "Ranking only: type (Quote 5, Departure/Appointment 4.5, Ownership 3.5, Award 3, Author 2, Mention 1) + topic bonus for quotes "
                  "(offshoring 2, staffing/costs 1.5, growth 1) + third-party press 1 / investor site 0.5 + named in headline 0.5 + "
                  "published in 90 days 1 / a year 0.5 - 1 if the article's match score < 0.6. show = top 2 per person."),
        ("snippet", "The part worth using: the quote (with its attribution line), else the sentence about the person that shows the type "
                    "(plus the next sentence when short). Up to ~450 characters."),
        ("context / full_text", "context = ~700 characters before the first mention to ~900 after (plus later surname sentences). "
                                "full_text = headline + summary + article text (cut at 32,000 characters, Excel's cell limit). "
                                "text_status 'not read' / http_error / too_short = only the headline and summary were available."),
        ("Review columns", "People sheet: fill right person? / useful? / review note; these will tune the rules before anything goes on the page."),
    ], columns=["item", "detail"])

    xlsx = L.grades / f"people_in_news_{L.name}_{dt.date.today():%Y-%m-%d}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        ppl.to_excel(w, sheet_name="People", index=False)
        df[mcols].to_excel(w, sheet_name="Mentions", index=False)
        notes.to_excel(w, sheet_name="Notes", index=False)
        widths = {"People": {"company": 28, "person": 22, "apollo_title": 26, "title_from_news": 34, "org_from_news": 24, "types": 22,
                             "themes": 30, "best_snippet": 90, "best_headline": 50, "best_url": 30, "review note": 30},
                  "Mentions": {"company": 26, "person": 22, "apollo_title": 24, "title_in_article": 32, "org_in_article": 22, "kind": 14,
                               "all_types": 20, "themes": 28, "snippet": 90, "quote": 60, "headline": 50, "url": 30, "context": 90,
                               "full_text": 90},
                  "Notes": {"item": 30, "detail": 140}}
        from openpyxl.styles import Alignment, Font
        for sheet, ws in w.sheets.items():
            ws.freeze_panes = "C2" if sheet != "Notes" else "A2"
            hdr = [c.value for c in ws[1]]
            for c in ws[1]:
                c.font = Font(bold=True)
            for j, h in enumerate(hdr, 1):
                col = ws.cell(row=1, column=j).column_letter
                ws.column_dimensions[col].width = widths.get(sheet, {}).get(h, 14)
                wrap = h in ("best_snippet", "snippet", "quote", "detail", "context", "full_text", "best_headline", "headline")
                for cell in ws[col][1:]:
                    cell.alignment = Alignment(wrap_text=wrap, vertical="top")
                    if h in ("url", "best_url") and cell.value:
                        cell.hyperlink, cell.style = cell.value, "Hyperlink"
            if sheet != "Notes":
                ws.auto_filter.ref = ws.dimensions
                for i in range(2, ws.max_row + 1):
                    ws.row_dimensions[i].height = 90
    print(f"wrote {xlsx}\n  {len(ppl)} people at {ppl['company'].nunique()} companies, {len(df)} mentions")
    print("  people by source:", dict(Counter(ppl["person_source"])))
    print("  best type:", dict(Counter(ppl["best_type"])), "| with a title from news:", int(ppl["title_from_news"].notna().sum()))
    return xlsx


if __name__ == "__main__":
    main()
