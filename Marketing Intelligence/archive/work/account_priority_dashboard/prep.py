"""Prepare the Account Priority Dashboard data (mock, fictional accounts).

Reads (never modified):
    reference materials/data/accounts.csv           400 scored accounts exported from the mock workbook
    reference materials/data/scoring_settings.json  weights, baselines, thresholds (matches the Settings sheet)
Writes:
    data/account_priority_dashboard.json            embedded in the page by build_dashboard.py

Triggers and routing come from the workbook (the reference implementation of the scoring logic). Two changes
are made on top of it, both set in score_adjustments.json next to this script:
    1. Seat growth (Organic Growth only): seats the client added in the last 6 months, read from seat_growth.csv
       (account_id, seats_added_6m; blank = unknown). Bands 0 / 1-5 / 6-10 / 11+ earn a share of seat_max_og points.
       The 50 + 50 + 30 = 130 points are rescaled to 100: Website and News and jobs 38.5 each, Seat growth 23.
       Unknown seat data uses the base_seats baseline and is flagged as estimated. New Logo is unchanged.
       Organic Growth scores are rebuilt from the signals in accounts.csv; the workbook's own score and tier are
       kept as csv_score and csv_tier.
    2. Act now bonus: accounts with an Act now trigger get hot_bonus extra points (hot_bonus_diamond, 7.5, when the trigger
       is a Diamond referral, because that already adds flag points), added after the industry
       nudge, with the score capped at 100. Tier and list order are then recalculated from the new score.
       The score and tier before the bonus are kept as workbook_score and workbook_tier.
Routing does not change: Organic Growth is always AM, and every Act now account is already on the BDM or AM list.
The rest only reshapes data for display: the "Why" chips, profile line and filter labels.

Run from the "Marketing Intelligence" folder:
    ../.venv/Scripts/python.exe work/account_priority_dashboard/prep.py
"""
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))   # the "Marketing Intelligence" folder
os.chdir(ROOT)
SRC = "reference materials/data/accounts.csv"
SETTINGS = "reference materials/data/scoring_settings.json"
ADJUST = "work/account_priority_dashboard/score_adjustments.json"
SEATS = "work/account_priority_dashboard/seat_growth.csv"
EXTRA = "work/account_priority_dashboard/accounts_extra.csv"   # 400 more mock accounts (make_mock_data.py), doubling the dataset
ROLES = "work/account_priority_dashboard/account_roles.csv"    # mock owner role per account: Marketing, SDR or BDM
OUT = "data/account_priority_dashboard.json"
AS_OF = "2026-11-08"          # as-of date for news recency in the mock workbook (generate_mock_workbook.py, AS_OF)
ROLE_ORDER = ["Marketing", "SDR", "BDM"]
GOALS = ["New Logo", "Organic Growth"]
LISTS = [f"{r}|{g}" for r in ROLE_ORDER for g in GOALS if not (r == "SDR" and g == "Organic Growth")]   # SDR has no Organic Growth list

# display rules for the "Why" chips (the same as the original mock dashboard)
STRONG, MODERATE = 0.66, 0.33  # strength dots: ●●● >= 66% of max, ●●○ >= 33%, ●○○ > 0
GROWING_INDUSTRY = 0.7         # industry trend at or above this shows a "Growing industry" chip
BAND_ORDER = ["1-10", "11-50", "51-200", "201-500", "500+"]


def blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or v == ""


def dots(s):
    return "●●●" if s >= STRONG else "●●○" if s >= MODERATE else "●○○"


def chips(a):
    """Reasons shown in the Why column: [text, kind]; kind = signal | flag | est."""
    out = []
    w = None if blank(a.web_signal) else float(a.web_signal)
    n = None if blank(a.news_jobs_signal) else float(a.news_jobs_signal)
    if w and w > 0:
        lab = "Team Builder visit" if a.goal == "Organic Growth" and a.team_builder_visit == "Yes" else "Website"
        out.append([f"{lab} {dots(w)}", "signal"])
    if n and n > 0:
        lab = a.news_signal if not blank(a.news_signal) and a.news_signal != "None" else "Hiring spike" if a.hiring_spike == "Yes" else "Job postings"
        out.append([f"{lab} {dots(n)}", "signal"])
    if a.goal == "Organic Growth" and not blank(a.seat_signal) and a.seat_signal > 0:
        out.append([f"{a.seat_band} seats added {dots(a.seat_signal)}", "signal"])
    if not blank(a.industry_trend) and float(a.industry_trend) >= GROWING_INDUSTRY:
        out.append(["Growing industry", "signal"])
    if a.diamond_referral == "Yes":
        out.append(["Diamond referral", "flag"])
    if a.competitor_client == "Yes":
        out.append(["Competitor client", "flag"])
    if not blank(a.estimated_fields):
        out.append(["No " + a.estimated_fields.lower().replace(", seat growth", " or seat growth").replace(", ", " or ") + " data", "est"])
    return out


