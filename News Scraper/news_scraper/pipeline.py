"""Run the scrape for a list of companies, and export the results for the Priority Score.

Window per company and source (the lookback toggle):
  - lookback_days: the company's own value if given, else --lookback-days (default 180).
  - backfill: the whole lookback window. Used the first time, with --mode backfill, or when the lookback
    was raised beyond what has already been checked.
  - incremental (the daily run): only since the last successful check, minus a 2-day overlap for articles
    that are indexed late. One cheap query per company per source, whatever the lookback.
"""
import csv
import datetime as dt
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import http, jobs, nlp, profile, registers
from .classify import OTHER, classify, load_settings, recency_factor
from .match import CONFIRM, MATCH, POSSIBLE, SOCIAL, VOLUME_CONFIRMED, VOLUME_MIN, Matcher, root_domain
from .sources import GDELT_MAX_DAYS, SOURCES, SkipSource, find_feed
from .store import Store, dedupe_key, is_direct, real_url

OVERLAP_DAYS = 2
FEED_RECHECK_DAYS = 30
COUNTRY_NAMES = {"AU": "Australia", "NZ": "New Zealand", "UK": "United Kingdom", "GB": "United Kingdom", "US": "United States",
                 "PH": "Philippines", "CA": "Canada", "SG": "Singapore", "IE": "Ireland"}


@dataclass
class Company:
    name: str
    company_id: str = ""
    domain: str = ""
    location: str = ""
    country: str = ""
    aliases: list = field(default_factory=list)
    context: list = field(default_factory=list)      # words that narrow a common name in searches, e.g. Deputy -> software;scheduling
    lookback_days: int | None = None
    ticker: str = ""                                 # e.g. XRO or ASX:XRO; strong identity evidence when an article mentions it
    ambiguous: bool | None = None                    # name is a common word? None = assume yes when context words are given
    employees: int | None = None                     # headcount; small companies (< match.SMALL_COMPANY) get stricter name checks

    def __post_init__(self):
        self.domain = root_domain(self.domain)
        if not self.company_id:
            self.company_id = re.sub(r"[^a-z0-9]+", "-", f"{self.name} {self.domain}".lower()).strip("-")

    @property
    def places(self):
        """Location words used as a matching hint: 'Brisbane, QLD' + country -> Brisbane, QLD, Australia."""
        p = [x.strip() for x in re.split(r"[,;/]", self.location or "") if x.strip()]
        if self.country:
            p.append(COUNTRY_NAMES.get(self.country.upper(), self.country))
        return p


def _int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def read_companies(path):
    """CSV with company_name (required) and optional company_id, website, location, country, aliases and context
    (both ';'-separated), lookback_days, ticker, ambiguous (yes/no), employees (or employee_count)."""
    def yes_no(v):
        v = (v or "").strip().lower()
        return True if v in ("yes", "y", "true", "1") else False if v in ("no", "n", "false", "0") else None
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("company_name"):
                continue
            out.append(Company(name=r["company_name"], company_id=r.get("company_id", ""), domain=r.get("website") or r.get("domain", ""),
                               location=r.get("location", ""), country=r.get("country", ""),
                               aliases=[a.strip() for a in r.get("aliases", "").split(";") if a.strip()],
                               context=[a.strip() for a in r.get("context", "").split(";") if a.strip()],
                               lookback_days=int(r["lookback_days"]) if r.get("lookback_days", "").isdigit() else None,
                               ticker=r.get("ticker", ""), ambiguous=yes_no(r.get("ambiguous")),
                               employees=_int(r.get("employees") or r.get("employee_count"))))
    return out


def window(store, c, src, lookback, mode, today):
    full = today - dt.timedelta(days=lookback)
    if src == "gdelt":
        full = max(full, today - dt.timedelta(days=GDELT_MAX_DAYS))
    span = store.covered_span(c.company_id, src)
    if mode == "backfill" or span is None or full < span[0] - dt.timedelta(days=1):
        return full
    return max(full, span[1] - dt.timedelta(days=OVERLAP_DAYS))


