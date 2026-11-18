"""Priority Score: scoring settings and formulas, shared by every pipeline that scores accounts.

Moved out of format_priority_data.ipynb (cells 0b and 8) on 2026-11-18 so that lead grading (../apollo_lead_grading/) scores
leads with exactly the same code. The notebook imports everything from here; its golden tests (workbook and dashboard
reference) must still pass with 0 mismatches after any change. Rules: BUSINESS_RULES.md section 11.2.
"""
import math

import numpy as np
import pandas as pd

__all__ = ['ACT_NOW_TARGET_SHARE', 'BDM_MIN_SCORE', 'FIT', 'NEWS_STRENGTH', 'NEWS_UNMAPPED', 'RECENCY', 'SCORING', 'SCORING_DASHBOARD', 'SCORING_DASHBOARD_REFERENCE', 'SCORING_DASHBOARD_V2', 'SCORING_DASHBOARD_V3', 'SCORING_PROFILE', 'SCORING_PROFILES', 'SCORING_WORKBOOK', 'TRIGGER_FAMILY', '_HOT', '_HOT_LIVE', '_HOT_V2', '_MODIFIER', '_TIER', '_band_value', '_blank', '_news_factor', '_strengths', '_fit_signal', '_num', '_recency', '_seat_share', '_signals', 'act_now_bonus', 'known_mean_fill', 'percentile_tier', 'score_account', 'score_accounts', 'tiers', 'xl_round']   # incl. _private names, for `from priority_scoring import *`

# ---- Scoring settings: four profiles ---------------------------------------------------------------
# "workbook":     the mock workbook's 'Settings' sheet. Kept as a regression test (must reproduce accounts.csv).
# "dashboard":    the dashboard's adjusted settings (work/account_priority_dashboard/score_adjustments.json):
#                 round points, 25% baselines, seat growth (Organic Growth) and an Act now bonus. Live until v0.2.
# "dashboard_v2": "dashboard" plus the 2026-11-10 scoring review (BUSINESS_RULES.md §11.2). Live until v0.3.
# "dashboard_v3": "dashboard_v2" plus a Fit component from the Client Propensity scores (2026-11-13). THE LIVE SETTINGS.
_HOT = {"diamond": True, "form_fill": True, "team_builder": True, "top_news": True,
        "top_news_min_strength": 1.0, "top_news_days": 30,
        # extended triggers: OFF in the workbook and reference profiles, ON in the live dashboard profile (_HOT_LIVE)
        "team_builder_prospect": False,            # Team Builder visit by a prospect (New Logo)
        "hiring_spike": False, "hiring_min_postings": 18,   # hiring spike, or 18+ job postings (New Logo)
        "heavy_visits_min": None,                  # N+ website visits in 30 days with no form fill (both goals)
        "campaign_news": [], "campaign_news_days": None}   # news categories that are Marketing triggers, and their window in days
_HOT_LIVE = {**_HOT, "team_builder_prospect": True, "hiring_spike": True, "heavy_visits_min": 10,
             "campaign_news": ["Restructuring", "Leadership change"], "campaign_news_days": 60}
_TIER = {"tier1": 70, "tier2": 40, "cap_tier1_on_coverage": False, "tier1_min_coverage": 0.6}
_MODIFIER = {"at_trend_0": 0.9, "at_trend_1": 1.1}

