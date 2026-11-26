"""Step 5: readout, relevant events, and the xlsx + dashboard JSON."""

import datetime as dt
import json
import os

import pandas as pd

from cloudstaff_dev.common import paths
from cloudstaff_dev.scoring.priority import NEWS_STRENGTH, RECENCY

from .config import L
from .enrich import load_reviews, review_of
from .events import cqc_event_homes, load_overrides
from .helpers import blank, jsonable
from .rules import CONFIDENCE_FACTOR, EVENT_WINDOW_DAYS, GOAL, NEWS_EVENTS, OWN_SITE_SOURCE, REGISTER_SCORED, SCORING


# ---------------------------------------------------------------- 5. readout + outputs
def readout(leads, events, apollo_files, n_contacts):
    L = leads
    news_checked = L["news_status"].isin(["found", "checked, nothing found"])
    counted = events
    by_src = counted.groupby("source").size().to_dict() if len(counted) else {}
    return {
        "apollo_files": [os.path.basename(f) for f in apollo_files], "contacts": int(n_contacts), "companies": int(len(L)),
        "news_checked": int(news_checked.sum()), "news_found": int((L["news_status"] == "found").sum()),
        "news_events": int(L["news_signal"].isin(NEWS_EVENTS).sum()),
        "news_events_high": int((L["news_signal"].isin(NEWS_EVENTS) & L["signal_confidence"].eq("high")).sum()),
        "articles_counted": int(len(counted)), "articles_by_source": by_src,
        "articles_to_review": int(L["news_to_review"].fillna(0).sum()),
        "website_profiles": L["website_profile"].fillna("not built").str.split(":").str[0].value_counts().to_dict(),
        "jobs_status": L["jobs_status"].fillna("not checked").str.split(":").str[0].value_counts().to_dict(),
        "filings_status": L["filings_status"].fillna("not checked").value_counts().to_dict(),
        "funding_labels": int(L["apollo_latest_funding"].notna().sum()),
        "funding_dated": int((L["apollo_latest_funding"].notna() & L["news_signal"].isin(["Funding round", "PE buyout", "M&A"])).sum()),
        "parents": int(L["parent_name"].notna().sum()), "parent_events": int(L["parent_signal"].notna().sum()),
        "parent_scored": int((L["news_from"] == "parent").sum()),
        "own_site_only": int(((L["news_signal"].isin(["None"]) | L["news_signal"].isna()) & (L["own_site_posts"] > 0)).sum()),
        "ownership": L["ownership"].value_counts().to_dict(),
        "ownership_checks": int(L["ownership_check"].notna().sum()),
    }


RELEVANT_DAYS = 365                                # Relevant events table: the last 12 months (user, 23 Nov 2026)
SOURCE_LABEL = {"cqc": "CQC register", "fts": "Public contract", "manual": "Hand-labelled", OWN_SITE_SOURCE: "Own website"}


def relevant_events(r, e, pe, contracts, overrides, homes, as_of):
    """One lead's relevant events in the last RELEVANT_DAYS, news, CQC, public contracts and its parent's, merged into one
    list for the company panel, newest first. Relevant = NEWS_EVENTS after event_overrides.csv ("Other" drops the article).
    review says why a person should check the row (decision 23 Nov 2026): the classifier rated it medium or low; a register
    match made on the company name only and not confirmed; or an event Claude labelled that no person has checked."""
    since = as_of - pd.Timedelta(days=RELEVANT_DAYS)
    by_url = {c["url"]: c for c in contracts}
    rows = []

    def add(x, parent=None):
        if pd.isna(x.published) or x.published < since:
            return
        title = "" if blank(x.title) else str(x.title)
        names = [r["company_name"]] + ([parent] if parent else [])
        ovr = next((c for n in names for pre, c in overrides.get(n, []) if pre and title.startswith(pre)), None)
        cat = ovr or x.category
        if cat not in NEWS_EVENTS:
            return
        src, conf = str(x.source or ""), "" if blank(x.event_confidence) else str(x.event_confidence)
        match = getattr(x, "match", None)
        match = "" if blank(match) else str(match)
        review, notes, detail = None, [], None
        if ovr:
            notes.append("type corrected on review" if ovr != x.category else "reviewed")
        elif conf in ("medium", "low"):
            review = f"News classifier unsure ({conf} confidence, half weight): check it is about this company and is this event"
        elif conf == "labelled by Claude":
            review = "Labelled by Claude, not yet checked by a person"
        if match.startswith("name") and "confirmed" not in match:
            review = "Matched on the company name only, not the company number: confirm or reject in register_match_reviews.csv"
        if src == "cqc" and cat not in REGISTER_SCORED:
            notes.append("not scored")
        if parent:
            notes.append("parent's event")
        url = None if blank(x.url) else str(x.url)
        if src == "fts" and url in by_url:
            c = by_url[url]
            detail = " · ".join(filter(None, [c.get("buyer"), f"{float(c['value']):,.0f} {c.get('currency') or ''}".strip() if c.get("value") else None]))
        h = homes.get((r["account_id"], str(x.published_at)[:10], url), []) if src == "cqc" else []
        rows.append({"date": f"{x.published:%Y-%m-%d}", "type": cat, "_src": src,
                     "source": f"Parent {parent}" if parent else SOURCE_LABEL.get(src, "News"),
                     "title": title, "url": url, "publisher": None if blank(x.publisher) else x.publisher, "detail": detail,
                     "homes": h, "notes": ", ".join(notes) or None, "review": review, "parent": bool(parent)})

    for x in ([] if e is None else e.itertuples()):
        add(x)
    for x in ([] if pe is None else pe.itertuples()):
        add(x, parent=r.get("parent_name"))
    # the same article from two feeds (news + hand-labelled, or a repeated row): keep one, preferring the row needing no review
    rows.sort(key=lambda d: d["review"] is not None)
    seen, out = set(), []
    for d in rows:
        k = (d["title"].strip().lower(), d["type"], d["parent"])
        if k not in seen:
            seen.add(k)
            out.append(d)
    return group_relevant(out)