def process(store, c, sources, lookback_default, mode, today, read=None):
    store.upsert_company(c)
    card = profile.ensure(store, c)                        # company card from its website (rebuilt every 30 days)
    matcher, stats = Matcher(c, card), Counter()
    stats[f"profile:{card['status'].split(':')[0]}"] += 1
    lookback = c.lookback_days or lookback_default
    for src in sources:
        since = window(store, c, src, lookback, mode, today)
        try:
            if src == "newsroom":
                if not c.domain:
                    raise SkipSource("no website given")
                feed_url, checked = store.feed(c.company_id)
                if not checked or dt.datetime.fromisoformat(checked) < dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=FEED_RECHECK_DAYS):
                    feed_url = find_feed(c.domain)
                    store.set_feed(c.company_id, feed_url)
                items = SOURCES[src](c, since, today, feed_url)
            else:
                items = SOURCES[src](c, since, today)
        except SkipSource as e:
            store.add_coverage(c.company_id, src, since, today, "skipped", error=str(e))
            stats[f"{src}:skipped"] += 1
            continue
        except (http.FetchError, Exception) as e:          # one failing source must not stop the others
            store.add_coverage(c.company_id, src, since, today, "error", error=f"{type(e).__name__}: {e}"[:300])
            stats[f"{src}:error"] += 1
            continue
        rows = []
        for a in items:
            d = a["published_at"]
            if d is None or not (since <= d.date() <= today):
                continue
            score = matcher.score(a["title"], a["summary"], a["url"], src)
            category = classify(a["title"], a["summary"])
            if score < POSSIBLE or category is None:           # not about the company, or a profile page rather than news
                continue
            rows.append({"company_id": c.company_id, "dedupe_key": dedupe_key(a["title"], a["publisher"], a["url"]), "source": src,
                         "title": a["title"], "url": a["url"], "publisher": a["publisher"], "published_at": d.isoformat(timespec="seconds"),
                         "summary": (a["summary"] or "")[:1000], "match_score": score, "category": category})
        new = store.add_articles(rows)
        store.add_coverage(c.company_id, src, since, today, "ok", len(items), len(rows))
        stats[f"{src}:ok"] += 1
        stats["new_articles"] += max(new, 0)
    if read:
        stats += read_texts(store, c.company_id, **read)
    return stats


def _reader():
    """article_reader is a separate package, imported only when reading is switched on."""
    try:
        from article_reader import read_article
    except ImportError as e:
        raise SystemExit(f"--read-articles needs the article_reader package next to news_scraper ({e})")
    return read_article


def read_texts(store, company_id, min_match=MATCH, max_per_company=10):
    """Fetch the text of this company's matched articles that have not been read yet (newest first)."""
    read_article, stats = _reader(), Counter()
    for key, url in store.unread(company_id, min_match, max_per_company):
        r = read_article(url)
        store.add_text(company_id, key, r)
        stats[f"read:{r.status}"] += 1
    return stats


def read_stored(db_path, min_match=MATCH, max_per_company=10, workers=6, log=print):
    """`read` command: fetch text for articles already in the store (e.g. after a run without --read-articles)."""
    store, t0, total = Store(db_path), time.time(), Counter()
    ids = [r[0] for r in store.db.execute("SELECT company_id FROM companies ORDER BY name")]
    log(f"Reading article text for {len(ids)} companies · up to {max_per_company} per company · match ≥ {min_match}")
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(read_texts, store, cid, min_match, max_per_company) for cid in ids]):
            total += f.result()
    log(f"Read in {time.time() - t0:,.0f}s · " + " · ".join(f"{k[5:]} {v}" for k, v in sorted(total.items())))
    return total


def build_profiles(companies, db_path, refresh=False, workers=6, log=print):
    """`profile` command: build (or refresh) each company's card and print what was found."""
    store = Store(db_path)
    for c in companies:
        store.upsert_company(c)
    with ThreadPoolExecutor(workers) as ex:
        cards = list(ex.map(lambda c: profile.ensure(store, c, refresh), companies))
    for c, card in zip(companies, cards):
        m = Matcher(c, card)
        log(f"\n{c.name}  [{card['status']}]  name: {'ambiguous' if m.ambiguous else 'distinctive'}")
        for k in ("site_name", "legal_name", "ticker", "city"):
            if card.get(k):
                log(f"  {k:<10} {card[k]}")
        for k in ("alt_names", "people", "keywords"):
            if card.get(k):
                log(f"  {k:<10} {'; '.join(card[k])}")
    return cards