SCORING_WORKBOOK = {
    "max_points": {"New Logo":       {"web": 35, "news": 35, "diamond": 15, "bpo": 15, "seat": 0},
                   "Organic Growth": {"web": 50, "news": 50, "diamond": 0,  "bpo": 0,  "seat": 0}},
    "baseline":   {"web": 0.35, "news": 0.30, "seat": 0.0},    # share of max used when a component is unknown
    "web":        {"tb_share": 0.4, "ff_share": 0.3, "vol_share": 0.3, "vol_cap": 20},
    "news":       {"news_share": 0.6, "jobs_share": 0.4, "jobs_cap": 20},
    "seat_bands": [],
    "modifier":   _MODIFIER, "tier": _TIER, "hot": _HOT,
    "act_now_bonus": None,
    "round_signals": 3,                                       # the workbook rounds each 0-1 signal to 3 decimals
}
SCORING_DASHBOARD = {
    "max_points": {"New Logo":       {"web": 40, "news": 40, "diamond": 10, "bpo": 10, "seat": 0},     # bpo = Competitor client
                   "Organic Growth": {"web": 40, "news": 40, "diamond": 0,  "bpo": 0,  "seat": 20}},
    "baseline":   {"web": 0.25, "news": 0.25, "seat": 0.25},
    "web":        {"tb_share": 0.5, "ff_share": 0.25, "vol_share": 0.25, "vol_cap": 20},
    "news":       {"news_share": 0.625, "jobs_share": 0.375, "jobs_cap": 20},
    "seat_bands": [(0, 0.0), (1, 0.25), (6, 0.5), (11, 1.0)],  # seats added in ~6 months (from) -> share of seat max
    "modifier":   _MODIFIER, "tier": _TIER, "hot": _HOT_LIVE,
    "act_now_bonus": {"default": 15, "Diamond referral": 7.5},   # every trigger; added after the industry nudge; Diamond already earns flag points
    "round_signals": None,
}
# The dashboard profile WITHOUT the extended triggers: what the mock dashboard's prep.py produced. Used by golden test 2 only.
SCORING_DASHBOARD_REFERENCE = {**SCORING_DASHBOARD, "hot": _HOT}
# dashboard_v2 (live until v0.3): the scoring review of 2026-11-10. Same points and signals as "dashboard", plus:
#   * rarer Act now triggers: heavy website visits need 20+ visits (was 10), restructuring / leadership news 30 days (was 60)
#   * every trigger adds to the bonus, not only the first: the best bonus per trigger family (TRIGGER_FAMILY), the families
#     sorted by bonus, and each further family worth stack_decay x the one before (15, then +7.5, then +3.75 ...)
#   * an unknown component is scored at the AVERAGE signal of the same goal's accounts where it is known (not a flat 25%)
#   * tiers by rank within each goal (top 10% Tier 1, next 30% Tier 2), not fixed scores
#   * sort_key = score: the bonus moves Act now accounts up, but they are no longer pinned above every other account
# Profiles that leave these keys out keep the old behaviour (flat baseline, first trigger only, score tiers, +1000 sort).
_HOT_V2 = {**_HOT_LIVE, "heavy_visits_min": 20, "campaign_news_days": 30}
SCORING_DASHBOARD_V2 = {
    **SCORING_DASHBOARD,
    "hot": _HOT_V2,
    "unknown_fill": "known_mean",          # "known_mean" or "baseline"; "baseline" (25%) stays the fallback when no account of a goal has the signal
    "act_now_bonus": {"default": 15, "Diamond referral": 7.5, "stack_decay": 0.5},
    "tier": {"method": "percentile", "tier1_share": 0.10, "tier2_share": 0.30},   # share of each goal's accounts; ties share the higher tier
    "hot_first": False,                    # True = the workbook's sort_key (+1000 for any Act now trigger)
}
# dashboard_v3 (LIVE, 2026-11-13): dashboard_v2 plus a FIT component from the Client Propensity scores (stage 7b), rolled
# into priority_score like the other signals. Points: Organic Growth fit 25 (website 30, news/jobs 30, seat growth 15),
# New Logo fit 20 (website 30, news/jobs 30, Diamond 10, Competitor client 10). Seat growth drops 20 -> 15 because the
# seat-milestone fit already reuses recent seat adds (rank correlation 0.53 with seats_added_6m).
# The 0-1 fit signal blends the account's propensity bands (band_value):
#   Organic Growth: seat part x seat_weight + department part x dept_weight. Seat part = the band of the client's NEXT seat
#     milestone (1-4 seats -> 5+, 5-9 -> 10+, 10-19 -> 20+; 20+ seats has none). Department part = fit_second_dept_band, for
#     ONE-department clients only (banded among them): the goal is clients that start with one department and grow past it.
#     Clients with 2+ departments score multi_dept_value (0) on the department part, with the weights kept, so their fit
#     is at most seat_weight (15 of 25 points) and one-department clients likely to add a second rank above them. 2+
#     departments with no seat milestone (20+ seats) = fit unknown (the goal's average).
#   New Logo (industry|country profile, "if we sign them"): growth part x growth_weight + department part x dept_weight.
#     Growth part = the better of the 5-seat (1 year) and 10-seat (2 years) bands; department part = fit_branch_1y_band.
#   A missing part leaves the other on its own. No fit at all (e.g. a client with no current seats) = an unknown component:
#   the average fit of the same goal's accounts (unknown_fill), listed in estimated_fields as "Fit".
FIT = {
    "band_value": {"High": 1.0, "Medium": 0.5, "Low": 0.0},
    "Organic Growth": {"seat_weight": 0.6, "dept_weight": 0.4, "multi_dept_value": 0.0},
    "New Logo": {"growth_weight": 0.75, "dept_weight": 0.25,   # 15 + 5 of the 20 fit points (2026-11-13; was 0.7 / 0.3)
                 # the "Likely 5+ seats" chip compares a prospect with the AVERAGE PROSPECT on the list ("prospects"), not with past
                 # new clients ("clients"): prospects are scored as an unknown role launching with 1-2 staff, so they average 5.7%
                 # against 9.6% for past new clients, and none would reach 1.5x the latter
                 "growth_compare": "prospects"},
    "chip_band": "High",                   # a fit chip (Why column) shows when that score's band is this ...
    "chip_min_lift": 1.5,                  # ... AND its chance is at least this many times the usual rate (the score's
                                           # historical base rate). Bands are relative: the top third of 1-4 seat clients
                                           # starts at 5%, below the usual 7%, and New Logo profiles barely differ from average
}
SCORING_DASHBOARD_V3 = {
    **SCORING_DASHBOARD_V2,
    "max_points": {"New Logo":       {"web": 30, "news": 30, "diamond": 10, "bpo": 10, "seat": 0,  "fit": 20},
                   "Organic Growth": {"web": 30, "news": 30, "diamond": 0,  "bpo": 0,  "seat": 15, "fit": 25}},
    "baseline": {**SCORING_DASHBOARD_V2["baseline"], "fit": 0.25},   # fallback only (unknown_fill = known_mean)
    # News and jobs: news and hiring 15 points each of the 30 (2026-11-13; dashboard / dashboard_v2: 0.625 / 0.375 = 18.75 / 11.25)
    "news": {**SCORING_DASHBOARD_V2["news"], "news_share": 0.5, "jobs_share": 0.5},
    "fit": FIT,
}
assert all(abs(sum(w for k, w in v.items() if k.endswith("_weight")) - 1) < 1e-9 for g, v in FIT.items()
           if g in ("Organic Growth", "New Logo")), "fit weights must add up to 1"