def clean(v):
    """NaN -> None so the JSON is valid; numpy scalars -> Python."""
    if blank(v):
        return None
    return v.item() if hasattr(v, "item") else v


def seat_band(n):
    """Band label and settings key for seats added in 6 months; None = unknown."""
    if blank(n):
        return None, None
    n = int(n)
    return ("0", "seat_0") if n <= 0 else ("1-5", "seat_1_5") if n <= 5 else ("6-10", "seat_6_10") if n <= 10 else ("11+", "seat_11")


def rescore(df, s, news, rec, seats=True):
    """Rebuild every account's signals, points, score and list from the raw data and the settings in `s`.
    Same rules as the workbook: unknown signal -> baseline share of the max, points = signal x max,
    score = round half up(points x industry modifier) capped at 100. Routing: Organic Growth -> AM; New Logo -> BDM with a
    Diamond referral, any Act now trigger or a score of bdm_min or more, else SDR. seats=False leaves Organic Growth without seat growth.
    `news` maps news type -> strength, `rec` lists the four recency factors."""
    og = df.goal.eq("Organic Growth")
    age = (pd.Timestamp(AS_OF) - pd.to_datetime(df.news_signal_date)).dt.days
    rf = age.map(lambda a: 0 if pd.isna(a) else rec[0] if a <= 30 else rec[1] if a <= 90 else rec[2] if a <= 180 else rec[3])
    strength = df.news_signal.map(news).fillna(0)
    hire = pd.Series(np.where(df.hiring_spike.eq("Yes"), 1, np.minimum(df.job_postings_30d.fillna(0) / s["jobs_cap"], 1)), index=df.index)
    est = df.estimated_fields.fillna("")                 # "Website" / "News" listed = never collected (unknown); blank but not listed = checked, real zero
    web_known, nj_known = ~est.str.contains("Website"), ~est.str.contains("News")
    web_sig = (s["tb_share"] * df.team_builder_visit.eq("Yes") + s["ff_share"] * (df.form_fill_30d.fillna(0) > 0)
               + s["vol_share"] * np.minimum(df.web_visits_30d.fillna(0) / s["vol_cap"], 1)).where(web_known)
    nj_sig = (s["news_share"] * strength * rf + s["jobs_share"] * hire).where(nj_known)
    r1 = lambda v: np.floor(v * 10 + 0.5 + 1e-9) / 10    # the workbook rounds each component to 1 decimal (half up) before adding
    out = pd.DataFrame(index=df.index)
    out["web_signal"], out["news_jobs_signal"] = web_sig, nj_sig
    out["web_pts"] = r1(web_sig.fillna(s["base_web"]) * np.where(og, s["web_max_og"], s["web_max_nl"]))
    out["news_jobs_pts"] = r1(nj_sig.fillna(s["base_news"]) * np.where(og, s["news_max_og"], s["news_max_nl"]))
    out["diamond_pts"] = (df.diamond_referral.eq("Yes") & ~og) * s["dia_max"]
    out["bpo_pts"] = (df.prior_bpo_flag.eq("Yes") & ~og) * s["bpo_max"]
    seat_pts = pd.Series(0.0, index=df.index)
    if seats:
        band = df.seats_added_6m.map(seat_band)
        out["seat_band"] = band.map(lambda t: t[0])
        out["seat_signal"] = band.map(lambda t: None if t[1] is None else s[t[1]]).astype(float)
        seat_pts = r1(out.seat_signal.fillna(s["base_seats"]) * s["seat_max_og"]).where(og, 0.0)
        out["seat_pts"] = seat_pts.where(og)
    out["base_points"] = r1(out.web_pts + out.news_jobs_pts + out.diamond_pts + out.bpo_pts + seat_pts)
    out["raw_score"] = out.base_points * df.industry_modifier                          # before rounding
    out["priority_score"] = (out.raw_score.clip(upper=100) + 0.5).map(math.floor)
    hot = df.hot_trigger.notna()
    out["assigned_team"] = np.where(og, "AM", np.where(df.diamond_referral.eq("Yes") | hot | (out.priority_score >= s["bdm_min"]), "BDM", "SDR"))
    return out


