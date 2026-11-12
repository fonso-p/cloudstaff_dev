"""Step 4a: department branching analysis (descriptive).
    start -> first new department, time to branch, related departments, branching vs growth,
    and a sensitivity check on the StaffCentral join.
Returns tables, plus the data the charts in step 5 need."""
import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

import config
from mi_pipeline.step3_features import build_branching


def _top_next(s, k=3):
    vc = s.value_counts(normalize=True).head(k)
    return " | ".join(f"{d} {p:.0%}" for d, p in vc.items())


def transitions(branch_known):
    """Starting department -> first new department, plus the same by client industry."""
    start_counts = branch_known["start_dept"].value_counts()
    bk = branch_known[branch_known["start_dept"].isin(start_counts[start_counts >= config.MIN_GROUP_N].index)]
    b1 = bk[bk["branched"] == 1]

    start_dept_summary = (bk.groupby("start_dept")
        .agg(accounts=("branched", "size"),
             pct_launched_multi_dept=("launch_n_depts", lambda s: (s > 1).mean()),
             pct_branched_ever=("branched", "mean"),
             median_days_to_first_branch_if_branched=("first_branch_day", "median"),
             median_depts_ever=("n_depts_ever", "median"))
        .join(b1.groupby("start_dept")["first_branch_dept"].agg(_top_next).rename("top_first_new_depts"))
        .sort_values("accounts", ascending=False).round(3))

    counts = pd.crosstab(b1["start_dept"], b1["first_branch_dept"])
    pct    = pd.crosstab(b1["start_dept"], b1["first_branch_dept"], normalize="index")
    overall_next = b1["first_branch_dept"].value_counts(normalize=True)
    lift = pct / overall_next          # vs the average branching client (1 = no different)
    tr = (counts.stack().rename("accounts_branching_to_dept").to_frame()
          .join(pct.stack().rename("pct_of_branched")).join(lift.stack().rename("lift")).reset_index())
    tr.insert(2, "start_dept_accounts", tr["start_dept"].map(bk["start_dept"].value_counts()))
    tr.insert(3, "start_dept_branched", tr["start_dept"].map(b1["start_dept"].value_counts()))
    tr = tr.rename(columns={"first_branch_dept": "first_new_dept"})
    tr = (tr[tr["accounts_branching_to_dept"] >= config.MIN_TRANSITION_N]
            .sort_values("accounts_branching_to_dept", ascending=False).round(3).reset_index(drop=True))

    top_paths = (bk.loc[bk["branched"] == 1, "path_3"].value_counts().head(25)
                   .rename_axis("path").reset_index(name="accounts"))

    ind = branch_known[branch_known["industry_group"].notna()]
    by_industry = (ind.groupby("industry_group")
        .agg(accounts=("branched", "size"), pct_branched_ever=("branched", "mean"),
             median_depts_ever=("n_depts_ever", "median"))
        .join(ind.groupby("industry_group")["start_dept"].agg(_top_next).rename("top_starting_depts"))
        .join(ind[ind["branched"] == 1].groupby("industry_group")["first_branch_dept"].agg(_top_next)
                 .rename("top_first_new_depts"))
        .loc[lambda d: d["accounts"] >= config.MIN_GROUP_N].sort_values("accounts", ascending=False).round(3))

    rows = counts.sum(axis=1).sort_values(ascending=False).index[:config.TOP_N_DEPTS]
    heat = {"pct": pct.loc[rows, overall_next.index[:config.TOP_N_DEPTS]] * 100,
            "row_n": counts.loc[rows].sum(axis=1)}
    return dict(bk=bk, start_dept_summary=start_dept_summary, transitions=tr, top_paths=top_paths,
                branch_by_industry=by_industry, transition_heat=heat)


