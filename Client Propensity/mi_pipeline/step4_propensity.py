"""Step 4b: propensity scorecards.
    New clients:      chance of reaching 5 seats within a year and the PS_MILESTONES (10 seats in 2 years), and of
                      adding a department in year 1, from traits known at signup
                      -> new_client_scorecard, prospect_profiles, NewClientScorer
    Existing clients: chance that a client under N seats reaches and holds N+ within a year, for each N in
                      ORG_SEAT_MILESTONES (5, 10, 20; clients already at the largest N are out of scope); of adding a
                      department never had before, plus likely next department (share and lift); and, for the workbook
                      only, of having more seats in 12 months (net, any size) -> organic_client_list
Every score has a band (thirds of the cross-validated historical scores) and a "why".
Simple logistic models."""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, StratifiedGroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import config
from mi_pipeline import mappings
from mi_pipeline.step3_features import held_run_starts, snapshot_features

PROFILE = ["industry_fit", "country", "start_dept_grp", "launch_bucket"]   # model inputs (brand deliberately not used)
PROFILE_DISPLAY = ["industry", "country", "start_dept_grp", "launch_bucket"]  # what a profile row shows (18 industry groups)
ORG_NUM = ["age_years", "log_seats", "seat_change_180d", "hires_180d", "n_depts"]
ORG_CAT = ["industry_fit", "country", "start_dept_grp"]