ACT_NOW_TARGET_SHARE = 0.10                # DQ warning when more than this share of a goal's accounts has an Act now trigger
SCORING_PROFILES = {"workbook": SCORING_WORKBOOK, "dashboard_reference": SCORING_DASHBOARD_REFERENCE,
                    "dashboard": SCORING_DASHBOARD, "dashboard_v2": SCORING_DASHBOARD_V2, "dashboard_v3": SCORING_DASHBOARD_V3}
SCORING_PROFILE = "dashboard_v3"
SCORING = SCORING_PROFILES[SCORING_PROFILE]
for name, prof in SCORING_PROFILES.items():
    assert all(sum(v.values()) == 100 for v in prof["max_points"].values()), f"{name}: max points must total 100 per goal"
NEWS_STRENGTH = {                              # order matters for the mock generator
    "Funding round": 1.0, "PE buyout": 1.0, "M&A": 0.8, "Expansion / new office": 0.7,
    "Restructuring": 0.5, "Leadership change": 0.3, "Other / Unclassified": 0.3, "None": 0.0,
}
NEWS_UNMAPPED = "Other / Unclassified"         # strength used for a category not in the table
RECENCY = [(0, 1.0), (31, 0.7), (91, 0.4), (181, 0.0)]   # (days since news, from) -> factor

BDM_MIN_SCORE = 60                             # the workbook's fixed 'New Logo score sent to BDM' (workbook golden test only)

# ---- Act now trigger -> family. Stacked bonuses count one trigger per family (they measure the same thing) --------
TRIGGER_FAMILY = {
    "Diamond referral": "Referral",
    "Form fill": "Website", "Team Builder visit": "Website", "Heavy website visits": "Website",
    "Funding round": "News", "PE buyout": "News", "Restructuring": "News", "Leadership change": "News",
    "Hiring spike": "Hiring",
}


# ---- Formulas ----------------------------------------------------------------------------------------
def xl_round(x, digits=0):
    """Excel ROUND: half away from zero (Python's round() is half-to-even)."""
    m = 10 ** digits
    return math.copysign(math.floor(abs(x) * m + 0.5 + 1e-9) / m, x)