def time_to_branch(bk):
    """Kaplan-Meier: share that added a new department by day X while still a client
    (accounts that left without branching are counted up to the day they left)."""
    km_pop = bk[bk["obs_day"] > config.LAUNCH_DAYS].copy()
    km_pop["dur"]   = km_pop["first_branch_day"].where(km_pop["branched"] == 1, km_pop["obs_day"])
    km_pop["event"] = km_pop["branched"]

    def km_row(d, label):
        kmf = KaplanMeierFitter().fit(d["dur"], d["event"])
        row = {"start_dept": label, "accounts": len(d)}
        for t in config.BRANCH_DAYS:
            at_risk = int((d["dur"] >= t).sum())
            row[f"pct_branched_{t}d"] = round(1 - float(kmf.predict(t)), 3) if at_risk >= config.MIN_AT_RISK_BRANCH else np.nan
        med = kmf.median_survival_time_
        row["median_days_to_branch"] = float(med) if np.isfinite(med) else np.nan
        cum = 1 - kmf.survival_function_.iloc[:, 0]
        return row, cum[cum.index <= config.XMAX_BRANCH] * 100

    rows, curves = [], {}
    row, curves["All"] = km_row(km_pop, "All client accounts")
    rows.append(row)
    for i, dept in enumerate(km_pop["start_dept"].value_counts().index):
        row, cum = km_row(km_pop[km_pop["start_dept"] == dept], dept)
        rows.append(row)
        if i < config.KM_SHOW:
            curves[dept] = cum
    table = pd.DataFrame(rows).set_index("start_dept")
    return dict(time_to_branch=table, km_curves=curves, km_n={k: int(table.loc["All client accounts" if k == "All" else k, "accounts"]) for k in curves})


def related_departments(branch_known, dept_entered):
    """Which departments go together in the same client, in any order (lift: 1 = chance)."""
    pres = (dept_entered[dept_entered["Shortcode"].isin(branch_known.index)].assign(v=1)
              .pivot_table(index="Shortcode", columns="role_group", values="v", aggfunc="max", fill_value=0))
    if config.RELATED_MULTI_DEPT_ONLY:
        pres = pres[pres.sum(axis=1) >= 2]
    dept_n = pres.sum().sort_values(ascending=False)
    keep = dept_n[dept_n >= config.MIN_GROUP_N].index
    P = pres[keep].astype(int)
    n_acc, na = len(P), dept_n[keep].to_numpy(dtype=float)
    co   = P.T @ P
    lift = (co / n_acc) / np.outer(na / n_acc, na / n_acc)
    cond = co.div(na, axis=0)
    iu = np.triu_indices(len(keep), k=1)
    pairs = pd.DataFrame({"dept_a": keep[iu[0]], "dept_b": keep[iu[1]], "clients_both": co.to_numpy()[iu],
                          "clients_a": na[iu[0]].astype(int), "clients_b": na[iu[1]].astype(int),
                          "pct_a_with_b": cond.to_numpy()[iu], "pct_b_with_a": cond.to_numpy().T[iu],
                          "lift": lift.to_numpy()[iu]})
    pairs = (pairs[pairs["clients_both"] >= config.MIN_PAIR_N].sort_values("lift", ascending=False)
                  .round(3).reset_index(drop=True))
    top = keep[:config.TOP_N_DEPTS]
    return dict(related_pairs=pairs, lift_matrix=lift.loc[top, top].mask(np.eye(len(top), dtype=bool)),
                lift_n=dept_n[top], related_n_clients=n_acc)


