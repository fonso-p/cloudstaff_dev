"""Step 3: data engineering.
    timeline   headcount per account per change date (+ exit-reason counts)
    summary    one row per account: lifecycle, churn, milestones, attrition, exit reasons, industry, launch size
    clients    client accounts only (internal / never-client accounts removed)
    branch     one row per client: starting department and the order/timing of new departments
    accounts   client attributes for the propensity models
    snapshots  what each client looked like at a given age (for the existing-client model)
"""
import numpy as np
import pandas as pd

import config
from mi_pipeline import mappings
from mi_pipeline.step1_format import clean_text

# ================================================================ timeline
def build_timeline(engagement, today, log=print):
    """Returns src (hires that have started) and timeline (seats per account on every date that changes them)."""
    eng = engagement.copy()

    # Who is still active? (blank, today/future-dated, or the extract's fill date)
    fill_ts = pd.Timestamp(config.ACTIVE_FILL_DATE) if config.ACTIVE_FILL_DATE else today
    dd = eng["disengagement_date"]
    is_active = dd.isna() | (dd >= today) | (dd == fill_ts)
    if config.ACTIVE_STATUSES:
        is_active |= eng["Employment Status"].isin(config.ACTIVE_STATUSES)
    eng["is_active"] = is_active
    src = eng[~(eng["engagement_date"] > today)].copy()          # hires that haven't started are left out

    top_dates = dd.value_counts().head(1)
    if len(top_dates) and top_dates.iloc[0] > 0.2 * len(dd) and not (top_dates.index[0] >= today or top_dates.index[0] == fill_ts):
        log(f"[3 features] WARNING: {top_dates.index[0].date()} is on {top_dates.iloc[0]} rows but treated as a real exit "
            "date. If it is the extract's 'still active' fill date, set config.ACTIVE_FILL_DATE.")

    # +1 per start, -1 per exit (still-active hires skipped)
    starts = src[["Shortcode", "engagement_date"]].rename(columns={"engagement_date": "date"}).assign(delta=1)
    ends = (src.loc[~src["is_active"], ["Shortcode", "disengagement_date"]]
               .rename(columns={"disengagement_date": "date"}).assign(delta=-1))
    timeline = (pd.concat([starts, ends], ignore_index=True)
                  .groupby(["Shortcode", "date"], as_index=False)["delta"].sum()
                  .sort_values(["Shortcode", "date"]).reset_index(drop=True))
    timeline["active_staff"] = timeline.groupby("Shortcode")["delta"].cumsum()
    timeline = timeline.drop(columns="delta")
    log(f"[3 features] hires {len(src)} | exits {len(ends)} | active {int(is_active.sum())} | "
        f"timeline rows {len(timeline)} for {timeline['Shortcode'].nunique()} accounts")
    return src, timeline


# ================================================================ summary
def held_run_starts(timeline, n, hold, today):
    """Start day of every run at n+ seats that lasted at least `hold` days (a run still going counts once it has).
    Brief spikes, e.g. a replacement overlapping a leaver, don't count. Returns Shortcode, start."""
    sc = timeline["Shortcode"]
    above = timeline["active_staff"] >= n
    prev_above = above.groupby(sc).shift(fill_value=False).astype(bool)
    run_start = above & ~prev_above
    run_end = timeline["date"].where(~above & prev_above).groupby(sc).bfill()
    runs = pd.DataFrame({"Shortcode": sc[run_start], "start": timeline.loc[run_start, "date"],
                         "end": run_end[run_start].fillna(today)})
    return runs.loc[(runs["end"] - runs["start"]).dt.days >= hold, ["Shortcode", "start"]].reset_index(drop=True)

def _first_held_date(timeline, n, hold, today):
    """First day of the first run at n+ seats that lasted `hold` days (a run still going counts once it has)."""
    return held_run_starts(timeline, n, hold, today).groupby("Shortcode")["start"].min()

