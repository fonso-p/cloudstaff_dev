"""Step 4: gates, Priority Score (priority_scoring), tiers and the chips that explain each grade."""

import re

import pandas as pd

from cloudstaff_dev.scoring.priority import FIT, percentile_tier, score_accounts

from .config import L
from .helpers import blank
from .rules import DECISION_MAKER, DISTRESS, DUPLICATE, NEWS_EVENTS, PROFILE_KINDS, SCORING, TIER_GROUP


# ---------------------------------------------------------------- 4. gates, score, reasons
def gate(r):
    status = " ".join(str(r.get(k) or "") for k in ("registered_status", "filing_signal")).lower()
    if re.search(DISTRESS, status):
        return "Excluded: distressed"
    if isinstance(r.get("internal_match"), str) and r["internal_match"].startswith("Existing client"):
        return "Existing client"
    if isinstance(r.get("duplicate_of"), str):
        return DUPLICATE                           # the other account carries the lead; this one keeps its contacts for reference
    # outside the list's target industry: tiered like the rest since 24 Nov 2026 (user); the company panel says to check it
    return None


def news_by_category(events, as_of):
    """account_id -> {event type: [{date, title, publisher, url, confidence}], newest first} for the lead's own relevant
    events in the last year. Feeds the Why chips' hover lists."""
    e = events[events["category"].isin(NEWS_EVENTS) & (events["published"] >= as_of - pd.Timedelta(days=365))]
    e = e.sort_values("published", ascending=False)
    out = {}
    for (acc, cat), g in e.groupby(["account_id", "category"], sort=False):
        out.setdefault(acc, {})[cat] = [{"date": f"{x.published:%Y-%m-%d}", "title": x.title, "publisher": None if blank(x.publisher) else x.publisher,
                                         "url": None if blank(x.url) else x.url,
                                         "confidence": None if blank(x.event_confidence) else x.event_confidence} for x in g.itertuples()]
    # newest type first
    return {a: dict(sorted(d.items(), key=lambda kv: kv[1][0]["date"], reverse=True)) for a, d in out.items()}


