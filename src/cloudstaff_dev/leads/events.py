"""Step 3a: gathered events: strength, grouping into distinct events, details, target check, competitor clients."""

import json
import re

import pandas as pd

from cloudstaff_dev.common.company_keys import name_key
from cloudstaff_dev.common.industry import INDUSTRY_SECTOR
from cloudstaff_dev.scoring.priority import _recency

from .config import L
from .helpers import blank
from .rules import (
    APOLLO_CONFIRMS, COMPETITOR_FUZZY, COMPOUND_EVENTS, CONFIDENCE_FACTOR, COUNTRY_WORDS, EVENT_WINDOW_DAYS,
    HIRING_BANDS, NEWS_EVENTS, OTHER_TRADE_UK_STRONG, OTHER_TRADE_UK_WEAK, OWN_SITE_SOURCE, PARENT_FACTOR,
    REGISTER_SCORED, STRENGTH)


# ---------------------------------------------------------------- 3. gathered: news, jobs, filings (News Scraper)
def _strength(news, factor, d, as_of):
    """Strength x recency of one news signal (what the score uses), for choosing between the lead's and its parent's."""
    if news not in STRENGTH or news == "None" or pd.isna(d):
        return 0.0
    return STRENGTH[news] * factor * _recency((as_of - d).days)


def cqc_event_homes():
    """{(account_id, date, url): [homes]} from cqc.py: each home in a CQC event with its own CQC page."""
    p = L.register_files["CQC register"]
    if not p.exists():
        return {}
    c = pd.read_csv(p, dtype=str, keep_default_na=False)
    if "locations" not in c.columns:
        return {}
    out = {}
    for r in c.itertuples():
        try:
            homes = json.loads(r.locations) if r.locations else []
        except ValueError:
            homes = []
        acc = "AP-" + re.sub("^apollo-", "", r.company_id)
        out[(acc, r.date, r.url)] = [{"name": h.get("name"), "city": h.get("city"), "beds": h.get("beds"),
                                      "url": "https://www.cqc.org.uk/location/" + h["id"]} for h in homes if h.get("id")]
    return out