def build_summary(timeline, src, mystaff, today, log=print):
    """One row per account: dates, whether still a client, current seats, held seat milestones, launch size, and
    industry / region from MyStaff. Returns summary and spells (zero-headcount gaps)."""
    summary = (timeline.groupby("Shortcode")
                       .agg(start_date=("date", "first"), last_date=("date", "last"), current_headcount=("active_staff", "last"))
                       .reset_index())
    summary["days_observed"] = (today - summary["start_date"]).dt.days

    # --- Zero-headcount spells: churn (> grace days) vs backfill gap. A short gap still running = still a client ---
    tl = timeline[["Shortcode", "date", "active_staff"]].copy()
    prev = tl.groupby("Shortcode")["active_staff"].shift()
    pos = tl["active_staff"].gt(0).astype(int)
    had_staff_before = pos.groupby(tl["Shortcode"]).cumsum() - pos
    tl["churn_point"]        = (tl["active_staff"].le(0) & prev.gt(0)).astype(int)
    tl["reactivation_point"] = (tl["active_staff"].gt(0) & prev.le(0) & had_staff_before.gt(0)).astype(int)
    tl["next_return"] = tl["date"].where(tl["reactivation_point"] == 1).groupby(tl["Shortcode"]).bfill()
    spells = tl.loc[tl["churn_point"] == 1, ["Shortcode", "date", "next_return"]].rename(columns={"date": "zero_start"})
    spells["ongoing"]  = spells["next_return"].isna()
    spells["gap_days"] = (spells["next_return"].fillna(today) - spells["zero_start"]).dt.days
    spells["is_churn"] = spells["gap_days"] > config.CHURN_GRACE_DAYS
    churn_pending = summary["Shortcode"].isin(spells.loc[spells["ongoing"] & ~spells["is_churn"], "Shortcode"])
    summary["engagement_active"] = (summary["current_headcount"].gt(0) | churn_pending).astype(int)
    summary["end_date"] = summary["last_date"].where(summary["engagement_active"] == 0, pd.NaT)

    # --- Held seat milestones ---
    for n in config.HEADCOUNT_MILESTONES:
        held = _first_held_date(timeline, n, config.MILESTONE_HOLD_DAYS, today)
        summary[f"days_till_{n}_headcount"] = (
            (pd.to_datetime(summary["Shortcode"].map(held.to_dict())) - summary["start_date"]).dt.days.astype("Int64"))
    summary["total_hires"] = summary["Shortcode"].map(src.groupby("Shortcode").size())

    # --- Industry / region from MyStaff ---
    ms = mystaff[["Shortcode", "Industry Roll Up", "Industry Hubspot", "industry_group", "industry_sector",
                  "industry_source", "region", "country"]]
    assert summary["Shortcode"].dtype == ms["Shortcode"].dtype, "Shortcode types differ for the MyStaff join"
    assert ms["Shortcode"].is_unique, "duplicate Shortcodes in MyStaff"
    summary = summary.drop(columns="last_date").merge(ms, on="Shortcode", how="left")

    # --- Launch size: seats on day LAUNCH_DAYS (staggered onboarding in the first month = one launch) ---
    L = config.LAUNCH_DAYS
    e = src[["Shortcode", "engagement_date", "disengagement_date", "is_active"]].merge(
        summary[["Shortcode", "start_date"]], on="Shortcode", how="inner")
    e["hire_day"] = (e["engagement_date"] - e["start_date"]).dt.days
    e["exit_day"] = (e["disengagement_date"] - e["start_date"]).dt.days.where(~e["is_active"])
    e = e[e["hire_day"] <= L]
    seats_l = (~(e["exit_day"] <= L)).groupby(e["Shortcode"]).sum()
    summary["launch_size"] = (summary["Shortcode"].map(seats_l).astype("float")
                              .where(summary["days_observed"] >= L))

    log(f"[3 features] summary: {len(summary)} accounts | active {int(summary['engagement_active'].sum())} | "
        f"churn gaps {int(spells['is_churn'].sum())}, backfill gaps {int((~spells['is_churn'] & ~spells['ongoing']).sum())} | "
        f"reached 5 seats (held): {int(summary['days_till_5_headcount'].notna().sum())}")
    return summary, spells

