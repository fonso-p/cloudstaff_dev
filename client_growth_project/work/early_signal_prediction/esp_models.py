"""Early signal prediction: model zoo, out-of-time backtest, metrics, drivers and watch-list scoring.

Backtest (plan section 5): expanding window by start year. For each test year T, models are trained and tuned only on clients
that started before T; tuning uses time-ordered inner folds (train on years < y, validate on year y, for each training year y
after the first). The decision threshold is also chosen on those inner folds. Nothing from year T is seen before it is scored.
All random steps use SEED.
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score, brier_score_loss, f1_score,
                             precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

warnings.filterwarnings("ignore")
SEED = 42
COUNT_COLS = ["seats_d30", "seats_d60", "seats_d90", "starting_seats", "starts_d90", "starts_first_week", "adds_d31_90", "leavers_d90", "peak_d90"]
FAMILIES = ["Logistic regression", "Elastic net logistic", "Random forest", "LightGBM", "XGBoost"]
GRIDS = {
    "Logistic regression": [{"C": c} for c in (0.03, 0.1, 0.3, 1.0)],
    "Elastic net logistic": [{"C": c, "l1_ratio": r} for c in (0.1, 0.5) for r in (0.3, 0.7)],
    "Random forest": [{"min_samples_leaf": m, "max_depth": d} for m in (10, 25) for d in (None, 6)],
    "LightGBM": [{"num_leaves": n, "min_child_samples": m, "n_estimators": 300} for n in (4, 8) for m in (20, 40)],
    "XGBoost": [{"max_depth": d, "n_estimators": n} for d in (2, 3) for n in (200, 400)],
}


# ---------------------------------------------------------------- pipelines
def make_model(family, params, num, cat, pos_weight):
    """Pipeline: one-hot categories (rare levels pooled), numeric counts log-scaled for the linear models."""
    linear = family in ("Logistic regression", "Elastic net logistic")
    cnt = [c for c in num if c in COUNT_COLS]
    oth = [c for c in num if c not in COUNT_COLS]
    ohe = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=20, sparse_output=False)
    if linear:
        pre = ColumnTransformer([("cnt", Pipeline([("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")), ("sc", StandardScaler())]), cnt),
                                 ("oth", StandardScaler(), oth), ("cat", ohe, cat)])
    else:
        pre = ColumnTransformer([("num", "passthrough", num), ("cat", ohe, cat)])
    if family == "Logistic regression":
        est = LogisticRegression(C=params["C"], class_weight="balanced", max_iter=5000)
    elif family == "Elastic net logistic":
        est = LogisticRegression(C=params["C"], l1_ratio=params["l1_ratio"], solver="saga", class_weight="balanced", max_iter=20000)
    elif family == "Random forest":
        est = RandomForestClassifier(n_estimators=300, min_samples_leaf=params["min_samples_leaf"], max_depth=params["max_depth"],
                                     max_features="sqrt", class_weight="balanced_subsample", random_state=SEED, n_jobs=-1)
    elif family == "LightGBM":
        from lightgbm import LGBMClassifier
        est = LGBMClassifier(n_estimators=params["n_estimators"], learning_rate=0.03, num_leaves=params["num_leaves"],
                             min_child_samples=params["min_child_samples"], subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                             reg_lambda=1.0, scale_pos_weight=pos_weight, random_state=SEED, verbose=-1)
    elif family == "XGBoost":
        from xgboost import XGBClassifier
        est = XGBClassifier(n_estimators=params["n_estimators"], max_depth=params["max_depth"], learning_rate=0.05, subsample=0.8,
                            colsample_bytree=0.8, reg_lambda=1.0, scale_pos_weight=pos_weight, eval_metric="logloss",
                            random_state=SEED, n_jobs=4)
    return Pipeline([("pre", pre), ("est", est)])


def inner_folds(years):
    """Time-ordered folds inside the training years: train on years before y, validate on y."""
    ys = sorted(set(years))
    return [(np.where(years < y)[0], np.where(years == y)[0]) for y in ys[1:]]


def best_f1_threshold(y, p):
    qs = np.unique(np.quantile(p, np.linspace(0.5, 0.995, 120)))
    f1s = [f1_score(y, (p >= q).astype(int), zero_division=0) for q in qs]
    return float(qs[int(np.argmax(f1s))]) if len(qs) else 0.5


def tune(family, X, y, years, num, cat):
    """Pick parameters by mean average precision over the inner folds; return params, inner predictions and their labels."""
    folds = inner_folds(years)
    best = (-1, None, None, None)
    for params in GRIDS[family]:
        preds, labs, aps = [], [], []
        for tr, va in folds:
            if y[tr].sum() == 0 or y[va].sum() == 0:
                continue
            pw = (len(tr) - y[tr].sum()) / max(1, y[tr].sum())
            m = make_model(family, params, num, cat, pw).fit(X.iloc[tr], y[tr])
            p = m.predict_proba(X.iloc[va])[:, 1]
            preds.append(p)
            labs.append(y[va])
            aps.append(average_precision_score(y[va], p))
        score = float(np.mean(aps)) if aps else -1
        if score > best[0]:
            best = (score, params, np.concatenate(preds) if preds else np.array([]), np.concatenate(labs) if labs else np.array([]))
    return best


# ---------------------------------------------------------------- metrics
def metrics(y, p, thr):
    y, p = np.asarray(y), np.asarray(p)
    yhat = (p >= thr).astype(int)
    tn = int(((yhat == 0) & (y == 0)).sum())
    fp = int(((yhat == 1) & (y == 0)).sum())
    out = {"n": int(len(y)), "positives": int(y.sum()), "base_rate": float(y.mean()),
           "roc_auc": float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else np.nan,
           "pr_auc": float(average_precision_score(y, p)) if y.sum() > 0 else np.nan,
           "brier": float(brier_score_loss(y, np.clip(p, 0, 1))),
           "threshold": float(thr), "flagged": int(yhat.sum()),
           "accuracy": float(accuracy_score(y, yhat)), "balanced_accuracy": float(balanced_accuracy_score(y, yhat)),
           "precision": float(precision_score(y, yhat, zero_division=0)), "recall": float(recall_score(y, yhat, zero_division=0)),
           "f1": float(f1_score(y, yhat, zero_division=0)), "specificity": float(tn / (tn + fp)) if tn + fp else np.nan}
    for k in (10, 20):
        n_top = max(1, int(round(len(y) * k / 100)))
        hits = top_hits(y, p, n_top)
        out[f"precision_top{k}"] = hits / n_top
        out[f"capture_top{k}"] = hits / y.sum() if y.sum() else np.nan
        out[f"lift_top{k}"] = (hits / n_top) / y.mean() if y.mean() else np.nan
    return out


def top_hits(y, p, n_top):
    """Expected positives among the n_top highest scores; clients tied at the cut-off share the remaining places evenly."""
    y, p = np.asarray(y), np.asarray(p)
    cut = np.sort(p)[::-1][n_top - 1]
    above, tied = p > cut, p == cut
    room = n_top - above.sum()
    return float(y[above].sum() + y[tied].sum() * room / tied.sum())


def top_share_flags(p, years, share=0.20):
    """Capacity rule: flag the top `share` of clients in each test year by score (no threshold carried across years)."""
    flags = np.zeros(len(p), dtype=int)
    for yv in np.unique(years):
        idx = np.where(years == yv)[0]
        k = max(1, int(round(len(idx) * share)))
        flags[idx[np.argsort(-p[idx], kind="stable")[:k]]] = 1
    return flags


# ---------------------------------------------------------------- backtest
def backtest(df, target, test_years, num, cat, families=FAMILIES, include_auto=True):
    """Returns predictions (one row per client per model in the test years) and the chosen settings per fold."""
    d = df[df[f"elig_{target}"]].copy()
    X, y, yrs = d[num + cat], d[f"y_{target}"].to_numpy(), d["start_year"].to_numpy()
    rows, chosen = [], []
    for T in test_years:
        tr, te = np.where(yrs < T)[0], np.where(yrs == T)[0]
        ytr = y[tr]
        pw = (len(tr) - ytr.sum()) / max(1, ytr.sum())
        base = np.full(len(te), ytr.mean())
        # no-skill baseline: everyone gets the training base rate and nobody is flagged (an "always no" rule)
        rows += [dict(model="Baseline: base rate", year=T, sc=s, y=int(v), p=float(q), thr=1.01) for s, v, q in zip(d.index[te], y[te], base)]
        # single signal: staff on the books at day 90 (threshold = best F1 on the training years)
        s90 = d["seats_d90"].to_numpy().astype(float)
        thr_s = best_f1_threshold(ytr, s90[tr])
        rows += [dict(model="Single signal: staff at day 90", year=T, sc=s, y=int(v), p=float(q), thr=thr_s) for s, v, q in zip(d.index[te], y[te], s90[te])]
        fold_best = []
        for fam in families:
            score, params, ip, il = tune(fam, X.iloc[tr], ytr, yrs[tr], num, cat)
            thr = best_f1_threshold(il, ip) if len(ip) else 0.5
            m = make_model(fam, params, num, cat, pw).fit(X.iloc[tr], ytr)
            p = m.predict_proba(X.iloc[te])[:, 1]
            rows += [dict(model=fam, year=T, sc=s, y=int(v), p=float(q), thr=thr) for s, v, q in zip(d.index[te], y[te], p)]
            chosen.append(dict(year=T, model=fam, params=str(params), inner_pr_auc=score, threshold=thr))
            fold_best.append((score, fam, params))
        if include_auto:
            # auto-selected: the family with the best inner-fold PR AUC, probabilities calibrated (sigmoid) on the inner folds
            score, fam, params = max(fold_best, key=lambda t: t[0])
            cal = CalibratedClassifierCV(make_model(fam, params, num, cat, pw), method="sigmoid", cv=inner_folds(yrs[tr]))
            cal.fit(X.iloc[tr], ytr)
            p = cal.predict_proba(X.iloc[te])[:, 1]
            # threshold: best F1 on the calibrated model's predictions for the training years (test year never used)
            thr = best_f1_threshold(ytr, cal.predict_proba(X.iloc[tr])[:, 1])
            rows += [dict(model="Auto-selected + calibrated", year=T, sc=s, y=int(v), p=float(q), thr=thr) for s, v, q in zip(d.index[te], y[te], p)]
            chosen.append(dict(year=T, model="Auto-selected + calibrated", params=f"{fam} {params}", inner_pr_auc=score, threshold=thr))
    return pd.DataFrame(rows), pd.DataFrame(chosen)


def summarise(pred, n_boot=2000, refs=("Logistic regression", "Single signal: staff at day 90")):
    """Per model: pooled out-of-time metrics with bootstrap 95% ranges, per-year metrics, and paired AUC differences against each of `refs`."""
    rng = np.random.default_rng(SEED)
    pooled, per_year, diffs = [], [], []
    models = list(dict.fromkeys(pred["model"]))
    wide = pred.pivot_table(index=["year", "sc"], columns="model", values="p")
    yv = pred.drop_duplicates(["year", "sc"]).set_index(["year", "sc"])["y"].reindex(wide.index).to_numpy()
    yrs = np.array([i[0] for i in wide.index])
    boots = [rng.integers(0, len(yv), len(yv)) for _ in range(n_boot)]
    for mdl in models:
        g = pred[pred["model"] == mdl]
        # per year, with that fold's threshold
        for T, gy in g.groupby("year"):
            per_year.append(dict(model=mdl, year=T, **metrics(gy["y"], gy["p"], gy["thr"].iloc[0])))
            if mdl.startswith("Single signal"):
                per_year[-1]["brier"] = np.nan             # a staff count is not a probability
            if mdl.startswith("Baseline"):
                per_year[-1].update(roc_auc=0.5, pr_auc=float(gy["y"].mean()))
        # pooled: each client keeps its own fold threshold, so flags are pooled rather than one threshold for all years
        p = wide[mdl].to_numpy()
        thr = g.set_index(["year", "sc"])["thr"].reindex(wide.index).to_numpy()
        flags = (p >= thr).astype(int)
        m = metrics(yv, p, 0.5)
        tp, fp_, fn, tn = (int(((flags == a) & (yv == b)).sum()) for a, b in [(1, 1), (1, 0), (0, 1), (0, 0)])
        m.update(threshold=np.nan, flagged=int(flags.sum()), accuracy=(tp + tn) / len(yv), precision=tp / (tp + fp_) if tp + fp_ else 0.0,
                 recall=tp / (tp + fn) if tp + fn else 0.0, specificity=tn / (tn + fp_) if tn + fp_ else np.nan)
        m["f1"] = 2 * m["precision"] * m["recall"] / (m["precision"] + m["recall"]) if m["precision"] + m["recall"] else 0.0
        m["balanced_accuracy"] = (m["recall"] + (m["specificity"] or 0)) / 2
        n20 = {yv_: max(1, int(round((yrs == yv_).sum() * 0.20))) for yv_ in np.unique(yrs)}
        tp20 = sum(top_hits(yv[yrs == yv_], p[yrs == yv_], n20[yv_]) for yv_ in n20)     # top 20% within each test year, ties shared
        m.update(precision_top20_per_year=tp20 / sum(n20.values()), capture_top20_per_year=tp20 / yv.sum())
        aucs = [roc_auc_score(yv[b], p[b]) for b in boots if 0 < yv[b].sum() < len(b)]
        aps = [average_precision_score(yv[b], p[b]) for b in boots if yv[b].sum() > 0]
        m.update(roc_auc_lo=float(np.percentile(aucs, 2.5)), roc_auc_hi=float(np.percentile(aucs, 97.5)),
                 pr_auc_lo=float(np.percentile(aps, 2.5)), pr_auc_hi=float(np.percentile(aps, 97.5)))
        if mdl.startswith("Single signal"):
            m["brier"] = np.nan
        if mdl.startswith("Baseline"):                     # no skill by definition: a constant score cannot rank clients
            m.update(roc_auc=0.5, roc_auc_lo=0.5, roc_auc_hi=0.5, pr_auc=float(yv.mean()), pr_auc_lo=float(yv.mean()), pr_auc_hi=float(yv.mean()))
        pooled.append(dict(model=mdl, **m))
        for ref in refs:
            if mdl == ref or ref not in wide or mdl.startswith("Baseline"):
                continue
            r = wide[ref].to_numpy()
            dd = [roc_auc_score(yv[b], p[b]) - roc_auc_score(yv[b], r[b]) for b in boots if 0 < yv[b].sum() < len(b)]
            diffs.append(dict(model=mdl, versus=ref, auc_diff=float(roc_auc_score(yv, p) - roc_auc_score(yv, r)),
                              lo=float(np.percentile(dd, 2.5)), hi=float(np.percentile(dd, 97.5))))
    return pd.DataFrame(pooled), pd.DataFrame(per_year), pd.DataFrame(diffs)


def calibration_table(y, p, bins=5):
    """Clients grouped into equal-size bands of predicted probability: mean predicted vs actual rate."""
    d = pd.DataFrame({"y": y, "p": p}).sort_values("p").reset_index(drop=True)
    d["band"] = pd.qcut(d.index, bins, labels=[f"Band {i + 1}" for i in range(bins)])
    return d.groupby("band", observed=True).agg(clients=("y", "size"), predicted=("p", "mean"), actual=("y", "mean")).reset_index()


# ---------------------------------------------------------------- final model, drivers, watch list
def fit_final(df, target, num, cat):
    """Tune every family on all eligible years (inner time folds), pick the best by inner PR AUC, calibrate it, and refit the
    uncalibrated best and a logistic regression for explanations."""
    d = df[df[f"elig_{target}"]]
    X, y, yrs = d[num + cat], d[f"y_{target}"].to_numpy(), d["start_year"].to_numpy()
    pw = (len(y) - y.sum()) / max(1, y.sum())
    res = {fam: tune(fam, X, y, yrs, num, cat) for fam in FAMILIES}
    fam = max(res, key=lambda k: res[k][0])
    params = res[fam][1]
    cal = CalibratedClassifierCV(make_model(fam, params, num, cat, pw), method="sigmoid", cv=inner_folds(yrs)).fit(X, y)
    raw = make_model(fam, params, num, cat, pw).fit(X, y)
    lr = make_model("Logistic regression", res["Logistic regression"][1], num, cat, pw).fit(X, y)
    return dict(family=fam, params=params, calibrated=cal, raw=raw, lr=lr, inner={k: v[0] for k, v in res.items()})


def contributions(model, X):
    """Per-client contribution of each original feature to the score: SHAP for tree models, coefficient x value for logistic."""
    pre, est = model.named_steps["pre"], model.named_steps["est"]
    Z = pre.transform(X)
    names = pre.get_feature_names_out()
    if isinstance(est, LogisticRegression):
        C = Z * est.coef_[0]
    else:
        import shap
        sv = shap.TreeExplainer(est).shap_values(Z)
        C = sv[1] if isinstance(sv, list) else (sv[:, :, 1] if np.ndim(sv) == 3 else sv)
    orig = [n.split("__", 1)[1] for n in names]
    base_names = []
    for n in orig:
        hit = next((c for c in sorted(X.columns, key=len, reverse=True) if n == c or n.startswith(c + "_")), n)
        base_names.append(hit)
    out = pd.DataFrame(C, index=X.index, columns=names).T.groupby(base_names).sum().T
    return out


# ---------------------------------------------------------------- drivers and Target C (statsmodels, readable units)
def driver_frame(d):
    """Readable early signals for odds ratios: one unit = one more staff member, or yes / no."""
    X = pd.DataFrame(index=d.index)
    X["Staff at day 90 (per extra staff)"] = d["seats_d90"]
    X["Any staff added in days 31-90"] = (d["adds_d31_90"] > 0).astype(int)
    X["Second start within 90 days"] = d["second_start_by_d90"]
    X["Any leaver by day 90"] = (d["leavers_d90"] > 0).astype(int)
    X["2+ functions by day 90"] = (d["functions_d90"] >= 2).astype(int)
    for r in ("AMER", "OPTI"):
        X[f"Region {r} (vs APAC)"] = (d["region"] == r).astype(int)
    return X


def odds_ratios(df, target):
    """Logistic regression (statsmodels) on the readable signals: odds ratio, 95% range and p-value per signal."""
    import statsmodels.api as sm
    d = df[df[f"elig_{target}"]]
    X = sm.add_constant(driver_frame(d).astype(float))
    fit = sm.Logit(d[f"y_{target}"].astype(float), X).fit(disp=0, maxiter=200)
    ci = fit.conf_int()
    out = pd.DataFrame({"signal": X.columns, "odds_ratio": np.exp(fit.params.values), "lo": np.exp(ci[0].values), "hi": np.exp(ci[1].values),
                        "p_value": fit.pvalues.values, "clients_with_signal": [int((X[c] > 0).sum()) for c in X.columns]})
    return out[out["signal"] != "const"].reset_index(drop=True), fit


def cv_auc(df, target, reps=20):
    """Repeated stratified 5-fold cross-validated AUC of the readable logistic regression (used for Target C, too small to backtest)."""
    from sklearn.model_selection import StratifiedKFold
    d = df[df[f"elig_{target}"]]
    X, y = driver_frame(d).to_numpy(float), d[f"y_{target}"].to_numpy()
    aucs = []
    for r in range(reps):
        p = np.zeros(len(y))
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=SEED + r).split(X, y):
            m = LogisticRegression(max_iter=5000).fit(X[tr], y[tr])
            p[te] = m.predict_proba(X[te])[:, 1]
        aucs.append(roc_auc_score(y, p))
    return float(np.mean(aucs)), float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def shap_importance(model, X):
    """Mean absolute contribution per original feature (SHAP for trees, coefficient x value for logistic)."""
    c = contributions(model, X)
    return c.abs().mean().sort_values(ascending=False)