def compound_events(leads, ev, as_of):
    """Distinct events per lead and their combined value (see COMPOUND_EVENTS). Writes news_compound (0-1, read by the
    shared scoring), unique_events, scoring_events, event_list (for the page)."""
    by = {k: g for k, g in ev.groupby("account_id")}
    homes = cqc_event_homes()
    overrides = load_overrides()
    comp, n_all, n_scoring, lists = [], [], [], []
    for _, r in leads.iterrows():
        g = by.get(r["account_id"])
        items = []
        if g is not None:
            for x in g.itertuples():
                cat, src = x.category, str(x.source or "")
                if cat not in NEWS_EVENTS or pd.isna(x.published):
                    continue
                if src == "cqc" and cat not in REGISTER_SCORED:
                    continue                           # a new registered manager: shown, not scored
                conf = str(x.event_confidence or "")
                f = 1.0 if conf.startswith(("labelled by", "from ")) else CONFIDENCE_FACTOR.get(conf, 1.0)
                # a person's review (event_overrides.csv) of one headline: applied below to the whole event it belongs to
                ovr = next((c for p, c in overrides.get(r["company_name"], []) if str(x.title or "").startswith(p)), None)
                if ovr:
                    f = 1.0
                kind = {"cqc": "CQC", "fts": "contract", "manual": "hand-labelled", OWN_SITE_SOURCE: "own site"}.get(src, "news")
                url = x.url if isinstance(x.url, str) and x.url else None
                items.append({"cat": cat, "date": x.published, "f": f, "kind": kind, "title": x.title, "ovr": ovr, "url": url,
                              "homes": homes.get((r["account_id"], str(x.published_at)[:10], url), []) if src == "cqc" else []})
        if r.get("parent_signal") in NEWS_EVENTS and not pd.isna(r.get("parent_signal_date")):
            pf = CONFIDENCE_FACTOR.get(r.get("parent_confidence") or "", 1.0) * PARENT_FACTOR
            items.append({"cat": r["parent_signal"], "date": r["parent_signal_date"], "f": pf, "kind": "parent",
                          "title": f"Parent {r.get('parent_name')}: {r.get('parent_headline') or ''}", "parent": True,
                          "url": r.get("parent_url") if isinstance(r.get("parent_url"), str) and r.get("parent_url") else None})
        events = []                                    # group: same type (and own vs parent) within EVENT_WINDOW_DAYS
        for it in sorted(items, key=lambda d: d["date"]):
            e = next((e for e in events if e["cat"] == it["cat"] and e["parent"] == it.get("parent", False)
                      and (it["date"] - e["first"]).days <= EVENT_WINDOW_DAYS), None)
            if e is None:
                e = {"cat": it["cat"], "parent": it.get("parent", False), "first": it["date"], "items": []}
                events.append(e)
            e["items"].append(it)
        # a reviewed headline decides for its whole event: "Other" drops it (Beal Homes' "sales manager snapped up" was
        # reported by three outlets), another type relabels it (Dunham Care's site purchase = Expansion, not M&A)
        kept = []
        for e in events:
            ovr = next((it["ovr"] for it in e["items"] if it.get("ovr")), None)
            if ovr and ovr not in NEWS_EVENTS:
                continue
            if ovr:
                e["cat"] = ovr
            kept.append(e)
        events = kept
        out, prod = [], 1.0
        for e in events:
            v = max(_strength(e["cat"], it["f"], it["date"], as_of) for it in e["items"])
            prod *= 1 - v
            best = max(e["items"], key=lambda it: (_strength(e["cat"], it["f"], it["date"], as_of), it["kind"] == "news"))
            out.append({"type": ("Parent: " if e["parent"] else "") + e["cat"], "date": e["first"].date().isoformat(),
                        "last": max(it["date"] for it in e["items"]).date().isoformat(), "value": round(v, 3),
                        "reports": len(e["items"]), "sources": ", ".join(sorted({it["kind"] for it in e["items"]})),
                        "title": best["title"], "url": best.get("url") or next((it.get("url") for it in e["items"] if it.get("url")), None),
                        # every CQC home in the event (all its reports), each linked to its CQC page
                        "homes": list({h["url"]: h for it in e["items"] for h in it.get("homes", [])}.values())})
        out.sort(key=lambda d: (-d["value"], d["date"]))
        comp.append(round(1 - prod, 4) if events else None)
        n_all.append(len(events)); n_scoring.append(sum(1 for d in out if d["value"] > 0)); lists.append(out)
    if COMPOUND_EVENTS:
        leads["news_compound"] = comp
    leads["unique_events"], leads["scoring_events"], leads["_event_list"] = n_all, n_scoring, lists
    return leads


def hiring_band(status, open_roles):
    """Open roles in bands (HIRING_BANDS). 'unknown' when the careers page wasn't read: never a zero."""
    if status != "ok" or blank(open_roles):
        return "unknown"
    n = int(open_roles)
    return "none open" if n <= 0 else next(lbl for lo, lbl in reversed(HIRING_BANDS) if n >= lo)


def event_detail(nlp_event, nlp_role):
    """Readable detail of an event from the scraper's NLP pass ('M&A: target · SecureSky' -> 'bought by SecureSky').
    Only ever describes an event already counted; never creates one."""
    if blank(nlp_event) or ":" not in str(nlp_event):
        return None
    d = str(nlp_event).split(":", 1)[1].strip()
    head, _, rest = d.partition(" · ")               # the scraper writes "M&A: target · SecureSky"
    head, rest = head.strip(), rest.strip(" ,")
    if nlp_role == "target" or head.startswith("target"):
        return f"bought by {rest.split(',')[0]}" if rest else "being bought"
    if nlp_role == "acquirer" or head.startswith("acquirer"):
        what = rest.split(",")[0]
        # a one-word object is usually a place ("buys Derbyshire nursing home" -> "Derbyshire"), not what was bought
        return f"buying {what}" if len(what.split()) > 1 else "as the buyer"
    m = re.match(r"(.+?) in$", head)
    if m:
        return f"new {m.group(1)}" + (f": {rest}" if rest else "")
    if head.startswith("raised") and re.search(r"\d", head):
        return head
    return None