def client_accounts(summary, src, today, log=print):
    """Removes never-client accounts and internal teams (mostly 'Hub' staff). Returns clients, excluded list."""
    hub_share = (src["Category"].astype("string").str.strip().eq("Hub").fillna(False)
                    .groupby(src["Shortcode"]).mean())
    excluded = set(config.NON_CLIENT_SHORTCODES) | set(hub_share[hub_share >= config.HUB_SHARE_EXCLUDE].index)
    is_excl = summary["Shortcode"].isin(excluded)
    excluded_accounts = (summary.loc[is_excl, ["Shortcode", "total_hires"]]
                                .assign(hub_share=lambda d: d["Shortcode"].map(hub_share).round(2))
                                .sort_values("total_hires", ascending=False))
    clients = summary.loc[~is_excl, ["Shortcode", "Industry Roll Up", "industry_group", "start_date",
                                     "end_date", "engagement_active", "days_observed"]].copy()
    clients["obs_day"] = (clients["end_date"].fillna(today) - clients["start_date"]).dt.days
    log(f"[3 features] client accounts: {len(clients)} ({int(is_excl.sum())} non-client accounts excluded)")
    return clients, excluded_accounts

def build_branching(rows, clients, arrow=" -> "):
    """One row per client account: starting department and the order/timing of new departments.
    rows: one row per hire with Shortcode, engagement_date, role_group (blank role_group is ignored).
    Also returns `entered`: one row per account x department with the day it was entered."""
    r = (rows.loc[rows["role_group"].notna(), ["Shortcode", "engagement_date", "role_group"]]
             .merge(clients[["Shortcode", "start_date"]], on="Shortcode", how="inner"))
    r["hire_day"]   = (r["engagement_date"] - r["start_date"]).dt.days
    r["role_group"] = r["role_group"].astype(str)

    # Starting department: most hires in the launch window; ties -> hired first, then name
    lg = (r[r["hire_day"] <= config.LAUNCH_DAYS].groupby(["Shortcode", "role_group"])
            .agg(n=("hire_day", "size"), first=("hire_day", "min")).reset_index())
    start = (lg.sort_values(["Shortcode", "n", "first", "role_group"], ascending=[True, False, True, True])
               .drop_duplicates("Shortcode").set_index("Shortcode")["role_group"])
    launch_n = lg.groupby("Shortcode").size()
    launch_pairs = set(zip(lg["Shortcode"], lg["role_group"]))

    # Day each department is entered = its BRANCH_MIN_HIRES-th hire
    r = r.sort_values(["Shortcode", "role_group", "hire_day"])
    r["nth"] = r.groupby(["Shortcode", "role_group"]).cumcount() + 1
    dept_hires = r.groupby(["Shortcode", "role_group"]).size().rename("dept_hires")
    entered = (r.loc[r["nth"] == config.BRANCH_MIN_HIRES, ["Shortcode", "role_group", "hire_day"]]
                .rename(columns={"hire_day": "entered_day"}).join(dept_hires, on=["Shortcode", "role_group"]))

    # Branches: departments not in the launch team, in entry order (same-day ties -> the bigger department)
    in_launch = np.array([p in launch_pairs for p in zip(entered["Shortcode"], entered["role_group"])], dtype=bool)
    br = entered[~in_launch].sort_values(["Shortcode", "entered_day", "dept_hires", "role_group"],
                                         ascending=[True, True, False, True])
    br["order"] = br.groupby("Shortcode").cumcount() + 1
    first, second = br[br["order"] == 1].set_index("Shortcode"), br[br["order"] == 2].set_index("Shortcode")

    out = clients.set_index("Shortcode")[["Industry Roll Up", "industry_group", "obs_day", "engagement_active"]].copy()
    out["start_dept"]         = start
    out["launch_n_depts"]     = launch_n
    out["n_depts_ever"]       = entered.groupby("Shortcode").size()
    out["n_branches"]         = br.groupby("Shortcode").size()
    out["first_branch_dept"]  = first["role_group"]
    out["first_branch_day"]   = first["entered_day"]
    out["second_branch_dept"] = second["role_group"]
    out["second_branch_day"]  = second["entered_day"]
    cnt = ["launch_n_depts", "n_depts_ever", "n_branches"]
    out[cnt] = out[cnt].fillna(0).astype(int)
    no_start = out["start_dept"].isna()        # without a starting department "new" can't be defined
    out.loc[no_start, ["n_branches", "first_branch_dept", "first_branch_day", "second_branch_dept", "second_branch_day"]] = np.nan
    out["branched"] = out["first_branch_dept"].notna().astype(int)
    out["path_3"] = (out[["start_dept", "first_branch_dept", "second_branch_dept"]]
                       .apply(lambda x: arrow.join(x.dropna()), axis=1).where(~no_start))
    return out, entered