def tier(score, s):
    return "Tier 1" if score >= s["tier1"] else "Tier 2" if score >= s["tier2"] else "Tier 3"


def apply_bonus(df, s):
    """Act now bonus on top of the score. A Diamond referral trigger earns hot_bonus_diamond (it already adds flag points),
    any other trigger earns hot_bonus. The bonus is added to the unrounded score, then rounded half up and capped at 100."""
    hot = df.hot_trigger.notna()
    bonus = df.hot_trigger.eq("Diamond referral").map({True: s["hot_bonus_diamond"], False: s["hot_bonus"]}) * hot
    score = ((df.raw_score + bonus).clip(upper=100) + 0.5).map(math.floor).astype(int)
    return score, score.map(lambda v: tier(v, s)), score + 1000 * hot   # sort key as in the workbook: Act now first, then score


def main():
    ref = pd.read_csv(SRC, dtype={"employee_band": str})
    extra = pd.read_csv(EXTRA, dtype={"employee_band": str})
    assert list(extra.columns) == list(ref.columns), "accounts_extra.csv must have the same columns as accounts.csv"
    df = pd.concat([ref, extra], ignore_index=True)
    assert df.account_id.is_unique and df.company_name.is_unique, "duplicate account or company in accounts.csv + accounts_extra.csv"
    adjust = json.load(open(ADJUST, encoding="utf-8"))
    over = {r["key"] for r in adjust}                      # adjustments replace a setting with the same key
    settings = [r for r in json.load(open(SETTINGS, encoding="utf-8")) if r["key"] not in over] + adjust
    s = {r["key"]: r["value"] for r in settings}
    # the workbook's tier and sort rules, checked before the bonus is applied on top
    assert (df.priority_score.map(lambda v: tier(v, s)) == df.tier).all(), "tier rule no longer matches the workbook"
    assert (df.sort_key == df.priority_score + 1000 * df.hot_trigger.notna()).all(), "sort rule no longer matches the workbook"
    df["csv_score"], df["csv_tier"], df["csv_team"] = df.priority_score, df.tier, df.assigned_team
    # the workbook's own settings must reproduce accounts.csv exactly before any change is made on top of it
    s0 = {r["key"]: r["value"] for r in json.load(open(SETTINGS, encoding="utf-8"))}
    news = {r["label"]: r["value"] for r in settings if r["kind"] == "news"}
    rec = [r["value"] for r in settings if r["kind"] == "recency"]
    chk = rescore(df, s0, news, rec, seats=False)
    assert (chk.priority_score == df.priority_score).all() and (chk.assigned_team == df.assigned_team).all(), "the workbook rules no longer reproduce accounts.csv"
    assert (chk.web_signal.fillna(-1) - df.web_signal.fillna(-1)).abs().max() < 1e-9 and (chk.news_jobs_signal.fillna(-1) - df.news_jobs_signal.fillna(-1)).abs().max() < 1e-9
    seats = pd.read_csv(SEATS)
    assert seats.account_id.is_unique and set(seats.account_id) == set(df[df.goal == "Organic Growth"].account_id), \
        "seat_growth.csv must have exactly one row for each Organic Growth account"
    df = df.merge(seats, on="account_id", how="left")
    roles = pd.read_csv(ROLES)
    assert roles.account_id.is_unique and set(roles.account_id) == set(df.account_id), "account_roles.csv must have one row per account"
    df = df.merge(roles, on="account_id", how="left")
    assert set(df.role) <= set(ROLE_ORDER) and not ((df.role == "SDR") & (df.goal == "Organic Growth")).any(), "SDR owns New Logo accounts only"
    new = rescore(df, s, news, rec)
    for c in new.columns:
        df[c] = new[c]
        og = df.goal == "Organic Growth"
    unknown = og & df.seat_signal.isna()
    df["estimated_fields"] = [("Seat growth" if pd.isna(e) else f"{e}, Seat growth") if u else e for e, u in zip(df.estimated_fields, unknown)]
    df["tier"] = df.priority_score.map(lambda v: tier(v, s))
    df["workbook_score"], df["workbook_tier"] = df.priority_score, df.tier      # before the Act now bonus
    df["priority_score"], df["tier"], df["sort_key"] = apply_bonus(df, s)
    # shown as "Competitor client": a past client of a competing outsourcing provider (source column prior_bpo_flag)
    df = df.rename(columns={"prior_bpo_flag": "competitor_client", "bpo_pts": "competitor_pts"})
    rows = []
    for a in df.itertuples(index=False):
        r = {k: clean(v) for k, v in a._asdict().items()}
        r.update({
            "team": f"{a.role}|{a.goal}",          # the list: owner role x goal
            "industry_lbl": "Unknown" if blank(a.industry) else a.industry,
            "band_lbl": "Unknown" if blank(a.employee_band) else a.employee_band,
            "profile": " · ".join([
                "Industry unknown" if blank(a.industry) else a.industry,
                "Size unknown" if blank(a.employee_band) else f"{a.employee_band} staff",
                "Region unknown" if blank(a.region) else a.region]),
            "chips": chips(a),
            "estimated": 0 if blank(a.estimated_fields) else 1,
            "seats_added_6m": clean(a.seats_added_6m),
        })
        rows.append(r)
    rows.sort(key=lambda r: (-r["sort_key"], r["company_name"]))   # Act now first, then score (sort_key from the workbook)

    qa = [
        {"step": "Accounts in accounts.csv (reference)", "rows": len(ref)},
        {"step": "Mock accounts added (accounts_extra.csv)", "rows": len(extra)},
        {"step": "All accounts", "rows": len(df)},
        {"step": "New Logo accounts", "rows": int((df.goal == "New Logo").sum())},
        {"step": "Organic Growth accounts", "rows": int((df.goal == "Organic Growth").sum())},
        *[{"step": f"{t.split('|')[0]} · {t.split('|')[1]} list", "rows": int(((df.role == t.split("|")[0]) & (df.goal == t.split("|")[1])).sum())} for t in LISTS],
        {"step": "Organic Growth accounts with seat data", "rows": int(((df.goal == "Organic Growth") & df.seats_added_6m.notna()).sum())},
        {"step": "Organic Growth accounts with unknown seat data (typical value used)", "rows": int(((df.goal == "Organic Growth") & df.seats_added_6m.isna()).sum())},
    ]
    assert sum(q["rows"] for q in qa[5:5 + len(LISTS)]) == len(df), "every account must be on exactly one list"
    assert df.account_id.is_unique, "duplicate account_id"

    data = {
        "meta": {
            "title": "Account Priority Dashboard",
            "subtitle": "Mock data · all companies are fictional",
            "source": "Mock Priority Score workbook",
            "extract": AS_OF,
            "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "shown_teams": LISTS,
            "roles": ROLE_ORDER,
            "band_order": BAND_ORDER,
            "default_example": "ACC-1059",
        },
        "settings": [{**r, "key": "competitor_max"} if r["key"] == "bpo_max" else r for r in settings],   # shown as Competitor client
        "qa": qa,
        "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, allow_nan=False)
    print(f"Wrote {OUT}: {len(rows)} accounts on {len(LISTS)} lists")
    print(f"Rescaled points + seat growth (before the bonus): Tier 1 {int((df.csv_tier == 'Tier 1').sum())} -> {int((df.workbook_tier == 'Tier 1').sum())}, "
          f"Tier 2 {int((df.csv_tier == 'Tier 2').sum())} -> {int((df.workbook_tier == 'Tier 2').sum())}; accounts changing list {int((df.csv_team != df.assigned_team).sum())}")
    print(f"Act now bonus +{s['hot_bonus']}: Tier 1 {int((df.workbook_tier == 'Tier 1').sum())} -> {int((df.tier == 'Tier 1').sum())}, "
          f"Tier 2 {int((df.workbook_tier == 'Tier 2').sum())} -> {int((df.tier == 'Tier 2').sum())}, "
          f"accounts changing tier {int((df.tier != df.workbook_tier).sum())}")
    for q in qa:
        print(f"  {q['step']:<45} {q['rows']:>4}")


if __name__ == "__main__":
    main()