def _blank(v):
    return v is None or (not isinstance(v, str) and pd.isna(v)) or v == ""

def _num(v):
    return 0 if _blank(v) else float(v)

def _recency(days):
    return next(f for lo, f in reversed(RECENCY) if days >= lo)

def _strengths(S):
    """News strengths: NEWS_STRENGTH plus a profile's optional "news_strength_extra" (new categories, e.g. lead grading's
    "Contract / partnership win"). Kept out of NEWS_STRENGTH itself, whose order drives the mock generator."""
    extra = S.get("news_strength_extra") if S else None
    return {**NEWS_STRENGTH, **extra} if extra else NEWS_STRENGTH

def _news_factor(r):
    """Optional per-row multiplier on the news strength (column news_strength_factor; blank or missing = 1). Lead grading
    sets 0.5 for medium / low confidence events (decision 2026-11-18). The main pipeline doesn't set it, so it scores as before."""
    f = r.get("news_strength_factor")
    return 1.0 if _blank(f) else float(f)

def _seat_share(seats, bands):
    return next(share for lo, share in reversed(bands) if seats >= lo)

def _band_value(band, F):
    return None if _blank(band) else F["band_value"].get(band)

def _fit_signal(r, S):
    """One account's 0-1 fit signal from its Client Propensity bands (S["fit"], see FIT); None = unknown (no fit score)."""
    F = S.get("fit")
    if not F or not S["max_points"][r["goal"]].get("fit", 0):
        return None
    if r["goal"] == "Organic Growth":
        W = F["Organic Growth"]
        # department part: one-department clients only (do they grow past one department?). 2+ departments score
        # multi_dept_value (0) on it with the weights kept, so their fit is at most seat_weight
        seat = _band_value(r.get("fit_seat_milestone_band"), F)
        n = r.get("depts_so_far")
        if not _blank(n) and n > 1:
            return None if seat is None else round(seat * W["seat_weight"] + W["multi_dept_value"] * W["dept_weight"], 3)
        parts = [(seat, W["seat_weight"]), (_band_value(r.get("fit_second_dept_band"), F), W["dept_weight"])]
    else:
        W = F["New Logo"]
        growth = [v for v in (_band_value(r.get("fit_growth_band"), F), _band_value(r.get("fit_reach_10_band"), F)) if v is not None]
        parts = [(max(growth) if growth else None, W["growth_weight"]), (_band_value(r.get("fit_branch_1y_band"), F), W["dept_weight"])]
    known = [(v, w) for v, w in parts if v is not None]
    return round(sum(v * w for v, w in known) / sum(w for _, w in known), 3) if known else None

def _signals(r, as_of, S):
    """One account's 0-1 signals (website, news/jobs, seat growth, fit); None = unknown."""
    W, N = S["web"], S["news"]
    rnd_sig = (lambda x: xl_round(x, S["round_signals"])) if S["round_signals"] is not None else (lambda x: x)
    web = None if _blank(r["web_visits_30d"]) else rnd_sig(
        (W["tb_share"] if r["team_builder_visit"] == "Yes" else 0)
        + (W["ff_share"] if _num(r["form_fill_30d"]) > 0 else 0)
        + min(float(r["web_visits_30d"]) / W["vol_cap"], 1) * W["vol_share"])
    news, ndate = r["news_signal"], r["news_signal_date"]
    if _blank(news) and _blank(r["job_postings_30d"]):
        nj = None
    else:
        strength = 0 if _blank(news) else _strengths(S).get(news, NEWS_STRENGTH[NEWS_UNMAPPED]) * _news_factor(r)
        rec = 1 if _blank(news) or _blank(ndate) else _recency((as_of - ndate).days)
        hire = 1 if r["hiring_spike"] == "Yes" else min(_num(r["job_postings_30d"]) / N["jobs_cap"], 1)
        nj = rnd_sig(N["news_share"] * strength * rec + N["jobs_share"] * hire)
    seat_max = S["max_points"][r["goal"]].get("seat", 0)
    seats = r.get("seats_added_6m")
    seat = None if not seat_max or _blank(seats) else _seat_share(float(seats), S["seat_bands"])
    return web, nj, seat, _fit_signal(r, S)