# ================================================================ propensity inputs
def industry_fit_map(industry_groups):
    """Industry level used by the models: the group, or its sector when the group has fewer than
    INDUSTRY_SECTOR_FALLBACK_N client accounts. Returns {group: model level}, plus 'Unknown'."""
    n = pd.Series(industry_groups).value_counts()
    out = {g: (g if n.get(g, 0) >= config.INDUSTRY_SECTOR_FALLBACK_N else mappings.INDUSTRY_SECTOR[g])
           for g in mappings.INDUSTRY_SECTOR}
    out["Unknown"] = "Unknown"
    return out

def propensity_accounts(branch, summary, mystaff, log=print):
    """Client attributes known at signup + outcomes, one row per client (MyStaff 'Internal' accounts dropped)."""
    ms = mystaff.drop_duplicates("Shortcode").set_index("Shortcode")
    attrs = pd.DataFrame({
        "country":  ms["country"],
        "region":   ms["region"],
        "internal": clean_text(ms["Internal (Yes / No)"]).str.lower().eq("yes").fillna(False).astype(bool)})
    acct = (branch[["industry_group", "start_dept", "launch_n_depts", "first_branch_day", "engagement_active"]]
            .join(summary.set_index("Shortcode")[["start_date", "days_observed", "launch_size",
                                                  *[f"days_till_{n}_headcount" for n in config.HEADCOUNT_MILESTONES],
                                                  "current_headcount"]])
            .join(attrs))
    n_internal = int(acct["internal"].fillna(False).sum())
    acct = acct[~acct["internal"].fillna(False).astype(bool)].copy()

    top_starts = list(acct["start_dept"].value_counts().index[:config.PS_TOP_START_DEPTS])
    acct["industry"]       = acct["industry_group"].astype("string").fillna("Unknown").astype(str)
    fit_map                = industry_fit_map(acct.loc[acct["industry"] != "Unknown", "industry"])
    acct["industry_fit"]   = acct["industry"].map(fit_map)
    acct["country"]        = acct["country"].fillna("Unknown").astype(str)
    acct["start_dept_grp"] = np.where(acct["start_dept"].isna(), "Unknown",
                                      np.where(acct["start_dept"].isin(top_starts), acct["start_dept"], "Other"))
    acct["launch_bucket"]  = pd.cut(acct["launch_size"], bins=[0, 2, 4, np.inf], labels=["1-2", "3-4", "5+"]).astype("string")
    pooled = sorted(g for g, lvl in fit_map.items() if g != lvl)
    log(f"[3 features] propensity accounts: {len(acct)} ({n_internal} flagged Internal in MyStaff dropped) | "
        f"modelled at sector level (< {config.INDUSTRY_SECTOR_FALLBACK_N} accounts): {', '.join(pooled) or 'none'}")
    return acct, top_starts, fit_map