def run(companies, db_path, sources, lookback_days=180, mode="auto", workers=6, read=None, log=print):
    """read: None (default, headlines only) or dict(min_match=..., max_per_company=...) to also fetch article text."""
    store, today, t0, total = Store(db_path), dt.date.today(), time.time(), Counter()
    if read:
        _reader()                                          # fail early if the package is missing
    log(f"Scraping {len(companies)} companies · sources {', '.join(sources)} · lookback {lookback_days} days · mode {mode} · {workers} workers"
        + (f" · reading up to {read['max_per_company']} articles per company" if read else ""))
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(process, store, c, sources, lookback_days, mode, today, read): c for c in companies}
        for i, f in enumerate(as_completed(futs), 1):
            total += f.result()
            if i % 25 == 0 or i == len(companies):
                log(f"  {i}/{len(companies)} companies · {total['new_articles']} new articles · {time.time() - t0:,.0f}s")
    log("Per source (ok / error / skipped): " + " · ".join(f"{s} {total[s + ':ok']}/{total[s + ':error']}/{total[s + ':skipped']}" for s in sources))
    if read:
        log("Article text: " + (" · ".join(f"{k[5:]} {v}" for k, v in sorted(total.items()) if k.startswith("read:")) or "nothing new to read"))
    return total


# ---------------------------------------------------------------- export for the Priority Score
def write_csv(out_dir, name, rows, cols):
    """Write a CSV; if the file is open in another program (Excel), write a timestamped copy instead. Returns the path."""
    import os
    path = os.path.join(out_dir, name)
    try:
        f = open(path, "w", encoding="utf-8-sig", newline="")
    except PermissionError:
        path = os.path.join(out_dir, f"{name[:-4]}_{dt.datetime.now():%Y%m%d_%H%M%S}.csv")
        print(f"  {name} is open in another program, so this export went to {os.path.basename(path)}")
        f = open(path, "w", encoding="utf-8-sig", newline="")
    with f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def _prepare(db_path, settings_path=None, min_match=MATCH, lookback_days=180):
    """Everything the export and the labelling/training commands share: companies, matchers, cached NLP results, and the
    judged events/review lists."""
    strength, recency = load_settings(settings_path)
    store, today = Store(db_path), dt.datetime.now(dt.timezone.utc)
    q = store.db.execute
    crow = q("SELECT company_id, name, domain, location, country, aliases, context, ticker, ambiguous, employees FROM companies ORDER BY name").fetchall()
    companies = [(r[0], r[1], r[2]) for r in crow]
    cards = {cid: store.profile(cid) or {} for cid, _, _ in companies}
    for cid, card in cards.items():                  # registered and trading names (filings) confirm a news match, like the site's names
        reg = registers.identity_names(store, cid)
        if reg:
            cards[cid] = {**card, "alt_names": list(dict.fromkeys(card.get("alt_names", []) + reg))}
    matchers = {r[0]: Matcher(Company(name=r[1], company_id=r[0], domain=r[2] or "", location=r[3] or "", country=r[4] or "",
                                      aliases=[a for a in (r[5] or "").split(";") if a], context=[a for a in (r[6] or "").split(";") if a],
                                      ticker=r[7] or "", ambiguous={"yes": True, "no": False}.get(r[8] or ""), employees=_int(r[9])),
                             cards[r[0]])
                for r in crow}
    texts = {(r[0], r[1]): (r[2], r[3] or "", r[4] or "") for r in q("SELECT company_id, dedupe_key, status, text, final_url FROM article_texts")}
    arts = q("SELECT company_id, source, title, url, publisher, published_at, match_score, summary, dedupe_key FROM articles").fetchall()
    cov = {}                                         # latest status per company x source
    for cid, src, status, checked in q("SELECT company_id, source, status, checked_at FROM source_coverage ORDER BY checked_at"):
        cov[(cid, src)] = (status, checked)

    # ---- NLP results (news_scraper nlp run), if any: per story, plus what the company-level checks need
    nlp_res = nlp.load(store, {a[8] for a in arts})
    company_vec = {}
    if any(r["embedding"] is not None for r in nlp_res.values()):
        for cid, _, _ in companies:
            company_vec[cid] = nlp.company_vector(cards[cid], None)
    recurring = defaultdict(Counter)                 # company -> longer headline names containing the company name, and how often
    for cid, _, title, _, _, _, _, _, key in arts:
        r = nlp_res.get(key)
        if r:
            le = nlp.longer_entity(matchers[cid].names, title, r["entities"])
            if le:
                recurring[cid][le] += 1
    ctx = {"store": store, "today": today, "strength": strength, "recency": recency, "companies": companies, "cards": cards, "matchers": matchers,
           "texts": texts, "arts": arts, "cov": cov, "nlp": nlp_res, "company_vec": company_vec, "lookback_days": lookback_days,
           "recurring": {cid: {k for k, n in c.items() if n >= 2} for cid, c in recurring.items()},
           "combiner": nlp.about_company_model(), "setfit": nlp.category_model(), "min_match": min_match}
    events, review = _judge(ctx)
    # a "distinctive" name with many matches that almost nothing confirms is really a common word: judge it again as ambiguous
    news = defaultdict(list)
    for e in events:
        if e["source"] != "newsroom":
            news[e["company_id"]].append(e)
    flipped = {cid for cid, evs in news.items() if matchers[cid].small and not matchers[cid].ambiguous and not matchers[cid].ambiguous_set
               and len(matchers[cid].name.split()) <= 2          # "Bank of Sydney" is specific; "Clutch", "Big Post" are not
               and len(evs) >= VOLUME_MIN and _unconfirmed(evs)}
    for cid in flipped:
        matchers[cid].ambiguous, matchers[cid].ambiguous_reason = True, f"{len(news[cid])} matches, few confirm the company"
    if flipped:
        events, review = _judge(ctx)
    ctx["events"], ctx["review"] = events, review
    return ctx