def branching_vs_growth(branch_known, clients, timeline, summary, spells):
    """Landmark comparison: clients still with us on LANDMARK_DAY, split by whether they had added a new
    department by then; outcomes over the next FOLLOW_DAYS, within headcount bands. Association, not cause."""
    L, H = config.LANDMARK_DAY, config.LANDMARK_DAY + config.FOLLOW_DAYS
    tl = timeline[["Shortcode", "date", "active_staff"]].merge(clients[["Shortcode", "start_date"]], on="Shortcode")
    tl = tl[tl["date"] <= tl["start_date"] + pd.Timedelta(days=L)]
    hc_l = tl.sort_values(["Shortcode", "date"]).groupby("Shortcode")["active_staff"].last()
    g = (branch_known.join(hc_l.rename("hc_landmark"))
                     .join(summary.set_index("Shortcode")[["days_observed", "days_till_10_headcount"]]))
    g = g[(g["days_observed"] >= L) & (g["hc_landmark"] > 0)].copy()
    g["branch_status"] = np.where(g["first_branch_day"] <= L, f"New dept by day {L}", f"No new dept by day {L}")
    g["hc_band"] = pd.cut(g["hc_landmark"], bins=[0, 2, 4, 9, np.inf], labels=["1-2 seats", "3-4 seats", "5-9 seats", "10+ seats"])
    d10 = g["days_till_10_headcount"].astype(float)
    elig_a = (g["days_observed"] >= H + config.MILESTONE_HOLD_DAYS) & (g["hc_landmark"] < 10) & ~(d10 <= L)
    g["reached_10_next_year"] = (d10 <= H).astype(float).where(elig_a)
    sp = spells[spells["is_churn"]].merge(clients[["Shortcode", "start_date"]], on="Shortcode")
    sp["day"] = (sp["zero_start"] - sp["start_date"]).dt.days
    churned = set(sp.loc[(sp["day"] > L) & (sp["day"] <= H), "Shortcode"])
    g["churned_next_year"] = (pd.Series(g.index.isin(churned), index=g.index).astype(float)
                                .where(g["days_observed"] >= H + config.CHURN_GRACE_DAYS))
    return (g.groupby(["hc_band", "branch_status"], observed=True)
              .agg(accounts=("start_dept", "size"),
                   n_eligible_10=("reached_10_next_year", "count"),
                   pct_reached_10_next_year=("reached_10_next_year", "mean"),
                   n_eligible_churn=("churned_next_year", "count"),
                   pct_churned_next_year=("churned_next_year", "mean"))
              .round(3))


def sensitivity(src, clients, branch, transitions_table):
    """Rebuild start -> next using only engagements whose department is certain (Engagement ID matches
    StaffCentral). Similar shares = the CSID join isn't distorting the pattern."""
    certain = src.assign(role_group=src["role_group"].where(src["dept_certain"] == 1))
    branch_c, _ = build_branching(certain, clients)
    bc = branch_c[branch_c["start_dept"].notna() & (branch_c["branched"] == 1)]
    cnt_c = pd.crosstab(bc["start_dept"], bc["first_branch_dept"])
    pct_c = pd.crosstab(bc["start_dept"], bc["first_branch_dept"], normalize="index")
    look = lambda tbl, s, n: tbl.at[s, n] if (s in tbl.index and n in tbl.columns) else np.nan
    tt = transitions_table.rename(columns={"first_new_dept": "first_branch_dept"})
    sens = tt.loc[tt["accounts_branching_to_dept"] >= config.SENS_MIN_N,
                  ["start_dept", "first_branch_dept", "start_dept_accounts", "start_dept_branched",
                   "accounts_branching_to_dept", "pct_of_branched"]].copy()
    sens["certain_only_accounts_branching_to_dept"] = [look(cnt_c, s, n) for s, n in zip(sens["start_dept"], sens["first_branch_dept"])]
    sens["certain_only_pct_of_branched"] = [look(pct_c, s, n) for s, n in zip(sens["start_dept"], sens["first_branch_dept"])]
    sens = sens.rename(columns={"first_branch_dept": "first_new_dept"}).round(3).reset_index(drop=True)
    both = sens.dropna(subset=["certain_only_pct_of_branched"])
    corr = both["pct_of_branched"].corr(both["certain_only_pct_of_branched"]) if len(both) > 2 else np.nan
    stats = {"known_start_main": int(branch["start_dept"].notna().sum()),
             "known_start_certain": int(branch_c["start_dept"].notna().sum()),
             "branching_main": int(branch["branched"].sum()), "branching_certain": len(bc),
             "transitions_compared": len(both), "correlation": corr}
    return sens, stats


def run(feat, log=print):
    branch = feat["branch"]
    branch_known = branch[branch["start_dept"].notna()]
    out = transitions(branch_known)
    out.update(time_to_branch(out["bk"]))
    out.update(related_departments(branch_known, feat["dept_entered"]))
    out["growth_by_branch"] = branching_vs_growth(branch_known, feat["clients"], feat["timeline"], feat["summary"], feat["spells"])
    out["sensitivity"], out["sensitivity_stats"] = sensitivity(feat["src"], feat["clients"], branch, out["transitions"])
    log(f"[4 branching] accounts with a known start {len(branch_known)} | have branched {branch_known['branched'].mean():.1%} | "
        f"sensitivity correlation {out['sensitivity_stats']['correlation']:.2f}")
    return out