def seat_measures(shortcodes, timeline, src, today):
    """Seats today, gross seats added and net seat change over the last 180 days, from the engagement list.
    seats_added_6m_gross lines up with the dashboard's seats_added_6m (gross adds); the net change is the alternative."""
    codes = pd.Index(pd.unique(pd.Series(list(shortcodes), dtype=timeline["Shortcode"].dtype)), name="Shortcode")
    start = today - pd.Timedelta(days=180)
    tl = timeline[timeline["Shortcode"].isin(codes)].sort_values(["Shortcode", "date"])
    seats_on = lambda day: tl[tl["date"] <= day].groupby("Shortcode")["active_staff"].last().reindex(codes).fillna(0)
    hires = src[src["Shortcode"].isin(codes) & (src["engagement_date"] > start) & (src["engagement_date"] <= today)]
    out = pd.DataFrame({"seats_current": seats_on(today).clip(lower=0),
                        "seats_added_6m_gross": hires.groupby("Shortcode").size().reindex(codes).fillna(0),
                        "seats_change_6m_net": seats_on(today) - seats_on(start)})
    return out.astype(int)

def snapshot_features(snaps, timeline, src, dept_entered, accounts, cat_cols):
    """snaps: Shortcode, age (days since first hire), snap_date. Adds features as they were on snap_date:
    seats, seats 180 days earlier, hires in the last 180 days, departments so far, plus static attributes."""
    s = snaps.copy()
    s["snap_date"] = pd.to_datetime(s["snap_date"]).astype("datetime64[ns]")
    s["Shortcode"] = s["Shortcode"].astype(timeline["Shortcode"].dtype)
    s = s.sort_values("snap_date")
    s["date_180"] = s["snap_date"] - pd.Timedelta(days=180)
    tl = timeline[["Shortcode", "date", "active_staff"]].astype({"date": "datetime64[ns]"}).sort_values("date")
    hires = (src.loc[src["Shortcode"].isin(accounts.index), ["Shortcode", "engagement_date"]]
                .astype({"engagement_date": "datetime64[ns]", "Shortcode": timeline["Shortcode"].dtype})
                .sort_values("engagement_date"))
    hires["cum_hires"] = hires.groupby("Shortcode").cumcount() + 1

    def asof(left_on, right, right_on, col):
        r = pd.merge_asof(s[["Shortcode", left_on]].reset_index().sort_values(left_on),
                          right.rename(columns={right_on: left_on})[["Shortcode", left_on, col]],
                          on=left_on, by="Shortcode", direction="backward")
        return r.set_index("index")[col].reindex(s.index).fillna(0)

    s["seats"] = asof("snap_date", tl, "date", "active_staff")
    seats_180 = asof("date_180", tl, "date", "active_staff")
    s["hires_180d"] = (asof("snap_date", hires, "engagement_date", "cum_hires")
                       - asof("date_180", hires, "engagement_date", "cum_hires"))
    s["seat_change_180d"] = s["seats"] - seats_180
    s["log_seats"] = np.log1p(s["seats"].clip(lower=0))
    s["age_years"] = s["age"] / 365
    held = s[["Shortcode", "age"]].reset_index().merge(dept_entered[["Shortcode", "entered_day"]], on="Shortcode")
    s["n_depts"] = held[held["entered_day"] <= held["age"]].groupby("index").size().reindex(s.index).fillna(0)
    return s.join(accounts[cat_cols], on="Shortcode")


def run(merged, today, log=print):
    engagement, mystaff = merged["engagement"], merged["mystaff"]
    src, timeline = build_timeline(engagement, today, log)
    summary, spells = build_summary(timeline, src, mystaff, today, log)
    clients, excluded_accounts = client_accounts(summary, src, today, log)
    branch, dept_entered = build_branching(src, clients)
    accounts, top_starts, fit_map = propensity_accounts(branch, summary, mystaff, log)
    return dict(src=src, timeline=timeline, summary=summary, spells=spells, clients=clients,
                excluded_accounts=excluded_accounts, branch=branch, dept_entered=dept_entered,
                accounts=accounts, top_starts=top_starts, industry_fit_map=fit_map, mystaff=mystaff)