LEAD_SOURCE = {"fts": 0, "cqc": 1, "": 2, "manual": 3, OWN_SITE_SOURCE: 4}   # which report heads a group: registers, then news


def group_relevant(rows):
    """Collapse reports of one event into one row (user, 23 Nov 2026): same type, own vs parent, within EVENT_WINDOW_DAYS of
    the group's first report, as compound_events groups them for the score. Public contracts stay one row each (two awards
    in a month are two deals). The row heads with its best report (no review needed, then registers before news, then the earliest: usually the announcement);
    every report stays in items for the expandable source list. The event needs review only when every report does."""
    groups = []
    for d in sorted(rows, key=lambda d: d["date"]):
        g = None if d["_src"] == "fts" else next(
            (g for g in groups if g["type"] == d["type"] and g["parent"] == d["parent"] and g["_src"] != "fts"
             and (pd.Timestamp(d["date"]) - pd.Timestamp(g["first"])).days <= EVENT_WINDOW_DAYS), None)
        if g is None:
            g = {"type": d["type"], "parent": d["parent"], "first": d["date"], "_src": d["_src"], "items": []}
            groups.append(g)
        g["items"].append(d)
    out = []
    for g in groups:
        items = sorted(g["items"], key=lambda d: d["date"], reverse=True)
        head = min(items, key=lambda d: (d["review"] is not None, LEAD_SOURCE.get(d["_src"], 2), d["date"]))
        flagged = all(d["review"] for d in items)
        out.append({**{k: v for k, v in head.items() if k != "_src"}, "first": g["first"], "date": items[0]["date"],
                    "source": ", ".join(dict.fromkeys(d["source"] for d in items)),
                    "homes": list({h["url"]: h for d in items for h in d["homes"]}.values()),
                    "review": head["review"] if flagged else None, "reports": len(items),
                    "items": [{k: v for k, v in d.items() if k not in ("_src", "homes")} for d in items]})
    return sorted(out, key=lambda d: d["date"], reverse=True)


def lead_signals(r, e):
    """Signal types a lead has, for the page's "Has these signals" filter. Present, not necessarily the scored one."""
    out = []
    if e is not None:
        src = e["source"].fillna("")
        if (e["category"].isin(NEWS_EVENTS) & ~src.isin(["cqc", "fts"])).any():
            out.append("news")                         # a news event (publisher, own site or hand-labelled)
        if (src == "cqc").any():
            out.append("cqc")
        if (src == "fts").any():
            out.append("contract")
    if not blank(r.get("job_postings_30d")) and r["job_postings_30d"] > 0:
        out.append("hiring")                           # roles Cloudstaff fills, posted in the last 30 days
    if r.get("parent_signal") in NEWS_EVENTS:
        out.append("parent")
    if not blank(r.get("competitor_client")):
        out.append("competitor")
    if not blank(r.get("match_review")):
        out.append("review")
    if not blank(r.get("scoring_events")) and r["scoring_events"] > 1:
        out.append("multi")
    if any(c[1] == "fit" for c in r.get("chips") or []):
        out.append("fit")
    if not blank(r.get("filing_signal")) and r["filing_signal"] != "None":
        out.append("filing")
    if not blank(r.get("owner_contacts")):
        out.append("owner")
    if not blank(r.get("officer_contacts")):
        out.append("director")
    return out