def _unconfirmed(evs):
    """Many matches and almost none confirmed, judged on the articles whose text was read: a headline alone rarely carries a
    domain or a city, so unread articles say nothing either way (Tyro Payments was flagged when no text had been read)."""
    read = [e for e in evs if e["text_status"] == "ok"]
    if len(read) < 5:
        return False
    return sum(bool(e["evidence"]) for e in read) / len(read) < VOLUME_CONFIRMED


def export(db_path, out_dir, settings_path=None, min_match=MATCH, lookback_days=180):
    """signal_events.csv (news, jobs and filings, told apart by signal_type), company_summary.csv (one row per company, in
    the scoring's news_signal / news_signal_date terms) and review.csv (possible matches to check by hand)."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    ctx = _prepare(db_path, settings_path, min_match, lookback_days)
    return _export_rest(out_dir, ctx)


def judge_all(db_path, settings_path=None):
    """(events, review) with company_name, _key and _features filled: for `nlp label` and `nlp train`."""
    ctx = _prepare(db_path, settings_path)
    names = {cid: name for cid, name, _ in ctx["companies"]}
    for r in ctx["events"] + ctx["review"]:
        r["company_name"] = names.get(r["company_id"], "")
    return ctx["events"], ctx["review"]


def _judge(ctx):
    """Every stored article -> (events that count, review rows). Rules first; the NLP results (when computed) add the entity
    checks, the event with who-did-what, the zero-shot category for 'Other' articles, and the semantic fit."""
    matchers, texts, strength, recency, today = ctx["matchers"], ctx["texts"], ctx["strength"], ctx["recency"], ctx["today"]
    lookback_days, min_match, nlp_res = ctx["lookback_days"], ctx["min_match"], ctx["nlp"]
    events, review, other_rows = [], [], []
    for cid, src, title, url, pub, published, score, summary_text, key in ctx["arts"]:
        age = (today - dt.datetime.fromisoformat(published)).days
        cat = classify(title, summary_text)          # re-classified on export, so rule changes apply without re-scraping
        if age > lookback_days or cat is None or (pub or "").strip().lower() in SOCIAL:
            continue
        m = matchers[cid]
        text_status, text, final_url = texts.get((cid, key), ("not read", "", ""))
        text = text if text_status == "ok" else ""
        lead = text[:600]
        if lead and cat == OTHER:                    # headline says nothing specific: let the opening paragraphs decide
            cat = classify("", lead) or OTHER
        basis = "rules" if cat != OTHER else ""
        # ---- NLP
        res = nlp_res.get(key)
        n = {"nlp_entity_check": "", "nlp_event": "", "nlp_role": "", "nlp_certainty": "", "zs_label": "", "zs_score": "", "zs_category": "",
             "fit": "", "mentions": ""}
        verdict, note, primary, role, zs_cat, fit, extra = "", "", None, "", None, None, 0
        if res:
            names = m.names + [p for _, p in m.strong]
            roles = [(ev, nlp.role_of(names, ev)) for ev in res["events"]]
            known = [m.name, *[p.pattern for p in m.cased], *ctx["cards"][cid].get("alt_names", []), ctx["cards"][cid].get("legal_name", "")]
            verdict, note = nlp.entity_check(names, title, f"{summary_text or ''} {lead}".strip(), res["entities"], known,
                                             ctx["recurring"].get(cid, set()), one_word=len(m.name.split()) == 1, is_actor=any(r for _, r in roles),
                                             strict=m.small)
            primary = next(((ev, r) for ev, r in roles if r), None) or next(((ev, r) for ev, r in roles if ev["where"] == "title"), None) \
                or (roles[0] if roles else None)
            zs_cat, zs_detail, zs_label, zs_score = nlp.zs_best(res["zeroshot"], "company")
            fit = nlp.cosine(res["embedding"], ctx["company_vec"].get(cid))
            extra = 0      # an ORG tag is not identity evidence: spaCy tags "Clutch" (a hockey team, a game) as an organisation too
            n.update({"nlp_entity_check": f"{verdict}: {note}" if note else verdict, "zs_label": zs_label, "zs_score": zs_score if zs_label else "",
                      "zs_category": zs_cat or "", "fit": round(fit, 3) if fit is not None else ""})
            if primary:
                ev, role = primary
                n.update({"nlp_event": f"{ev['category']}: {nlp.describe(ev, role)}", "nlp_role": role, "nlp_certainty": ev["certainty"]})
        mentions = m.company_uses(f"{title} {summary_text or ''} {text}", minus_titles=False)
        n["mentions"] = mentions
        # ---- does it count?
        ok, check, found = m.verdict(title, summary_text, src, text or None, extra=extra)
        pts, _ = m.evidence(f"{title} {text or summary_text or ''}")
        pts += extra
        if src != "newsroom":
            if ok and verdict in ("compound", "longer name"):
                ok, check = False, note
            elif ok and verdict == "wrong type" and pts < CONFIRM:
                ok, check = False, note
            lex = m.passing_lexical(title)
            if ok and lex and mentions < 3:                              # unless the article text keeps naming the company
                ok, check = False, f"passing mention: '{lex}'"
        if score < min_match:
            ok, check = False, check or f"low match score ({score})"
        feats = nlp.features(pts, verdict, mentions, bool(any(p.search((title or "").lower()) for p in m.names)), fit, m.ambiguous, m.one_word,
                             bool(text), bool(zs_cat and zs_cat != OTHER), m.passing_mention(title)) if res else None
        about_p = ""
        if ctx["combiner"] and feats and src != "newsroom":   # a trained combiner (nlp train) overrides the rules when it is confident
            about_p = round(float(ctx["combiner"]["model"].predict_proba([feats])[0][1]), 3)
            if about_p >= 0.7 and not ok and not check.startswith("low match"):
                ok, check = True, ""
                found.append(f"combiner p={about_p}")
            elif about_p <= 0.3 and ok:
                ok, check = False, f"combiner says not this company (p={about_p})"
        # ---- what happened: rules, else the dependency event, else zero-shot, else SetFit (trained)
        if primary and primary[0]["certainty"] == "denied" and primary[0]["category"] == cat:
            cat, basis = OTHER, "denied"
        elif cat == OTHER and primary and nlp.confident(primary[0], primary[1], title):
            cat, basis = primary[0]["category"], "nlp event"
        elif (cat == OTHER and zs_cat and zs_cat != OTHER and zs_score >= 0.75 and src != "newsroom"
              and any(p.search((title or "").lower()) for p in m.names)):      # zero-shot alone is noisy: the company must be in the headline
            cat, basis = zs_cat, "zero-shot"
        row = {"company_id": cid, "published_at": published[:10], "age_days": age, "category": cat, "category_basis": basis,
               "strength": strength.get(cat, strength.get(OTHER, 0.3)),
               "recency_factor": recency_factor(age, recency), "match_score": score, "title": title, "publisher": pub, "url": real_url(final_url, url),
               "google_url": url if not is_direct(url) else "", "source": src, "text_status": text_status, "evidence": "; ".join(found),
               "check": check, "lead": re.sub(r"\s+", " ", lead[:300]), **n, "about_p": about_p, "_key": key, "_features": feats}
        row["weighted"] = round(row["strength"] * row["recency_factor"], 3)
        row["_rule_cat"], row["_masked"] = (cat if basis in ("rules", "") else OTHER), nlp.mask_name(title, m.names)
        row["event_confidence"] = "high" if basis == "rules" else "medium" if cat != OTHER else ""
        (events if ok else review).append(row)
        if cat == OTHER and ctx["setfit"]:
            other_rows.append(row)
    # ---- headline event classifier (trained on event_examples.py) for the counted news articles: veto, add, confidence
    cand = [r for r in events if r["source"] != "newsroom" and r["category_basis"] in ("rules", "")]
    if cand and ctx.get("use_event_clf", True):
        try:
            probs = nlp.event_probs(ctx["store"], [(r["company_id"], r["_key"], r["_masked"]) for r in cand])
        except ImportError:                          # the nlp dependency group is not installed: rules only
            probs = {}
        for r in cand:
            p = probs.get((r["company_id"], r["_key"]))
            if not p:
                continue
            c, b, conf = nlp.combine_event(r["_rule_cat"], p, OTHER)
            r["category"], r["category_basis"], r["event_confidence"] = c, b, conf
            r["clf_top"], r["clf_score"] = max(p.items(), key=lambda kv: kv[1])
            r["strength"] = strength.get(c, strength.get(OTHER, 0.3))
            r["weighted"] = round(r["strength"] * r["recency_factor"], 3)
    if other_rows:                                   # batch prediction: MiniLM is cheap, one call for all rows
        preds = ctx["setfit"].predict([f"{r['title']}. {r['lead']}"[:600] for r in other_rows])
        for r, p in zip(other_rows, preds):
            if p != OTHER:
                r["category"], r["category_basis"] = p, "setfit"
                r["strength"] = strength.get(p, strength.get(OTHER, 0.3))
                r["weighted"] = round(r["strength"] * r["recency_factor"], 3)
    return events, review


def _export_rest(out_dir, ctx):
    """company_summary.csv, signal_events.csv (news, jobs and filings, told apart by signal_type), review.csv.
    news_signal comes from news only, so its meaning in the score doesn't change; jobs and filings get their own columns."""
    events, review, companies, cards, matchers, cov = ctx["events"], ctx["review"], ctx["companies"], ctx["cards"], ctx["matchers"], ctx["cov"]
    store, today, lookback_days, recency = ctx["store"], ctx["today"], ctx["lookback_days"], ctx["recency"]
    for e in events:
        e["signal_type"] = "news"
    extra, extra_fields = [], {}
    for cid, _, _ in companies:
        jf, jev = jobs.job_rows(store, cid, today.date())
        ff, fev = registers.filing_rows(store, cid, today.date(), lookback_days)
        extra_fields[cid] = {**jf, **ff}
        for e in jev + fev:
            age = (today.date() - dt.date.fromisoformat(e["published_at"])).days
            extra.append({**e, "company_id": cid, "age_days": age, "recency_factor": recency_factor(age, recency), "strength": "",
                          "weighted": "", "match_score": "", "text_status": "", "check": "", "lead": ""})
    by_c = {}
    for e in events:
        by_c.setdefault(e["company_id"], []).append(e)
    vectors = {k: r["embedding"] for k, r in ctx["nlp"].items() if r["embedding"] is not None}
    summary = []
    for cid, name, domain in companies:
        statuses = {s: st for (c, s), (st, _) in cov.items() if c == cid}
        checked = [st for st in statuses.values() if st == "ok"]
        rank = {"high": 2, "medium": 1, "low": 1}
        evs = sorted(by_c.get(cid, []), key=lambda e: (e["category"] != OTHER and rank.get(e.get("event_confidence"), 0) == 2,
                                                       e["weighted"], e["strength"], e["published_at"]), reverse=True)
        stories = nlp.story_groups(evs, vectors) if vectors and evs else {}
        for e in evs:
            e["story_id"] = f"{cid}-{stories[e['_key']]}" if e["_key"] in stories else ""
        best = evs[0] if evs else None
        status = "found" if best else ("checked, nothing found" if checked else "not checked")
        summary.append({
            "company_id": cid, "company_name": name, "website": domain or "", "news_status": status,
            # in the scoring's terms: blank = unknown (baseline), "None" = checked and found nothing (real zero)
            "news_signal": best["category"] if best else ("None" if checked else ""),
            "news_signal_date": best["published_at"] if best else "", "headline": best["title"] if best else "",
            "publisher": best["publisher"] if best else "", "url": best["url"] if best else "",
            "signal_confidence": best.get("event_confidence", "") if best else "", "signal_basis": best["category_basis"] if best else "", "nlp_event": best["nlp_event"] if best else "",
            "matched_articles": len(evs), "distinct_stories": len(set(stories.values())) if stories else (len(evs) or ""),
            "events_not_other": sum(e["category"] != OTHER for e in evs),
            "possible_matches_to_review": sum(r["company_id"] == cid for r in review),
            "name_type": f"ambiguous ({matchers[cid].ambiguous_reason})" if matchers[cid].ambiguous else "distinctive",
            "profile_status": cards[cid].get("status", "not built"),
            "profile_keywords": "; ".join(cards[cid].get("keywords", [])[:8]),
            "sources_ok": ";".join(s for s, st in statuses.items() if st == "ok"),
            "sources_error": ";".join(s for s, st in statuses.items() if st == "error"),
            "sources_skipped": ";".join(s for s, st in statuses.items() if st == "skipped"),
            "note": "" if domain else "no website: matched on name and location only",
        })
        summary[-1].update(extra_fields.get(cid, {}))

    def write(name, rows, cols):
        write_csv(out_dir, name, rows, cols)

    ev_cols = ["company_id", "signal_type", "published_at", "age_days", "category", "category_basis", "strength", "recency_factor", "weighted",
               "event_confidence", "match_score", "title", "publisher", "url", "google_url", "source", "text_status", "evidence", "check", "story_id",
               "clf_top", "clf_score",
               "nlp_entity_check", "nlp_event", "nlp_role", "nlp_certainty", "zs_category", "zs_label", "zs_score", "fit", "mentions", "about_p", "lead"]
    write("signal_events.csv", sorted(events + extra, key=lambda e: (e["company_id"], e["published_at"]), reverse=True), ev_cols)
    write("review.csv", sorted(review, key=lambda e: (e["company_id"], e["published_at"]), reverse=True), ev_cols)
    # same columns on every row (job and filing fields only exist for companies that were checked)
    cols = list(dict.fromkeys(["company_id", "company_name", "website", "news_status", "news_signal", "news_signal_date", "headline", "publisher",
                               "url", "signal_confidence", "signal_basis", "nlp_event", "matched_articles", "distinct_stories", "events_not_other", "possible_matches_to_review",
                               "jobs_status", "jobs_method", "open_roles", "job_postings_30d", "jobs_dates_known", "hiring_spike", "open_roles_before",
                               "careers_url", "filings_status", "filing_signal", "filing_signal_date", "registered_name", "registration_id", "abn",
                               "registered_status", "registered_on", "trading_names", "uk_accounts", "uk_sic"]
                              + [k for s in summary for k in s]))
    write("company_summary.csv", summary, cols if summary else ["company_id"])
    return {"companies": len(summary), "events": len(events), "review": len(review), "status": Counter(s["news_status"] for s in summary)}