def chips(r, as_of):
    out = []
    news, d = r.get("news_signal"), r.get("news_signal_date")
    from_parent = r.get("news_from") == "parent"
    by_cat = r.get("_news_by_cat") if isinstance(r.get("_news_by_cat"), dict) else {}   # {event type: [headlines]}, newest first
    head = r.get("news_headline")
    if news in NEWS_EVENTS and not from_parent and not blank(head):
        # a reviewed or hand-labelled event keeps its article under the reviewed type, not the scraper's original one
        mine = [x for xs in by_cat.values() for x in xs if x["title"] == head][:1]
        by_cat = {c: [x for x in xs if x["title"] != head] for c, xs in by_cat.items()}
        by_cat[news] = mine + by_cat.get(news, [])
        by_cat = {c: xs for c, xs in by_cat.items() if xs}
    if news in NEWS_EVENTS and not from_parent:
        conf = r.get("signal_confidence") or "unrated"
        suffix = ("" if conf == "high" else " (reviewed)" if conf == "reviewed"
                  else f" (labelled by {r.get('event_labelled_by')})" if conf == "manual"
                  else f" ({r.get('event_labelled_by')})" if conf == "register" else f" ({conf} confidence, half weight)")
        det = r.get("event_detail")
        out.append([f"{news}{'' if blank(det) else ': ' + det} · {d:%b %Y}{suffix}", "signal", by_cat.get(news, [])])
    # other kinds of news event the lead had in the year: one short chip each, headlines on hover. Not scored (only the
    # strongest event counts), but two or more different events say more than one.
    for cat, items in by_cat.items():
        if cat == news and not from_parent:
            continue
        n = len(items)
        low = all(x["confidence"] == "low" for x in items)
        out.append([f"{cat} · {pd.Timestamp(items[0]['date']):%b %Y}" + (f" · {n} articles" if n > 1 else "")
                    + (" · low confidence" if low else ""), "news", items])
    # "Other" news and own-website posts are not reasons (decision 2026-11-18): they stay in the lead's news list only
    if r.get("parent_signal") in NEWS_EVENTS:       # parent news: always shown, marked; scored only when it beat the lead's own
        pd_, pdet = r.get("parent_signal_date"), r.get("parent_detail")
        out.append([f"Parent {r.get('parent_name')}: {r['parent_signal']}{'' if blank(pdet) else ' (' + pdet + ')'}"
                    + ("" if pd.isna(pd_) else f" · {pd_:%b %Y}")
                    + (" (scored, half weight)" if from_parent else " (not scored: own news is stronger)"), "parent"])
    if r.get("hiring_band") not in (None, "unknown", "none open"):
        n30, newest = r.get("jobs_new_30d"), r.get("jobs_newest")
        recency = (f" · {int(n30)} new in 30 days" if not blank(n30) and n30 > 0
                   else f" · newest {newest:%d %b %Y}" if not blank(newest) and not pd.isna(newest) else " · dates unknown")
        spike = " · hiring spike" if r.get("hiring_spike") == "Yes" else ""
        k, listed, onsite = r.get("roles_we_fill"), r.get("roles_listed"), r.get("roles_onsite")
        if blank(k):
            fill = ""
        elif k > 0:
            fill = f" · {int(k)} we fill ({r.get('roles_we_fill_categories')})"
        else:
            fill = " · all on-site roles" if not blank(onsite) and onsite == listed else " · none we fill"
        out.append([f"Hiring {r['hiring_band']} roles{recency}{fill}{spike}", "signal" if not blank(k) and k > 0 else "jobs"])
    for s in ([] if blank(r.get("service_lines")) else str(r["service_lines"]).split("; ")):
        out.append([s, "service"])
    for s in ([] if blank(r.get("sub_sectors")) else str(r["sub_sectors"]).split("; ")):
        out.append([f"Sub-sector: {s}", "info"])
        if s in L.subsector_pitch:
            out.append([f"Pitch ({s.lower()}): {L.subsector_pitch[s]}", "pitch"])
    if not blank(r.get("cqc_locations")):
        out.append([f"CQC: {int(r['cqc_locations'])} locations"
                    + (f" · {int(r['cqc_care_homes'])} care homes, {int(r['cqc_beds'])} beds" if r.get("cqc_care_homes") else "")
                    + (f" · {int(r['cqc_homecare_locations'])} home-care offices" if r.get("cqc_homecare_locations") else ""), "info"])
    if not blank(r.get("cqc_needs_improvement_180d")) and r["cqc_needs_improvement_180d"] > 0:
        n = int(r["cqc_needs_improvement_180d"])
        out.append([f"CQC: {n} location{'s' if n > 1 else ''} rated Requires improvement or Inadequate in the last 6 months", "filing"])
    fs = r.get("filing_signal")
    if not blank(fs) and fs != "None" and not str(r.get("grade", "")).startswith("Excluded"):
        fd = r.get("filing_signal_date")
        out.append([fs + ("" if blank(fd) else f" · {fd}"), "filing"])
    if not blank(r.get("apollo_latest_funding")):   # Apollo's own funding event: its own chip, compared with the news, no points
        m = r.get("apollo_vs_news")
        tail = {"matches the news": f" · matches the news ({d:%b %Y})" if not pd.isna(d) else " · matches the news",
                "news shows a different event": f" · news shows {news} instead",
                "not in the news": " · undated, not in the news"}.get(m, "")
        out.append([f"Apollo funding: {r['apollo_latest_funding']}{tail}", "apollo"])
    # fit chip: the main dashboard's rule (FIT chip_band / chip_min_lift): High band AND at least 1.5x the usual rate.
    # Bands are relative, so "High" alone flags most industries; the full detail is in the lead's panel.
    for s, lbl in (("fit_growth", "5+ seats in a year"), ("fit_reach_10", "10+ seats in 2 years"), ("fit_branch_1y", "a 2nd department in a year")):
        p, usual = r.get(f"{s}_p"), r.get(f"{s}_usual")
        if r.get(f"{s}_band") == FIT["chip_band"] and not blank(p) and not blank(usual) and p >= FIT["chip_min_lift"] * usual:
            size = f", {r['fit_size_band']} staff" if s != "fit_branch_1y" and not blank(r.get("fit_size_band")) else ""
            out.append([f"Fit: likely {lbl} ({p:.0%} vs usual {usual:.0%}{size})", "fit"])
    if not blank(r.get("parent_company")):          # Apollo's parent company field: Apollo column
        out.append([f"Part of {r['parent_company']}", "apollo"])
    # an owner or director who is an Apollo contact is not a chip (24 Nov 2026, user): the owner / director badges on
    # Best contact already say it; the "Owner / Director is an Apollo contact" filters still find them
    if not blank(r.get("competitor_client")):       # from candidates' CVs (Client Extraction)
        if r.get("competitor_client_status") == "confirmed":
            out.append([f"Competitor client: {r['competitor_client']}", "signal"])
        else:
            out.append([f"Possible competitor client, check: {r['competitor_client']} · {r.get('competitor_client_basis')}", "warn"])
    if not blank(r.get("former_name")):          # Apollo name "Old Now New": searched under the new name
        out.append([f"Renamed: was {r['former_name']}" + ("" if blank(r.get("duplicate_of_name")) else f" · same business as the {r['duplicate_of_name']} lead"), "warn"])
    elif r.get("name_check"):
        out.append([f"Check the name: {r.get('name_note')}", "warn"])
    if r.get("_on_target") is False:
        out.append([f"Check that the industry matches the list: {r.get('fit_basis') or r.get('industry_raw')}", "warn"])
    if not blank(r.get("scoring_events")) and r["scoring_events"] > 1:
        out.append([f"{int(r['scoring_events'])} separate events in 6 months (added up)", "signal"])
    if not blank(r.get("match_review")):
        out.append([f"Check match: {r['match_review']}", "warn"])
    if not blank(r.get("ownership_check")):
        out.append([f"Check ownership: {r['ownership_check']}", "warn"])
    if isinstance(r.get("internal_match"), str):
        out.append([r["internal_match"], "warn"])
    for p in filter(None, str(r.get("pitch") or "").split("; ")):
        out.append([p, "pitch"])
    return out