def save(leads, contacts, events, parent_events, jobs_by_lead, info, name, as_of):
    cols_out = [c for c in leads.columns if not c.startswith("_") and c not in ("chips", "profile_chips", "apollo_chips")]
    paths.ensure(L.grades)
    xlsx = L.grades_xlsx
    with pd.ExcelWriter(xlsx) as w:
        joined = lambda k: leads[k].map(lambda cs: "; ".join(c[0] for c in cs))
        leads.assign(events_and_signals=joined("chips"), apollo=joined("apollo_chips"), profile=joined("profile_chips"))[
            ["events_and_signals", "apollo", "profile"] + cols_out].to_excel(w, sheet_name="leads", index=False)
        contacts.to_excel(w, sheet_name="contacts", index=False)
        events.to_excel(w, sheet_name="news_articles", index=False)
        parent_events.to_excel(w, sheet_name="parent_news_articles", index=False)
        pd.DataFrame([{"key": k, "value": json.dumps(v) if isinstance(v, (dict, list)) else v} for k, v in info.items()]).to_excel(w, sheet_name="run_info", index=False)
    rows = []
    ev_by = {k: g.sort_values("published_at", ascending=False) for k, g in events.groupby("account_id")}
    # parent articles shown on the lead: its relevant events first, then its newest other news (max 3, marked "parent")
    pev_by = {k: g.assign(_e=g["category"].isin(NEWS_EVENTS)).sort_values(["_e", "published_at"], ascending=False)
              for k, g in parent_events.groupby("parent_id")}
    con_by = {k: g for k, g in contacts.groupby("account_id")}
    cqc_by, con_awards = {}, {}
    if L.cqc_locations.exists():
        cl = pd.read_csv(L.cqc_locations, dtype=str, keep_default_na=False)
        cl["account_id"] = "AP-" + cl["company_id"].str.replace("^apollo-", "", regex=True)
        cols = ["location_name", "city", "registered_on", "care_home", "beds", "rating", "rating_published", "service_types", "location_id"]
        cqc_by = {k: g.sort_values("registered_on", ascending=False)[cols].to_dict("records") for k, g in cl.groupby("account_id")}
    ca_path = L.register_files["Find a Tender"]
    if ca_path.exists():
        ca = pd.read_csv(ca_path, dtype=str, keep_default_na=False)
        ca["account_id"] = "AP-" + ca["company_id"].str.replace("^apollo-", "", regex=True)
        cols = ["date", "buyer", "headline", "value", "currency", "cpv_desc", "url", "supplier_name", "match"]
        reviews, names = load_reviews(), dict(zip(leads["account_id"], leads["company_name"]))
        for i, x in ca.iterrows():
            if x["match"] == "name":
                rv = review_of(reviews, names.get(x["account_id"], ""), "Find a Tender", x["url"].rsplit("/", 1)[-1])
                ca.loc[i, "match"] = "rejected" if rv and rv[0] == "rejected" else f"name, confirmed by {rv[1]}" if rv else "name"
        ca = ca[ca["match"] != "rejected"]
        con_awards = {k: g.sort_values("date", ascending=False)[cols].to_dict("records") for k, g in ca.groupby("account_id")}
    fields = (("date", "published_at"), ("category", "category"), ("confidence", "event_confidence"), ("title", "title"),
              ("publisher", "publisher"), ("url", "url"), ("source", "source"))
    overrides, homes = load_overrides(), cqc_event_homes()
    for r in leads.to_dict("records"):
        row = {k: jsonable(r.get(k)) for k in cols_out}
        row["chips"], row["profile_chips"], row["apollo_chips"] = r["chips"], r["profile_chips"], r["apollo_chips"]
        e, pe = ev_by.get(r["account_id"]), pev_by.get(r.get("parent_id"))
        row["news"] = ([] if e is None else [{k: jsonable(getattr(x, f)) for k, f in fields} for x in e.head(8).itertuples()]) + \
                      ([] if pe is None else [{**{k: jsonable(getattr(x, f)) for k, f in fields}, "parent": r.get("parent_name")} for x in pe.head(3).itertuples()])
        row["jobs"] = jobs_by_lead.get(r["account_id"], [])
        row["signals"] = lead_signals(r, e)
        row["event_list"] = r.get("_event_list") or []
        row["cqc_list"] = cqc_by.get(r["account_id"], [])
        row["contracts"] = con_awards.get(r["account_id"], [])
        row["relevant_events"] = relevant_events(r, e, pe, row["contracts"], overrides, homes, as_of)
        row["events_to_review"] = sum(1 for d in row["relevant_events"] if d["review"])
        if row["events_to_review"]:
            row["signals"].append("needs_review")
        cg = con_by.get(r["account_id"])
        row["contacts"] = [] if cg is None else [{k: jsonable(v) for k, v in x.items() if k != "account_id"} for x in cg.to_dict("records")]
        rows.append(row)
    S = SCORING
    data = {"meta": {"title": L.title, "subtitle": L.subtitle, "source": L.source,
                     "extract": info["apollo_extract"], "generated": dt.datetime.now().isoformat(timespec="seconds"),
                     "as_of": as_of.strftime("%Y-%m-%d"), "team": L.team, "fit_country": L.fit_country,
                     "max_points": S["max_points"][GOAL], "news_strength": NEWS_STRENGTH, "recency": RECENCY,
                     "confidence_factor": CONFIDENCE_FACTOR, "tier_shares": S["tier"], "info": info},
            "qa": info["qa"], "rows": rows}
    # the Industry trends page's data (industry_trends.py) is added when the page is built (dashboards/build.py)
    js = L.grades_json
    json.dump(data, open(js, "w", encoding="utf-8"), ensure_ascii=False, allow_nan=False, default=str)
    return xlsx, js