def _codes(v):
    return [c.strip() for c in str(v).replace(";", ",").split(",") if c.strip() and c.strip().lower() != "nan"]


def target_check(leads):
    """Is the lead in its list's target industry? Apollo's one-word industry is often wrong ("individual & family services"
    for Coxbench Hall Residential Care Home), so the activity codes decide: Apollo's US SIC / NAICS and the Companies House
    UK SIC, then the service lines on its website. Order: codes showing the target activity (and no other trade) -> in;
    a UK SIC for another trade (furniture, building, staffing...) -> outside the target, even if its website mentions care (suppliers'
    sites do); website service lines for the list -> in; otherwise Apollo's industry decides. fit_basis says which applied."""
    on, why = [], []
    for r in leads.itertuples():
        rules = L.target_codes.get(r.lead_list)
        if not rules:
            on.append(None); why.append(None); continue
        sic, naics = _codes(r.sic_us), _codes(r.naics)
        uk = re.findall(r"\b(\d{5})\b", str(r.uk_sic or ""))
        hit = ([f"SIC {c}" for c in sic if c[:4] in rules["sic"]] + [f"NAICS {c}" for c in naics if c[:4] in rules["naics"]]
               + [f"UK SIC {c}" for c in uk if c[:2] in rules["uk"]])
        strong = [f"UK SIC {c}" for c in uk if c[:2] in OTHER_TRADE_UK_STRONG]
        weak = [f"UK SIC {c}" for c in uk if c[:2] in OTHER_TRADE_UK_WEAK]
        web = [] if blank(r.service_lines) else str(r.service_lines).split("; ")   # what its website says it does
        industry_ok = isinstance(r.industry, str) and r.industry in r.list_target
        supplier = isinstance(r.industry, str) and r.industry in L.supplier_groups   # Apollo itself names a supplier trade
        if strong:                                  # a supplier's site says "residential care" too, so building / furniture codes win
            on.append(False); why.append(f"another trade: {', '.join(strong[:2])}" + (f" (codes also show {', '.join(hit[:2])})" if hit else ""))
        elif hit and not (weak and supplier):       # codes win over a holding-company registration, unless Apollo agrees it's another trade
            on.append(True); why.append(f"activity codes: {', '.join(hit[:3])}" + (f" (registered as {', '.join(weak[:1])})" if weak else ""))
        elif weak:
            on.append(False); why.append(f"another trade: {', '.join(weak[:2])} and Apollo industry {r.industry_raw}")
        elif web and not supplier:
            on.append(True); why.append(f"website: {', '.join(web[:3])}")
        else:
            on.append(industry_ok); why.append(f"Apollo industry only: {r.industry_raw}" + (f" (website mentions {web[0]})" if web else ""))
    leads["_on_target"], leads["fit_basis"] = on, why
    leads["on_target"] = on                        # same, kept in the outputs
    # a lead the evidence puts in the target gets the target's industry group for fit and trend (Apollo's label kept in
    # industry_raw / industry_apollo): Royal Variety Charity is "entertainment" in Apollo but runs a care home
    leads["industry_apollo"] = leads["industry"]
    for i, r in leads.iterrows():
        targets = sorted(L.list_target_groups.get(r["lead_list"], []))
        if r["_on_target"] is True and r["industry"] not in targets and len(targets) == 1:
            leads.loc[i, ["industry", "industry_sector"]] = [targets[0], INDUSTRY_SECTOR.get(targets[0])]
    return leads