def grade(leads, contacts, events, as_of):
    # contacts: best contact and decision-maker counts, shown on the page; not in the score
    # a named owner (Companies House) who is an Apollo contact is the best contact; the rest keep the seniority order
    if "is_owner" in contacts.columns:
        contacts = contacts.assign(_own=~contacts["is_owner"]).sort_values(["account_id", "_own"], kind="stable").drop(columns="_own")
    c = contacts.assign(_dm=contacts["seniority"].str.lower().isin(DECISION_MAKER), _ver=contacts["email_status"].eq("Verified"))
    c["_dmv"] = c["_dm"] & c["_ver"]
    agg = c.groupby("account_id").agg(n_contacts=("name", "size"), decision_makers=("_dm", "sum"), verified_emails=("_ver", "sum"),
                                      dm_verified=("_dmv", "sum"), best_contact=("name", "first"), best_title=("title", "first"))
    leads = leads.merge(agg, on="account_id", how="left")

    leads["grade"] = leads.apply(gate, axis=1)
    scorable = elig = leads["grade"].isna()        # scored and tiered (leads outside the target industry too, since 24 Nov 2026)
    scored = score_accounts(leads.loc[scorable], as_of, SCORING)
    for k in scored.columns:
        if not k.startswith("_"):
            leads.loc[scorable, k] = scored[k]
    # website activity is not part of lead scoring (0 points), so it is not an "estimated" part either
    leads["estimated_fields"] = leads["estimated_fields"].map(
        lambda s: (", ".join(x for x in str(s).split(", ") if x != "Website") or None) if isinstance(s, str) else s)
    # tiers within each Apollo list (D3, per list since 18 Nov), ranked on the score; exact ties share the higher tier.
    # The readiness tie-break (0-4) was removed on 23 Nov 2026 (user).
    key = leads.loc[elig, "priority_score"].astype(float)
    leads["tier"] = None
    leads.loc[elig, "tier"] = percentile_tier(key, leads.loc[elig, TIER_GROUP], SCORING)
    # Tier 3 = no scored signal (user, 23 Nov 2026): no scored event (news, CQC, contract or parent, scoring_events), no
    # roles we fill posted in 30 days, not a confirmed competitor client. Fit alone doesn't count: every lead gets fit
    # points from its industry. Tiers 1-2 stay percentile ranks on the score; a lead without a signal is Tier 3 wherever
    # its score would put it.
    leads["scored_signal"] = ((pd.to_numeric(leads["scoring_events"], errors="coerce").fillna(0) > 0)
                              | (pd.to_numeric(leads["job_postings_30d"], errors="coerce").fillna(0) > 0)
                              | leads["prior_bpo_flag"].eq("Yes"))
    leads.loc[elig & ~leads["scored_signal"], "tier"] = "Tier 3"
    leads.loc[elig, "grade"] = leads.loc[elig, "tier"]
    leads["team"] = L.team
    leads["act_now"] = leads["act_now_triggers"].notna() & scorable
    leads["_news_by_cat"] = leads["account_id"].map(news_by_category(events, as_of))
    allchips = leads.apply(lambda r: chips(r, as_of), axis=1)
    # Why = relevant signals only (decision 2026-11-18); service lines, pitch and group membership go to the company profile
    # Events & signals column; Apollo-sourced chips (funding label, parent, owner contact) get their own column (23 Nov 2026)
    leads["chips"] = allchips.map(lambda cs: [c for c in cs if c[1] not in PROFILE_KINDS | {"apollo"}])
    leads["apollo_chips"] = allchips.map(lambda cs: [c for c in cs if c[1] == "apollo"])
    leads["profile_chips"] = allchips.map(lambda cs: [c for c in cs if c[1] in PROFILE_KINDS])
    order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2, "Existing client": 3, DUPLICATE: 4, "Excluded: distressed": 5}
    leads["_o"] = leads["grade"].map(order)
    leads = leads.sort_values(["_o", "priority_score"], ascending=[True, False]).drop(columns="_o")
    return leads.reset_index(drop=True)