# ================================================================ shared helpers
def _model(num, cat):
    steps = []
    if num:
        steps.append(("num", StandardScaler(), num))
    if cat:
        steps.append(("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=config.PS_MIN_LEVEL_N), cat))
    return Pipeline([("pre", ColumnTransformer(steps)), ("lr", LogisticRegression(C=config.PS_C, max_iter=5000))])

def band(p, cuts):
    return pd.Categorical(np.select([p >= cuts[1], p >= cuts[0]], ["High", "Medium"], "Low"),
                          categories=config.PS_BANDS, ordered=True)

def band_check(p, y, cuts):
    """What each band delivered: rows, actual rate and average score per band."""
    return (pd.DataFrame({"band": band(p, cuts), "y": np.asarray(y), "score": p})
              .groupby("band", observed=False)
              .agg(rows=("y", "size"), actual_rate=("y", "mean"), avg_score=("score", "mean")).round(3))

def fit(df, num, cat, y_col, name, groups=None, log=print, return_cv=False):
    """Fit on all rows; judge with 5-fold cross-validation (grouped by client when groups is given).
    return_cv=True also returns the cross-validated scores (to band a subset, e.g. one-department clients)."""
    X, y = df[num + cat], df[y_col].astype(int)
    cv = (StratifiedKFold(5, shuffle=True, random_state=config.PS_RANDOM_STATE) if groups is None
          else StratifiedGroupKFold(5, shuffle=True, random_state=config.PS_RANDOM_STATE))
    p_cv = cross_val_predict(_model(num, cat), X, y, cv=cv, groups=groups, method="predict_proba")[:, 1]
    model = _model(num, cat).fit(X, y)
    cuts = np.quantile(p_cv, [1 / 3, 2 / 3])
    check = band_check(p_cv, y.to_numpy(), cuts)
    auc = roc_auc_score(y, p_cv)
    log(f"[4 propensity] {name}: {len(df)} rows | base rate {y.mean():.1%} | cross-validated AUC {auc:.2f} | "
        f"band cut-offs {cuts[0]:.0%} / {cuts[1]:.0%}")
    return (model, cuts, check, auc, p_cv) if return_cv else (model, cuts, check, auc)

def factors(model, df, num, cat):
    """How each trait moves the average score (percentage points), holding everything else as it was."""
    X = df[num + cat]
    base = model.predict_proba(X)[:, 1].mean()
    rows = []
    for f in cat:
        for lvl, n in X[f].value_counts().items():
            if n >= config.PS_MIN_LEVEL_N:
                Xs = X.copy(); Xs[f] = lvl
                rows.append({"factor": f, "level": lvl, "rows": int(n), "avg_score": model.predict_proba(Xs)[:, 1].mean()})
    for f in num:
        for q, lvl in zip((0.1, 0.5, 0.9), ("low (10th pct)", "typical (median)", "high (90th pct)")):
            v = X[f].quantile(q)
            Xs = X.copy(); Xs[f] = v
            rows.append({"factor": f, "level": f"{lvl} = {v:.2f}", "rows": np.nan, "avg_score": model.predict_proba(Xs)[:, 1].mean()})
    t = pd.DataFrame(rows)
    t["vs_average_pts"] = ((t["avg_score"] - base) * 100).round(1)
    t["avg_score"] = t["avg_score"].round(3)
    return t

def reasons(model, X, ref, labeller, k=2, min_logit=0.05, context=None, fallback=None):
    """Top-k traits pushing each row's score UP vs a typical client. labeller returns text or None (skip).
    context: optional {trait: phrase(value, typical) -> text} for traits the reader already sees elsewhere (e.g. seats and
    time with us, shown on the dashboard row). They are not listed one by one: the top-k OTHER traits are listed, and when
    a context trait is the strongest driver (or the only one) the text leads with a summary, e.g.
    "Mostly its size and recent growth; also industry: Technology". A context phrase of None keeps that trait out of the
    text; fallback = {trait: text} is used when such a silent trait is the strongest driver and nothing else is shown."""
    logit = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    lo = logit(model.predict_proba(X)[:, 1])
    contrib = {}
    for f in X.columns:
        Xr = X.copy(); Xr[f] = ref[f]
        contrib[f] = lo - logit(model.predict_proba(Xr)[:, 1])
    C = pd.DataFrame(contrib, index=X.index)
    context, fallback = context or {}, fallback or {}
    out = []
    for i, row in C.iterrows():
        ranked = [f for f in row[row > min_logit].sort_values(ascending=False).index if labeller(f, X.at[i, f])]
        # a trait counts when its label (or, for context traits, its phrase) isn't None
        up = [f for f in ranked if f not in context or context[f](X.at[i, f], ref[f])]
        if not up:
            out.append(next((fallback[f] for f in ranked[:1] if f in fallback), ""))
            continue
        other = [labeller(f, X.at[i, f]) for f in up if f not in context][:k]
        ctx = [f for f in up if f in context]
        if ctx and (up[0] in context or not other):
            phrases = list(dict.fromkeys(context[f](X.at[i, f], ref[f]) for f in ctx))[:2]
            lead = "Mostly " + " and ".join(phrases)
            out.append(lead + (f"; also {', '.join(other)}" if other else ""))
        else:
            out.append("; ".join(other))
    return pd.Series(out, index=X.index)

def top_next(dist, k=2):
    d = dist.sort_values(ascending=False).head(k)
    return ", ".join(f"{n} {p:.0%}" for n, p in d.items()) if len(d) else ""


# ================================================================ new clients
def outlook(gb, bb):
    if gb == "High" and bb == "High":
        return "Grow + expand"
    if gb == "High":
        return "Likely to grow"
    if bb == "High":
        return "Likely to expand"
    if gb == "Low" and bb == "Low":
        return "Low propensity"
    return "Moderate"

def fmt_share_lift(share, base, k=2):
    """'Dept A 10% (1.1x), Dept B 9% (0.9x)': top-k by share; lift = share / the department's usual share."""
    d = share.sort_values(ascending=False).head(k)
    return ", ".join(f"{n} {p:.0%} ({p / base.get(n, np.nan):.1f}x)" if base.get(n, 0) > 0 else f"{n} {p:.0%}"
                     for n, p in d.items())

def fmt_by_lift(share, base, k=2):
    """'Dept C 2.1x (6%), ...': departments most unusually likely (share >= PS_LIFT_MIN_SHARE), top-k by lift."""
    b = pd.Series({n: base.get(n, np.nan) for n in share.index}, dtype=float)
    lift = (share / b).replace([np.inf, -np.inf], np.nan)[share >= config.PS_LIFT_MIN_SHARE].dropna()
    d = lift.sort_values(ascending=False).head(k)
    return ", ".join(f"{n} {l:.1f}x ({share[n]:.0%})" for n, l in d.items())

def milestone_col(n, d):
    return f"p_reach_{n}_{d}d"

def why_col(n, d):
    return f"why_reach_{n}_{d}d"

def _profile_label(f, v):
    """Reason text for a new-client profile trait (None = not worth showing)."""
    if v in ("Other", "Unknown"):
        return None
    return {"industry_fit": f"industry: {v}", "country": f"country: {v}", "start_dept_grp": f"starts in {v}",
            "launch_bucket": f"launch {v} staff"}.get(f, f"{f}: {v}")


class NewClientScorer:
    """Scores client profiles (PROFILE_DISPLAY columns): growth to 5 in a year, the extra seat milestones,
    and year-1 branching."""

    def __init__(self, growth, branch, milestones, next_by_start, next_overall, n_by_start, top_starts, fit_map, refs):
        self.fit_map = fit_map            # industry group -> model level (group, or sector for small groups)
        self.refs = refs                  # typical profile per model (most common value of each trait), for the "why"
        self.growth_model, self.growth_cuts = growth
        self.branch_model, self.branch_cuts = branch
        self.milestones = milestones      # {(seats, days): (model, cuts)}
        self.next_by_start, self.next_overall, self.n_by_start = next_by_start, next_overall, n_by_start
        self.top_starts = set(top_starts)

    def _next_dist(self, start_dept):
        d = self.next_by_start[self.next_by_start["start_dept"] == start_dept]
        if d["p"].size and self.n_by_start.get(start_dept, 0) >= 10:   # enough history for this start
            return d.set_index("first_branch_dept")["p"], False
        return self.next_overall, True

    def likely_first_new(self, start_dept, k=2):
        dist, overall = self._next_dist(start_dept)
        if overall:
            return ", ".join(f"{n} {p:.0%}" for n, p in dist.sort_values(ascending=False).head(k).items()) + " (overall)"
        return fmt_share_lift(dist, self.next_overall, k)

    def likely_first_new_by_lift(self, start_dept, k=2):
        dist, overall = self._next_dist(start_dept)
        return "" if overall else fmt_by_lift(dist, self.next_overall, k)

    def milestone_columns(self):
        return [c for (n, d) in self.milestones
                for c in (milestone_col(n, d), milestone_col(n, d).replace("p_", "band_", 1), why_col(n, d))]

    def score_profiles(self, prof):
        """prof: PROFILE_DISPLAY columns (industry = one of the 18 groups or 'Unknown')."""
        out = prof.copy()
        out["industry_fit"] = out["industry"].map(self.fit_map).fillna("Unknown")
        X = out[PROFILE]
        can_grow = out["launch_bucket"].ne("5+").to_numpy()
        out["p_growth"] = np.where(can_grow, self.growth_model.predict_proba(X)[:, 1], np.nan)
        out["growth_band"] = band(out["p_growth"].fillna(-1).to_numpy(), self.growth_cuts)
        out.loc[~can_grow, "growth_band"] = np.nan          # already at 5+: growth to 5 doesn't apply
        out["growth_why"] = np.where(can_grow, reasons(self.growth_model, X, self.refs["growth"], _profile_label), "")
        ms_txt = [""] * len(out)
        for (n, d), (m, cuts) in self.milestones.items():
            col = milestone_col(n, d)
            bcol = col.replace("p_", "band_", 1)
            out[col] = m.predict_proba(X)[:, 1]
            out[bcol] = band(out[col].to_numpy(), cuts)
            out[why_col(n, d)] = reasons(m, X, self.refs[(n, d)], _profile_label)
            ms_txt = [t + f" | {n} seats in {d // 365}y: {b} ({p:.0%})" for t, b, p in zip(ms_txt, out[bcol].astype(str), out[col])]
        out["p_branch"] = self.branch_model.predict_proba(X)[:, 1]
        out["branch_band"] = band(out["p_branch"].to_numpy(), self.branch_cuts)
        out["branch_why"] = reasons(self.branch_model, X, self.refs["branch"], _profile_label)
        out["likely_first_new_dept"] = [self.likely_first_new(s) for s in out["start_dept_grp"]]
        out["likely_first_new_dept_by_lift"] = [self.likely_first_new_by_lift(s) for s in out["start_dept_grp"]]
        out["outlook"] = [outlook(g, b) for g, b in zip(out["growth_band"].astype(str), out["branch_band"].astype(str))]
        n5 = config.PS_GROWTH_SEATS
        grow_txt = [f"{n5} seats in 1y: {b} ({p:.0%})" if pd.notna(p) else f"{n5} seats: n/a (launched at 5+)"
                    for b, p in zip(out["growth_band"].astype(str), out["p_growth"])]
        out["line_item"] = [
            f"{r.industry} | {r.country} | starts in {r.start_dept_grp} | launch {r.launch_bucket} staff"
            f"  ->  {g}{m} | New dept in 1y: {r.branch_band} ({r.p_branch:.0%}) | likely next: {r.likely_first_new_dept}"
            for r, g, m in zip(out.itertuples(), grow_txt, ms_txt)]
        return out

    def score(self, industry, country=None, start_dept="Unknown", launch_size=1, region=None):
        """Score a brand-new client. industry = one of the 18 dashboard groups; give country, or the dashboard's
        region code, e.g. scorer.score("Real Estate", region="AU-NSW", start_dept="Real Estate")."""
        if region is not None:
            country = mappings.region_to_country(region)
        country = country or "Unknown"
        bucket = "1-2" if launch_size <= 2 else ("3-4" if launch_size <= 4 else "5+")
        grp = start_dept if start_dept in self.top_starts or start_dept == "Unknown" else "Other"
        prof = pd.DataFrame([{"industry": industry, "country": country, "start_dept_grp": grp, "launch_bucket": bucket}])
        return self.score_profiles(prof)[["line_item", "outlook", "p_growth", "growth_band", "growth_why", *self.milestone_columns(),
                                          "p_branch", "branch_band", "branch_why", "likely_first_new_dept",
                                          "likely_first_new_dept_by_lift"]]


def new_client_models(accounts, branch, top_starts, fit_map, today, log=print):
    train_from = today - pd.DateOffset(years=config.PS_TRAIN_YEARS)
    pool = accounts[(accounts["start_date"] >= train_from) & accounts["launch_bucket"].notna()].copy()
    d5 = f"days_till_{config.PS_GROWTH_SEATS}_headcount"
    gro = pool[pool["launch_bucket"].ne("5+") & (pool["days_observed"] >= config.PS_GROWTH_DAYS + config.MILESTONE_HOLD_DAYS)].copy()
    gro["y"] = (gro[d5].astype(float) <= config.PS_GROWTH_DAYS).astype(int)
    brn = pool[pool["start_dept"].notna() & (pool["days_observed"] >= config.PS_BRANCH_DAYS)].copy()
    brn["y"] = (brn["first_branch_day"] <= config.PS_BRANCH_DAYS).astype(int)

    g_model, g_cuts, g_check, g_auc = fit(gro, [], PROFILE, "y",
        f"Growth to {config.PS_GROWTH_SEATS} seats in {config.PS_GROWTH_DAYS}d (new clients)", log=log)
    b_model, b_cuts, b_check, b_auc = fit(brn, [], PROFILE, "y",
        f"New department in first {config.PS_BRANCH_DAYS}d (new clients)", log=log)

    # How well the models rank clients when scored like a prospect (starting department Unknown, launch 1-2 staff).
    # Measured on the training clients, so slightly optimistic.
    def prospect_auc(train, model):
        X = train[PROFILE].copy()
        X["start_dept_grp"], X["launch_bucket"] = "Unknown", "1-2"
        return roc_auc_score(train["y"], model.predict_proba(X)[:, 1])
    prospect_aucs = {"growth": prospect_auc(gro, g_model), "branch": prospect_auc(brn, b_model)}

    # Extra seat milestones: launched below N seats, observed long enough for the milestone hold to be confirmed
    milestones, ms_checks, ms_factors, ms_train = {}, {}, [], {}
    for n, d in config.PS_MILESTONES:
        t = pool[(pool["launch_size"] < n) & (pool["days_observed"] >= d + config.MILESTONE_HOLD_DAYS)].copy()
        t["y"] = (t[f"days_till_{n}_headcount"].astype(float) <= d).astype(int)
        if t["y"].sum() < config.PS_MIN_POSITIVES:
            log(f"[4 propensity] {n} seats in {d}d: only {int(t['y'].sum())} clients reached it, model not fitted")
            continue
        m, cuts, chk, auc = fit(t, [], PROFILE, "y", f"Reach {n} seats in {d}d (new clients)", log=log)
        milestones[(n, d)] = (m, cuts)
        prospect_aucs[(n, d)] = prospect_auc(t, m)
        ms_checks[f"New client reaches {n} seats in {d // 365}y"] = (chk, auc)
        ms_factors.append(factors(m, t, [], PROFILE)[["factor", "level", "vs_average_pts"]]
                          .rename(columns={"vs_average_pts": f"reach{n}_vs_avg_pts"}))
        ms_train[(n, d)] = t

    gf, bf = factors(g_model, gro, [], PROFILE), factors(b_model, brn, [], PROFILE)
    new_factors = (gf[["factor", "level", "rows", "vs_average_pts"]]
                   .rename(columns={"rows": "rows_growth", "vs_average_pts": "growth_vs_avg_pts"})
                   .merge(bf[["factor", "level", "rows", "vs_average_pts"]]
                          .rename(columns={"rows": "rows_branch", "vs_average_pts": "branch_vs_avg_pts"}),
                          on=["factor", "level"], how="outer"))
    for f in ms_factors:
        new_factors = new_factors.merge(f, on=["factor", "level"], how="outer")
    new_factors = new_factors.sort_values(["factor", "growth_vs_avg_pts"], ascending=[True, False])

    b = branch.loc[branch.index.isin(pool.index) & branch["first_branch_dept"].notna()]
    next_by_start = b.groupby("start_dept")["first_branch_dept"].value_counts(normalize=True).rename("p").reset_index()
    mode = lambda df: {f: df[f].mode().iat[0] for f in PROFILE}
    refs = {"growth": mode(gro), "branch": mode(brn), **{k: mode(t) for k, t in ms_train.items()}}
    scorer = NewClientScorer((g_model, g_cuts), (b_model, b_cuts), milestones, next_by_start,
                             b["first_branch_dept"].value_counts(normalize=True),
                             b["start_dept"].value_counts().to_dict(), top_starts, fit_map, refs)

    seen  = pool.groupby(PROFILE_DISPLAY, observed=True).size().rename("clients_seen")
    act_g = gro.groupby(PROFILE_DISPLAY, observed=True)["y"].agg(n_growth_observed="size", actual_growth_rate="mean")
    act_b = brn.groupby(PROFILE_DISPLAY, observed=True)["y"].agg(n_branch_observed="size", actual_branch_rate="mean")
    prof = pd.concat([seen, act_g, act_b], axis=1).reset_index()
    prof = prof[prof["clients_seen"] >= config.PS_MIN_PROFILE_CLIENTS]
    scorecard = (scorer.score_profiles(prof)
        [["line_item", "outlook", *PROFILE_DISPLAY, "p_growth", "growth_band", "growth_why", *scorer.milestone_columns(),
          "p_branch", "branch_band", "likely_first_new_dept", "likely_first_new_dept_by_lift", "clients_seen",
          "n_growth_observed", "actual_growth_rate", "n_branch_observed", "actual_branch_rate"]]
        .sort_values(["p_growth", "p_branch"], ascending=False, na_position="last").round(3).reset_index(drop=True))
    log(f"[4 propensity] new-client scorecard: {len(scorecard)} profiles | outlook mix: {scorecard['outlook'].value_counts().to_dict()}")
    return dict(new_client_scorecard=scorecard, scorer=scorer, new_factors=new_factors,
                growth_check=g_check, branch_check=b_check, growth_auc=g_auc, branch_auc=b_auc,
                milestone_checks=ms_checks, growth_train=gro, branch_train=brn, milestone_train=ms_train,
                prospect_aucs=prospect_aucs)


# ================================================================ existing clients
ORG_LABELS = {"industry_fit": "industry", "country": "country", "start_dept_grp": "started in"}

def _org_label(f, v):
    if f in ORG_LABELS and v in ("Other", "Unknown"):
        return None
    if f == "seat_change_180d" and v <= 0:
        return None
    if f == "log_seats":
        return f"{int(round(np.expm1(v)))} seats"
    if f == "age_years":
        return f"{v:.1f} yrs with us"
    if f == "seat_change_180d":
        return f"{v:+.0f} seats in last 6m"
    if f == "hires_180d":
        return f"{v:.0f} hires in last 6m"
    if f == "n_depts":
        return f"{v:.0f} dept{'' if round(v) == 1 else 's'} already"
    return f"{ORG_LABELS.get(f, f)}: {v}"

# Traits the dashboard already shows on each client's row ("With us": seats, recent change, time as a client; and the
# department count). In the "why" they are summarised in a phrase instead of listed ("9 seats" says little next to the
# seat count). Each phrase gets the client's value and the typical (reference) value.
ORG_CONTEXT = {
    "log_seats":        lambda v, r: "its size",
    "seat_change_180d": lambda v, r: "recent growth",
    "hires_180d":       lambda v, r: "recent growth",
    # time with us: a stage, not a reason (and partly onboarding: a staggered launch looks like growth), so never named;
    # when it is the only driver the text is ORG_CONTEXT_FALLBACK
    "age_years":        lambda v, r: None,
    # one department: true of every client the dashboard's second-department chip can show, so it explains nothing
    "n_depts":          lambda v, r: None if round(v) == 1 else "its departments so far",
}
ORG_CONTEXT_FALLBACK = {"age_years": "In line with clients at this stage"}   # the why when a silent trait is the only driver

def _seats_on(timeline, snaps, date_col):
    """Seats each snapshot's client has on the date in date_col (0 before the first hire)."""
    tl = timeline[["Shortcode", "date", "active_staff"]].astype({"date": "datetime64[ns]"}).sort_values("date")
    q = snaps[["Shortcode", date_col]].reset_index().astype({date_col: "datetime64[ns]", "Shortcode": tl["Shortcode"].dtype})
    r = pd.merge_asof(q.sort_values(date_col), tl.rename(columns={"date": date_col}), on=date_col, by="Shortcode",
                      direction="backward")
    return r.set_index("index")["active_staff"].reindex(snaps.index).fillna(0)

def seat_milestone_ranges():
    """(lowest seats, milestone) per ORG_SEAT_MILESTONES: [(1, 5), (5, 10), (10, 20)]. A client with s seats is scored
    for the milestone whose range holds s; clients at or above the largest milestone are out of scope."""
    steps = sorted(config.ORG_SEAT_MILESTONES)
    return list(zip([1] + steps[:-1], steps))

def organic_model(accounts, timeline, src, dept_entered, today, log=print):
    """Snapshot every PS_SNAP_STEP days of age: features that day; outcomes over the next year =
    (a) a department never had before, (b) more seats than on the snapshot day (net seat growth)."""
    org = accounts[accounts["start_dept"].notna()].copy()
    train_from = today - pd.DateOffset(years=config.PS_TRAIN_YEARS)
    horizon = max(config.PS_BRANCH_DAYS, config.PS_SEAT_GROWTH_DAYS)
    grid = org[["start_date", "days_observed"]].copy()
    grid["age"] = [list(range(config.PS_MIN_SNAP_AGE, int(o) + 1, config.PS_SNAP_STEP)) for o in grid["days_observed"]]
    grid = grid.explode("age").dropna(subset=["age"]).reset_index()
    grid["age"] = grid["age"].astype(int)
    grid["snap_date"] = grid["start_date"] + pd.to_timedelta(grid["age"], unit="D")
    grid = grid[(grid["snap_date"] >= train_from) & (grid["age"] + horizon <= grid["days_observed"])]
    snaps = snapshot_features(grid[["Shortcode", "age", "snap_date"]], timeline, src, dept_entered, org, ORG_CAT)
    snaps = snaps[snaps["seats"] > 0].copy()

    w = snaps[["Shortcode", "age"]].reset_index().merge(dept_entered[["Shortcode", "role_group", "entered_day"]], on="Shortcode")
    # a department first staffed in the client's first ORG_DEPT_LAUNCH_DAYS is a staggered launch, not an added department
    w = w[(w["entered_day"] > w["age"]) & (w["entered_day"] <= w["age"] + config.PS_BRANCH_DAYS)
          & (w["entered_day"] > config.ORG_DEPT_LAUNCH_DAYS)]
    first_new = w.sort_values(["index", "entered_day"]).drop_duplicates("index").set_index("index")["role_group"]
    snaps["y"] = snaps.index.isin(first_new.index).astype(int)
    snaps["next_dept"] = first_new.reindex(snaps.index)
    snaps["later_date"] = snaps["snap_date"] + pd.Timedelta(days=config.PS_SEAT_GROWTH_DAYS)
    snaps["seats_later"] = _seats_on(timeline, snaps, "later_date")
    snaps["y_seats"] = (snaps["seats_later"] > snaps["seats"]).astype(int)

    groups = snaps["Shortcode"].to_numpy()
    model, cuts, check, auc, p_cv = fit(snaps, ORG_NUM, ORG_CAT, "y",
        f"New department in next {config.PS_BRANCH_DAYS}d (existing clients)", groups=groups, log=log, return_cv=True)
    # One-department clients: the same model, banded among one-department snapshots only. More departments raise the
    # score, so on the all-client bands most one-department clients land in Low / Medium; these bands compare like with like.
    one = (snaps["n_depts"] == 1).to_numpy()
    one_cuts = np.quantile(p_cv[one], [1 / 3, 2 / 3])
    one_check = band_check(p_cv[one], snaps.loc[one, "y"].to_numpy(), one_cuts)
    one_auc = roc_auc_score(snaps.loc[one, "y"], p_cv[one])
    log(f"[4 propensity] Second department, one-department clients: {int(one.sum())} snapshots | base rate "
        f"{snaps.loc[one, 'y'].mean():.1%} | AUC within them {one_auc:.2f} | band cut-offs {one_cuts[0]:.0%} / {one_cuts[1]:.0%}")
    s_model, s_cuts, s_check, s_auc = fit(snaps, ORG_NUM, ORG_CAT, "y_seats",
        f"More seats in {config.PS_SEAT_GROWTH_DAYS}d than today (existing clients)", groups=groups, log=log)
    org_factors = factors(model, snaps, ORG_NUM, ORG_CAT).sort_values(["factor", "vs_average_pts"], ascending=[True, False])
    seat_factors = factors(s_model, snaps, ORG_NUM, ORG_CAT).sort_values(["factor", "vs_average_pts"], ascending=[True, False])

    # Seat milestones: each N is the NEXT milestone for clients between the previous milestone and N (1-4 -> 5,
    # 5-9 -> 10, 10-19 -> 20). Snapshots in that range: did the client reach and hold N+ within the window?
    seat_milestones = {}
    for lo, n in seat_milestone_ranges():
        col = f"y_to_{n}"
        in_range = snaps["seats"].between(lo, n - 1)
        runs = held_run_starts(timeline, n, config.MILESTONE_HOLD_DAYS, today)
        q = snaps.loc[in_range, ["Shortcode", "snap_date", "later_date"]].reset_index().merge(runs, on="Shortcode")
        hit = q.loc[(q["start"] > q["snap_date"]) & (q["start"] <= q["later_date"]), "index"].unique()
        snaps[col] = np.where(in_range, snaps.index.isin(hit).astype(float), np.nan)
        sub = snaps[in_range].copy()
        sub[col] = sub[col].astype(int)
        if sub[col].sum() < config.PS_MIN_POSITIVES:
            log(f"[4 propensity] {lo}-{n - 1} seats -> {n}+: only {int(sub[col].sum())} snapshots reached it, model not fitted")
            continue
        m, c, chk, a = fit(sub, ORG_NUM, ORG_CAT, col,
                           f"{lo}-{n - 1} seats -> {n}+ within {config.PS_SEAT_GROWTH_DAYS}d (existing clients)",
                           groups=sub["Shortcode"].to_numpy(), log=log)
        seat_milestones[n] = dict(model=m, cuts=c, check=chk, auc=a, rows=len(sub), seats_from=lo, seats_to=n - 1,
                                  factors=factors(m, sub, ORG_NUM, ORG_CAT).sort_values(["factor", "vs_average_pts"], ascending=[True, False]))

    # Likely next department given the departments held; each "added X" event counted once per client
    ev = snaps[snaps["y"] == 1].reset_index().sort_values("age").drop_duplicates(["Shortcode", "next_dept"])
    held_ev = ev[["index", "Shortcode", "age", "next_dept"]].merge(dept_entered[["Shortcode", "role_group", "entered_day"]], on="Shortcode")
    held_ev = held_ev[held_ev["entered_day"] <= held_ev["age"]]
    pair_n = held_ev.groupby(["role_group", "next_dept"]).size()
    have_n = held_ev.groupby("role_group")["index"].nunique()
    next_given = (pair_n / have_n.reindex(pair_n.index.get_level_values(0)).to_numpy()).rename("p").reset_index()
    next_given = next_given[next_given["role_group"].map(have_n) >= 10]
    return dict(org=org, organic_snaps=snaps, organic_model=model, organic_cuts=cuts, organic_check=check,
                organic_auc=auc, organic_factors=org_factors, next_given_dept=next_given,
                one_dept_cuts=one_cuts, one_dept_check=one_check, one_dept_auc=one_auc,
                next_overall_org=ev["next_dept"].value_counts(normalize=True),
                seat_model=s_model, seat_cuts=s_cuts, seat_check=s_check, seat_auc=s_auc, seat_factors=seat_factors,
                seat_milestones=seat_milestones)

def organic_list(om, timeline, src, dept_entered, today, current_seats=None):
    """Scores every client with seats today. current_seats (shortcode -> seats, from the dashboard) replaces the
    engagement list's seat count where it lists the client: it decides the seat milestone and feeds the "seats now"
    input. The other inputs (seat change and hires in the last 180 days, departments, tenure) stay engagement-list based."""
    org, model = om["org"], om["organic_model"]
    active = (org["engagement_active"] == 1) & (org["current_headcount"] > 0)
    if current_seats is not None:
        active |= org.index.astype(str).isin(current_seats.index)
    active = org[active]
    now = snapshot_features(pd.DataFrame({"Shortcode": active.index, "age": active["days_observed"].astype(int).to_numpy(),
                                          "snap_date": today}), timeline, src, dept_entered, org, ORG_CAT).set_index("Shortcode")
    now["seats_engagement"] = now["seats"]
    now["seats_source"] = "engagement list"
    if current_seats is not None:
        dash = current_seats.reindex(now.index.astype(str)).set_axis(now.index)
        now.loc[dash.notna(), "seats_source"] = "dashboard"
        now["seats"] = dash.fillna(now["seats"])
        now["log_seats"] = np.log1p(now["seats"].clip(lower=0))
    now = now[now["seats"] > 0]
    now["industry"] = org["industry"].reindex(now.index)
    Xn = now[ORG_NUM + ORG_CAT]
    ref = {f: (om["organic_snaps"][f].median() if f in ORG_NUM else om["organic_snaps"][f].mode().iat[0]) for f in Xn.columns}
    now["seat_band"] = pd.cut(now["seats"], bins=config.PS_SEAT_BANDS, labels=config.PS_SEAT_LABELS)
    peers = lambda col: (now[col] / now.groupby("seat_band", observed=True)[col].transform("mean")).round(2)

    # (a) department expansion
    now["p_new_dept_12m"] = model.predict_proba(Xn)[:, 1]
    now["band"] = band(now["p_new_dept_12m"].to_numpy(), om["organic_cuts"])
    now["why"] = reasons(model, Xn, ref, _org_label, context=ORG_CONTEXT, fallback=ORG_CONTEXT_FALLBACK)   # context traits summarised (dashboard)
    now["why_all"] = reasons(model, Xn, ref, _org_label)                     # every trait listed (workbook)
    now["vs_peers"] = peers("p_new_dept_12m")
    # one-department clients: the same chance, banded among one-department clients (a second department)
    one = now["n_depts"] == 1
    now["p_second_dept"] = now["p_new_dept_12m"].where(one)
    now["band_second_dept"] = None
    now.loc[one, "band_second_dept"] = list(band(now.loc[one, "p_new_dept_12m"].to_numpy(), om["one_dept_cuts"]).astype(str))
    # (b) seat growth
    now["p_seat_growth_12m"] = om["seat_model"].predict_proba(Xn)[:, 1]
    now["seat_growth_band"] = band(now["p_seat_growth_12m"].to_numpy(), om["seat_cuts"])
    now["seat_why"] = reasons(om["seat_model"], Xn, ref, _org_label)
    now["seat_vs_peers"] = peers("p_seat_growth_12m")
    # (c) seat milestones: each client is scored for its NEXT milestone only (1-4 seats -> 5+, 5-9 -> 10+, 10-19 -> 20+)
    ms_cols = []
    for n, sm in om["seat_milestones"].items():
        under = now["seats"].between(sm["seats_from"], sm["seats_to"])
        now[f"p_to_{n}"], now[f"band_to_{n}"], now[f"why_to_{n}"], now[f"why_to_{n}_all"] = np.nan, None, None, None
        if under.any():
            now.loc[under, f"p_to_{n}"] = sm["model"].predict_proba(Xn[under])[:, 1]
            now.loc[under, f"band_to_{n}"] = list(band(now.loc[under, f"p_to_{n}"].to_numpy(), sm["cuts"]).astype(str))
            now.loc[under, f"why_to_{n}"] = reasons(sm["model"], Xn[under], ref, _org_label, context=ORG_CONTEXT, fallback=ORG_CONTEXT_FALLBACK)
            now.loc[under, f"why_to_{n}_all"] = reasons(sm["model"], Xn[under], ref, _org_label)
        ms_cols += [f"p_to_{n}", f"band_to_{n}", f"why_to_{n}", f"why_to_{n}_all"]
    steps = sorted(config.ORG_SEAT_MILESTONES)
    now["next_seat_milestone"] = [next((n for n in steps if s < n), np.nan) for s in now["seats"]]
    now["p_next_seat_milestone"] = [now.at[sc, f"p_to_{int(n)}"] if n == n and f"p_to_{int(n)}" in now else np.nan
                                    for sc, n in now["next_seat_milestone"].items()]
    now["band_next_seat_milestone"] = [now.at[sc, f"band_to_{int(n)}"] if n == n and f"band_to_{int(n)}" in now else None
                                       for sc, n in now["next_seat_milestone"].items()]
    now["why_next_seat_milestone"] = [now.at[sc, f"why_to_{int(n)}"] if n == n and f"why_to_{int(n)}" in now else None
                                      for sc, n in now["next_seat_milestone"].items()]

    # Likely next department: average over departments held, excluding those, as a share of the options left;
    # lift = that share / the department's usual share of additions (among the same options)
    held_now = dept_entered[dept_entered["Shortcode"].isin(now.index)][["Shortcode", "role_group"]]
    cand = held_now.merge(om["next_given_dept"], on="role_group")
    cand = cand.merge(held_now.rename(columns={"role_group": "next_dept"}).assign(held=1), on=["Shortcode", "next_dept"], how="left")
    cand = cand[cand["held"].isna()]
    n_held = held_now.groupby("Shortcode").size()
    score = cand.groupby(["Shortcode", "next_dept"])["p"].sum() / n_held.reindex(
        cand.groupby(["Shortcode", "next_dept"]).size().index.get_level_values(0)).to_numpy()
    score = score / score.groupby(level=0).transform("sum")
    held_sets = held_now.groupby("Shortcode")["role_group"].agg(set)
    overall = om["next_overall_org"]
    by_client = {sc: s.droplevel(0) for sc, s in score.groupby(level=0)}
    likely, by_lift = {}, {}
    for sc in now.index:
        base = overall.drop(list(held_sets.get(sc, set())), errors="ignore")
        base = base / base.sum() if len(base) else base
        if sc in by_client and len(by_client[sc]):
            likely[sc] = fmt_share_lift(by_client[sc], base)
            by_lift[sc] = fmt_by_lift(by_client[sc], base)
        else:
            top = base.sort_values(ascending=False).head(2)
            likely[sc] = (", ".join(f"{n} {p:.0%}" for n, p in top.items()) + " (overall)") if len(top) else ""
            by_lift[sc] = ""
    now["likely_next_dept"] = pd.Series(likely)
    now["likely_next_dept_by_lift"] = pd.Series(by_lift)

    # "; "-separated: some department names contain a comma (e.g. "Creative, Design & Multimedia")
    now["current_depts"] = held_sets.reindex(now.index).map(lambda s: "; ".join(sorted(s)) if isinstance(s, set) else "")
    top = max(config.ORG_SEAT_MILESTONES)
    milestone_txt = [(f"{int(r.next_seat_milestone)}+ seats in 12m: {r.band_next_seat_milestone} ({r.p_next_seat_milestone:.0%})"
                      if r.p_next_seat_milestone == r.p_next_seat_milestone else
                      f"{top}+ seats already (seat milestones out of scope)" if r.seats >= top else "seat milestone not scored")
                     for r in now.itertuples()]
    now["line_item"] = [
        f"{sc} | {r.industry} | {int(r.seats)} seats, {int(r.n_depts)} dept(s)  ->  {mt} | "
        f"New dept in 12m: {r.band} ({r.p_new_dept_12m:.0%}, {r.vs_peers:.1f}x peers) | likely next: {r.likely_next_dept} | "
        f"why: {r.why or 'no standout traits'}"
        for sc, r, mt in zip(now.index, now.itertuples(), milestone_txt)]
    lst = (now.reset_index()
        [["Shortcode", "line_item", "band", "p_new_dept_12m", "vs_peers", "p_second_dept", "band_second_dept",
          "seat_band", "likely_next_dept",
          "likely_next_dept_by_lift", "why", "why_all", "next_seat_milestone", "p_next_seat_milestone", "band_next_seat_milestone",
          "why_next_seat_milestone",
          *ms_cols, "seat_growth_band", "p_seat_growth_12m", "seat_vs_peers", "seat_why", "seats_source", "seats_engagement",
          "industry", "country", "seats", "n_depts", "current_depts", "hires_180d", "seat_change_180d", "age_years"]]
        .rename(columns={"seats": "current_seats", "age_years": "years_with_us"})
        .sort_values("p_new_dept_12m", ascending=False).round(3).reset_index(drop=True))
    rising = lst[lst["current_seats"] < 10].sort_values("vs_peers", ascending=False).head(25).reset_index(drop=True)
    return lst, rising


def prospect_profiles(scorer, countries):
    """New Logo lookup: every industry group x country, scored as a brand-new client whose first role and size
    aren't known yet (starting department 'Unknown', launch 1-2 staff, as ~95% of clients launch)."""
    grid = pd.MultiIndex.from_product([list(mappings.INDUSTRY_GROUPS) + ["Unknown"], countries],
                                      names=["industry", "country"]).to_frame(index=False)
    grid["start_dept_grp"], grid["launch_bucket"] = "Unknown", "1-2"
    sc = scorer.score_profiles(grid)
    sc["industry_sector"] = sc["industry"].map(mappings.INDUSTRY_SECTOR).fillna("Unknown")
    sc["profile_key"] = sc["industry"] + "|" + sc["country"]
    ren = {"p_growth": "fit_growth_p", "growth_band": "fit_growth_band", "growth_why": "fit_growth_why",
           "p_branch": "fit_branch_1y_p", "branch_band": "fit_branch_1y_band", "branch_why": "fit_branch_1y_why"}
    for (n, d) in scorer.milestones:
        ren[milestone_col(n, d)] = f"fit_reach_{n}_p"
        ren[milestone_col(n, d).replace("p_", "band_", 1)] = f"fit_reach_{n}_band"
        ren[why_col(n, d)] = f"fit_reach_{n}_why"
    sc = sc.rename(columns=ren)
    return (sc[["profile_key", "industry", "industry_sector", "country", "industry_fit", "fit_growth_p", "fit_growth_band",
                "fit_growth_why", *[c for (n, d) in scorer.milestones for c in (f"fit_reach_{n}_p", f"fit_reach_{n}_band", f"fit_reach_{n}_why")],
                "fit_branch_1y_p", "fit_branch_1y_band", "fit_branch_1y_why", "likely_first_new_dept", "outlook", "line_item"]]
              .round(3))


def run(feat, today, log=print, current_seats=None):
    out = new_client_models(feat["accounts"], feat["branch"], feat["top_starts"], feat["industry_fit_map"], today, log)
    om = organic_model(feat["accounts"], feat["timeline"], feat["src"], feat["dept_entered"], today, log)
    out.update(om)
    out["organic_client_list"], out["organic_rising"] = organic_list(om, feat["timeline"], feat["src"], feat["dept_entered"], today,
                                                                     current_seats)
    out["prospect_profiles"] = prospect_profiles(out["scorer"], ["Australia", "United States", "United Kingdom", "New Zealand",
                                                                 "Canada", "Other", "Unknown"])
    lst = out["organic_client_list"]
    log(f"[4 propensity] active clients scored: {len(lst)} | new-dept bands: {lst['band'].value_counts().reindex(config.PS_BANDS).to_dict()}"
        f" | seat-growth bands: {lst['seat_growth_band'].value_counts().reindex(config.PS_BANDS).to_dict()}")
    return out