def competitor_matches(names, domains, country, cmap):
    """Match one company to the competitor-client map (names from candidates' CVs, no domains there).
    exact name key, or the website's name ('smokealarmsaustralia.com.au') = a map name without spaces -> 'confirmed' if
    the map row is confirmed; a close fuzzy match (>= COMPETITOR_FUZZY, names of 2+ words) -> 'pending' (a person checks).
    One-word names (the "Athena" problem) need an exact match and a location that doesn't point elsewhere."""
    import difflib
    keys = {name_key(n) for n in names if not blank(n)} - {""}
    stems = {d.split(".")[0].replace("-", "") for d in domains if isinstance(d, str) and d}
    out = []
    for k in keys:
        rows = cmap.get(k, [])
        if len(k.split()) == 1:                     # one-word: exact, long enough, and no other country named
            rows = [r for r in rows if len(k) >= 6 and (blank(r["client_locations"]) or COUNTRY_WORDS.get(country, "~") in str(r["client_locations"]).lower())]
        out += [(r, "exact name") for r in rows]
    for s in stems:
        out += [(r, "website name") for k, rows in cmap.items() if len(s) >= 6 and k.replace(" ", "") == s for r in rows]
    if not out:                                     # close names: both sides 2+ words and 10+ letters ("c technologies" ≠ "technologies")
        multi = [c for c in cmap if len(c.split()) >= 2 and len(c) >= 10]
        for k in keys:
            if len(k.split()) >= 2 and len(k) >= 10:
                for m in difflib.get_close_matches(k, multi, n=1, cutoff=COMPETITOR_FUZZY):
                    out += [({**r, "status": "pending"}, f"close name ({m})") for r in cmap[m]]
    return out


def add_competitor_clients(leads, path):
    """Competitor client (prior_bpo_flag): the lead appears as a competitor's client in candidates' CVs."""
    cols = ["competitor_client", "competitor_client_status", "competitor_client_basis"]
    if not path.exists():
        return leads.assign(**{k: None for k in cols}), f"no competitor map ({path.name}): Competitor client counts as No"
    m = pd.read_csv(path, dtype={"name_key": str})
    cmap = {}
    for r in m.to_dict("records"):
        cmap.setdefault(r["name_key"], []).append(r)
    res = []
    for r in leads.itertuples():
        hits = competitor_matches([r.company_name, r.apollo_name], [r.website_domain, r.email_domain], r.region, cmap)
        if not hits:
            res.append((None, None, None)); continue
        conf = [h for h in hits if h[0]["status"] == "confirmed"]
        use = conf or hits
        comp = "; ".join(sorted({f"{h[0]['competitor']} ({int(h[0]['rows_confirmed'] + h[0]['rows_pending'])} CV mentions)" for h in use}))
        res.append((comp, "confirmed" if conf else "pending", "; ".join(sorted({h[1] for h in use}))))
    leads[cols] = pd.DataFrame(res, index=leads.index, columns=cols)
    leads["prior_bpo_flag"] = leads["competitor_client_status"].map({"confirmed": "Yes"}).fillna("No")
    return leads, f"{path.name}: {m['name_key'].nunique():,} clients of {m['competitor'].nunique()} competitors"


def apollo_vs_news(label, news):
    """How Apollo's undated 'Latest Funding' compares with the event the news found (decision 2026-11-18: shown side by
    side; how to reconcile the two is still open). None = no Apollo label."""
    if blank(label):
        return None
    if news not in NEWS_EVENTS:
        return "not in the news"
    return "matches the news" if news in APOLLO_CONFIRMS.get(label, []) else "news shows a different event"


def best_detail(arts, category, date):
    """The fullest detail for one event: among the company's articles about it (the NLP pass read the same event type,
    published within 30 days of the event date), prefer one that names the other party, amount or person."""
    if arts.empty or blank(category):
        return None
    a = arts[arts["nlp_event"].fillna("").str.startswith(category + ":")]
    if not pd.isna(date):
        a = a[(a["published"] - date).abs() <= pd.Timedelta(days=30)]
    best = None
    for e, ro in sorted(zip(a["nlp_event"], a["nlp_role"]), key=lambda x: (" · " not in x[0], len(x[0]))):
        best = best or event_detail(e, ro)
    return best


def load_overrides():
    """event_overrides.csv: {company name: [(headline prefix, category)]}, a person's (or Claude's) correction of one headline."""
    out = {}
    if L.event_overrides.exists():
        for o in pd.read_csv(L.event_overrides, dtype=str).fillna("").itertuples():
            out.setdefault(o.company_name, []).append((o.headline_starts_with, o.category))
    return out
