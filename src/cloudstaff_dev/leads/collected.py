"""Step 3: join everything the News Scraper and the register collectors gathered onto the leads."""

import pandas as pd

from .config import L
from .enrich import (
    add_cqc, add_ownership, add_roles, add_service_lines, add_subsectors, job_recency, register_events,
    review_flags)
from .events import _strength, apollo_vs_news, best_detail, hiring_band, target_check
from .helpers import blank
from .rules import (
    CONFIDENCE_FACTOR, HIRING_SCORE, NEWS_EVENTS, OTHER_NEWS_POINTS, OWN_SITE_SOURCE, PARENT_FACTOR,
    REGISTER_SCORED)


def add_collected(leads, out_dir, as_of):
    s_all = pd.read_csv(out_dir / "company_summary.csv", keep_default_na=False, na_values=[""], dtype=str)
    parents = s_all[s_all["company_id"].str.startswith("parent-")].set_index("company_id")
    s = s_all[s_all["company_id"].str.startswith("apollo-")].copy()
    s["account_id"] = "AP-" + s["company_id"].str.replace("^apollo-", "", regex=True)
    keep = {"news_status": "news_status", "news_signal": "news_signal", "news_signal_date": "news_signal_date",
            "signal_confidence": "signal_confidence", "headline": "news_headline", "url": "news_url", "publisher": "news_publisher",
            "matched_articles": "matched_articles", "distinct_stories": "distinct_stories", "events_not_other": "events_not_other",
            "company_website_articles": "company_website_articles", "possible_matches_to_review": "news_to_review",
            "jobs_status": "jobs_status", "open_roles": "open_roles", "job_postings_30d": "job_postings_30d",
            "hiring_spike": "hiring_spike", "careers_url": "careers_url", "filings_status": "filings_status",
            "filing_signal": "filing_signal", "filing_signal_date": "filing_signal_date", "registered_name": "registered_name",
            "registration_id": "company_number", "registered_status": "registered_status", "registered_on": "registered_on",
            "uk_accounts": "uk_accounts", "uk_sic": "uk_sic", "profile_status": "website_profile", "name_type": "name_type"}
    leads = leads.merge(s[["account_id"] + list(keep)].rename(columns=keep), on="account_id", how="left")
    for k in ("matched_articles", "distinct_stories", "events_not_other", "company_website_articles", "news_to_review", "open_roles", "job_postings_30d"):
        leads[k] = pd.to_numeric(leads[k], errors="coerce")
    leads["news_signal_date"] = pd.to_datetime(leads["news_signal_date"], errors="coerce")
    ev_all = pd.read_csv(out_dir / "signal_events.csv", dtype=str, keep_default_na=False, na_values=[""])
    ev_all = ev_all[ev_all["signal_type"] == "news"].copy()
    ev_all["published"] = pd.to_datetime(ev_all["published_at"], errors="coerce")
    pev = ev_all[ev_all["company_id"].str.startswith("parent-")].copy()
    ev = ev_all[ev_all["company_id"].str.startswith("apollo-")].copy()
    ev["account_id"] = "AP-" + ev["company_id"].str.replace("^apollo-", "", regex=True)

    # a person's review of the chosen event wins over the scraper's category (event_overrides.csv); applies to parents too
    overrides = pd.read_csv(L.event_overrides, dtype=str) if L.event_overrides.exists() else pd.DataFrame()
    leads["event_review"] = None
    for o in overrides.itertuples():
        hit = (leads["company_name"] == o.company_name) & leads["news_headline"].fillna("").str.startswith(o.headline_starts_with)
        leads.loc[hit, ["news_signal", "signal_confidence", "event_review"]] = [o.category, "reviewed", f"{o.reason} ({o.reviewed_on})"]
        ph = (parents["company_name"] == o.company_name) & parents["headline"].fillna("").str.startswith(o.headline_starts_with)
        parents.loc[ph, ["news_signal", "signal_confidence"]] = [o.category, "reviewed"]

    # own blog posts: no points unless the post is a relevant event. When the chosen signal is "Other" news, keep it only if
    # someone else wrote about the company in the last 180 days (dated by the newest such article); otherwise "None".
    third = ev[(ev["source"] != OWN_SITE_SOURCE) & (ev["published"] >= as_of - pd.Timedelta(days=180))]
    newest_third = third.sort_values("published").groupby("account_id").last()
    own_posts = ev[ev["source"] == OWN_SITE_SOURCE].groupby("account_id").size()
    leads["own_site_posts"] = leads["account_id"].map(own_posts).fillna(0).astype(int)
    leads["news_from"] = None
    for i, r in leads[leads["news_signal"] == "Other / Unclassified"].iterrows():
        if r["account_id"] in newest_third.index:
            t = newest_third.loc[r["account_id"]]
            leads.loc[i, ["news_signal_date", "news_headline", "news_url", "news_publisher"]] = [t["published"], t["title"], t["url"], t["publisher"]]
        else:
            leads.loc[i, ["news_signal", "news_signal_date", "news_headline", "news_url", "news_publisher"]] = ["None", pd.NaT, None, None, None]
    # decision 2026-11-18: "Other" news earns no points for leads (it isn't shown as a reason, so it mustn't move the score).
    # The articles stay in the lead's news list; other_news_date keeps the newest one for reference.
    leads["other_news_date"] = leads["news_signal_date"].where(leads["news_signal"] == "Other / Unclassified")
    if not OTHER_NEWS_POINTS:
        leads.loc[leads["news_signal"] == "Other / Unclassified", ["news_signal", "news_signal_date"]] = ["None", pd.NaT]
    is_event = leads["news_signal"].isin(NEWS_EVENTS)
    leads["news_strength_factor"] = [CONFIDENCE_FACTOR.get(c, 1.0) if e else 1.0 for c, e in zip(leads["signal_confidence"].fillna(""), is_event)]
    leads.loc[leads["news_signal"].notna() & (leads["news_signal"] != "None"), "news_from"] = "company"
    # event details (scraper NLP pass): who bought whom, amounts, new executives; only for the event already chosen
    leads["event_detail"] = [best_detail(ev[ev["account_id"] == a], s, d) if s in NEWS_EVENTS else None
                             for a, s, d in zip(leads["account_id"], leads["news_signal"], leads["news_signal_date"])]

    # parent company: its relevant event counts at PARENT_FACTOR when stronger than the lead's own news; marked "Parent"
    leads["parent_id"] = "parent-" + leads["parent_company"].fillna("").str.extract(r"\(([^()]+)\)\s*$")[0].fillna("").str.lower().str.replace("^www\\.", "", regex=True)
    pcols = {"company_name": "parent_name", "news_signal": "parent_signal", "news_signal_date": "parent_signal_date",
             "signal_confidence": "parent_confidence", "headline": "parent_headline", "url": "parent_url", "news_status": "parent_news_status"}
    leads = leads.merge(parents[list(pcols)].rename(columns=pcols), left_on="parent_id", right_index=True, how="left")
    leads["parent_signal_date"] = pd.to_datetime(leads["parent_signal_date"], errors="coerce")
    leads.loc[~leads["parent_signal"].isin(NEWS_EVENTS), ["parent_signal", "parent_signal_date", "parent_confidence", "parent_headline", "parent_url"]] = None
    for i, r in leads[leads["parent_signal"].notna()].iterrows():
        pf = CONFIDENCE_FACTOR.get(r["parent_confidence"] or "", 1.0) * PARENT_FACTOR
        if _strength(r["parent_signal"], pf, r["parent_signal_date"], as_of) > _strength(r["news_signal"], r["news_strength_factor"], r["news_signal_date"], as_of):
            leads.loc[i, ["news_signal", "news_signal_date", "signal_confidence", "news_strength_factor", "news_from"]] = \
                [r["parent_signal"], r["parent_signal_date"], r["parent_confidence"], pf, "parent"]

    # hand-labelled events (manual_events.csv, labelled_by Claude or a person): count in full when stronger than the lead's
    # own news; also added to the lead's news list so they show with who labelled them
    # registers (CQC, Find a Tender): dated facts, the same treatment, keyed by account; only REGISTER_SCORED types score
    leads["event_labelled_by"] = None
    me = pd.DataFrame(columns=["account_id", "date", "category", "headline", "url", "publisher", "labelled_by", "note", "kind", "source"])
    if L.manual_events.exists():
        me = pd.read_csv(L.manual_events, dtype=str).fillna("")
        acc = dict(zip(leads["company_name"], leads["account_id"]))
        me["account_id"] = me["company_name"].map(acc)
        unknown = me.loc[me["account_id"].isna(), "company_name"].unique()
        if len(unknown):
            print(f"manual_events.csv: no lead called {', '.join(unknown)} (check the spelling)")
        me = me[me["account_id"].notna()].assign(kind="manual", source="manual")
    reg = register_events(leads)
    # contract awards matched on a name only, not yet confirmed: listed on the lead for a person to check
    nm = reg[(reg["source"] == "fts") & (reg["match"] == "name")]
    leads["_contract_review"] = leads["account_id"].map(nm.groupby("account_id")["url"].agg(
        lambda u: f"{len(u)} contract{'s' if len(u) > 1 else ''} matched by supplier name"))
    me = pd.concat([me, reg], ignore_index=True)
    me = me[me["account_id"].isin(leads["account_id"])].copy()
    me["published"] = pd.to_datetime(me["date"], errors="coerce")
    for i, r in leads.iterrows():
        for m in me[me["account_id"] == r["account_id"]].itertuples():
            if m.kind == "register" and m.category not in REGISTER_SCORED:
                continue
            cur = _strength(leads.at[i, "news_signal"], leads.at[i, "news_strength_factor"], leads.at[i, "news_signal_date"], as_of)
            if _strength(m.category, 1.0, m.published, as_of) > cur:
                conf = "manual" if m.kind == "manual" else "register"
                leads.loc[i, ["news_signal", "news_signal_date", "signal_confidence", "news_strength_factor", "news_from",
                              "news_headline", "news_url", "news_publisher", "event_labelled_by", "event_detail"]] = \
                    [m.category, m.published, conf, 1.0, m.kind, m.headline, m.url, m.publisher, m.labelled_by, m.note or None]
    ev = pd.concat([ev, pd.DataFrame({"account_id": me["account_id"], "published_at": me["date"], "published": me["published"],
                                      "category": me["category"],
                                      "event_confidence": [("labelled by " if k == "manual" else "from ") + b for k, b in zip(me["kind"], me["labelled_by"])],
                                      "title": me["headline"], "url": me["url"], "publisher": me["publisher"],
                                      "source": me["source"], "match": me["match"] if "match" in me.columns else None})], ignore_index=True)

    # jobs: a count is only known when the careers page was read (blank = unknown, never zero)
    leads.loc[leads["jobs_status"] != "ok", "job_postings_30d"] = None
    leads = job_recency(leads, L.jobs_db)
    leads["hiring_band"] = [hiring_band(s, n) for s, n in zip(leads["jobs_status"], leads["open_roles"])]
    leads, jobs_by_lead, roles_src = add_roles(leads, L.jobs_db)
    leads["all_postings_30d"] = leads["job_postings_30d"]
    if HIRING_SCORE == "roles_we_fill" and leads["roles_we_fill_30d"].notna().any():
        # hiring points count only roles Cloudstaff fills; a read careers page with none of them is a real zero
        leads.loc[leads["jobs_status"] == "ok", "job_postings_30d"] = leads["roles_we_fill_30d"].fillna(0)
    leads = add_service_lines(leads, L.jobs_db)
    leads = add_cqc(leads)
    leads = review_flags(leads)
    leads = target_check(leads)                    # needs the Companies House UK SIC, so after the scraper results
    leads = add_subsectors(leads)
    leads = add_ownership(leads, ev, as_of)
    leads["apollo_vs_news"] = [apollo_vs_news(a, s) for a, s in zip(leads["apollo_latest_funding"], leads["news_signal"])]
    leads["parent_detail"] = [best_detail(pev[pev["company_id"] == p], s, d) if not blank(s) else None
                              for p, s, d in zip(leads["parent_id"], leads["parent_signal"], leads["parent_signal_date"])]
    for k in ("team_builder_visit", "form_fill_30d", "web_visits_30d", "diamond_referral", "prior_bpo_flag"):
        leads[k] = None                            # no website analytics or referral data for Apollo leads yet
    pev["parent_id"] = pev["company_id"]
    return leads, ev, pev, jobs_by_lead, roles_src