def known_mean_fill(recs, as_of, S):
    """Share of max used for an unknown component, per goal and component: the average signal of the accounts of that
    goal where the component is known (S["baseline"] when none is known). Rounded to 3 decimals."""
    sig = pd.DataFrame([dict(zip(("web", "news", "seat", "fit"), _signals(r, as_of, S)), goal=r["goal"]) for r in recs])
    fill = {}
    for goal, d in sig.groupby("goal"):
        fill[goal] = {}
        for comp in ("web", "news", "seat", "fit"):
            known = pd.to_numeric(d[comp], errors="coerce").dropna()
            fill[goal][comp] = round(float(known.mean()), 3) if len(known) else S["baseline"].get(comp, 0.25)
    return fill

def act_now_bonus(triggers, A):
    """Bonus points for an account's Act now triggers (A = S["act_now_bonus"]). Without "stack_decay" only the first
    trigger counts (the dashboard profile); with it, the best bonus per trigger family, sorted, each further family
    worth stack_decay x the one before."""
    if not triggers or not A:
        return 0
    if A.get("stack_decay") is None:
        return A.get(triggers[0], A["default"])
    best = {}
    for t in triggers:
        fam = TRIGGER_FAMILY.get(t, t)
        best[fam] = max(best.get(fam, 0), A.get(t, A["default"]))
    return sum(b * A["stack_decay"] ** i for i, b in enumerate(sorted(best.values(), reverse=True)))

def score_account(r, as_of, S, fill=None):
    """One account through the scoring formulas with settings profile S. fill = share of max for an unknown component
    ({"web", "news", "seat", "fit"}); None = the profile's flat baseline."""
    goal = r["goal"]
    nl = goal == "New Logo"
    mx, H = S["max_points"][goal], S["hot"]
    F = fill or S["baseline"]

    # industry modifier
    trend = r["industry_trend"]
    mod = 1.0 if _blank(trend) else xl_round(S["modifier"]["at_trend_0"]
                                             + trend * (S["modifier"]["at_trend_1"] - S["modifier"]["at_trend_0"]), 3)
    # signals (0-1); None = unknown
    web, nj, seat, fit = _signals(r, as_of, S)
    seat_max, fit_max = mx.get("seat", 0), mx.get("fit", 0)

    # points (unknown -> fill share of max)
    web_pts = xl_round(mx["web"] * (F["web"] if web is None else web), 1)
    news_pts = xl_round(mx["news"] * (F["news"] if nj is None else nj), 1)
    seat_pts = xl_round(seat_max * (F["seat"] if seat is None else seat), 1) if seat_max else None
    fit_pts = xl_round(fit_max * (F.get("fit", S["baseline"].get("fit", 0.25)) if fit is None else fit), 1) if fit_max else None
    dia = (mx["diamond"] if r["diamond_referral"] == "Yes" else 0) if nl else "N/A"
    bpo = (mx["bpo"] if r["prior_bpo_flag"] == "Yes" else 0) if nl else "N/A"
    base = xl_round(web_pts + news_pts + (dia + bpo if nl else 0) + (seat_pts or 0) + (fit_pts or 0), 1)
    raw = base * mod
    score_before = int(xl_round(min(raw, 100), 0))

    # Act now triggers: every one that applies, in priority order; the first is hot_trigger (it decides the team)
    news, ndate = r["news_signal"], r["news_signal_date"]
    news_age = None if _blank(news) or _blank(ndate) else (as_of - ndate).days
    top_news = (H["top_news"] and news_age is not None and _strengths(S).get(news, 0) * _news_factor(r) >= H["top_news_min_strength"]
                and news_age <= H["top_news_days"])
    hiring = nl and H["hiring_spike"] and (r["hiring_spike"] == "Yes" or _num(r["job_postings_30d"]) >= H["hiring_min_postings"])
    heavy = (H["heavy_visits_min"] is not None and _num(r["web_visits_30d"]) >= H["heavy_visits_min"]
             and not _num(r["form_fill_30d"]) > 0)
    # _news_factor(r) < 1 (half-weight evidence: a parent's news, or medium / low confidence in lead grading) never triggers
    # Act now; the main pipeline doesn't set the factor, so this changes nothing there
    campaign = (news_age is not None and news in H["campaign_news"] and news_age <= H["campaign_news_days"]
                and _news_factor(r) >= 1)
    triggers = []
    if nl and r["diamond_referral"] == "Yes" and H["diamond"]:
        triggers.append("Diamond referral")
    if _num(r["form_fill_30d"]) > 0 and H["form_fill"]:
        triggers.append("Form fill")
    if r["team_builder_visit"] == "Yes" and (H["team_builder"] if not nl else H["team_builder_prospect"]):
        triggers.append("Team Builder visit")                  # a client's visit (Organic Growth) or a prospect's (New Logo)
    if top_news:
        triggers.append(news)                                  # Funding round / PE buyout in the last 30 days
    if hiring:
        triggers.append("Hiring spike")
    if heavy:
        triggers.append("Heavy website visits")                # Marketing trigger
    if campaign:
        triggers.append(news)                                  # Restructuring / Leadership change: Marketing trigger
    hot = triggers[0] if triggers else None

    # Act now bonus, added after the industry nudge; the score is capped at 100
    bonus = act_now_bonus(triggers, S["act_now_bonus"])
    score = int(xl_round(min(raw + bonus, 100), 0)) if bonus else score_before

    unknown = [("Website", web is None), ("News", nj is None), ("Seat growth", bool(seat_max) and seat is None),
               ("Fit", bool(fit_max) and fit is None)]
    est = ", ".join(name for name, unk in unknown if unk) or None
    known = ((0 if web is None else mx["web"]) + (0 if nj is None else mx["news"])
             + (mx["diamond"] + mx["bpo"] if nl else 0) + (seat_max if seat is not None else 0) + (fit_max if fit is not None else 0))
    T = S["tier"]
    coverage = known / sum(mx.values())
    if T.get("method", "score") == "score":
        tier = ("Tier 1" if score >= T["tier1"] and (not T["cap_tier1_on_coverage"] or coverage >= T["tier1_min_coverage"])
                else "Tier 2" if score >= T["tier2"] else "Tier 3")
    else:
        tier = None                                            # percentile tiers need every account: set in score_accounts()
    return {
        "industry_modifier": mod, "web_signal (0-1)": web, "news_jobs_signal (0-1)": nj, "seat_signal (0-1)": seat,
        "web_pts": web_pts, "news_jobs_pts": news_pts, "seat_pts": seat_pts, "diamond_pts": dia, "bpo_pts": bpo,
        "fit_signal (0-1)": fit, "fit_pts": fit_pts,
        "base_points": base, "score_before_bonus": score_before, "act_now_bonus": bonus, "priority_score": score,
        "estimated_fields": est, "data_coverage": round(coverage, 4), "hot_trigger": hot,
        "act_now_triggers": "; ".join(triggers) or None, "tier": tier,
        "sort_key": score + (1000 if hot and S.get("hot_first", True) else 0),
        # the workbook's own routing (Organic Growth -> AM), only for the workbook golden test
        "_workbook_team": "AM" if not nl else ("BDM" if (r["diamond_referral"] == "Yes" or hot or score >= BDM_MIN_SCORE) else "SDR"),
    }

def percentile_tier(scores, goals, S=SCORING):
    """Tier by rank within each goal: the top tier1_share of a goal's accounts are Tier 1, the next tier2_share Tier 2.
    An account's position = share of its goal's accounts that score strictly higher, so ties share the higher tier."""
    T = S["tier"]
    scores, goals = pd.Series(scores), pd.Series(goals, index=pd.Series(scores).index)
    above = (scores.groupby(goals).rank(method="min", ascending=False) - 1) / goals.map(goals.value_counts())
    return pd.Series(np.select([above < T["tier1_share"], above < T["tier1_share"] + T["tier2_share"]],
                               ["Tier 1", "Tier 2"], "Tier 3"), index=scores.index)

def tiers(scores, goals, S=SCORING):
    """Tier for a set of scores (e.g. the score before the bonus) with profile S's tier rule."""
    T = S["tier"]
    if T.get("method", "score") == "percentile":
        return percentile_tier(scores, goals, S)
    return pd.Series(scores).map(lambda v: "Tier 1" if v >= T["tier1"] else "Tier 2" if v >= T["tier2"] else "Tier 3")

def score_accounts(df, as_of, S):
    recs = df.to_dict("records")
    fill = known_mean_fill(recs, as_of, S) if S.get("unknown_fill") == "known_mean" else {}
    out = pd.DataFrame([score_account(r, as_of, S, fill.get(r["goal"])) for r in recs], index=df.index)
    if S["tier"].get("method", "score") == "percentile":
        out["tier"] = percentile_tier(out["priority_score"], df["goal"], S)
    return out
