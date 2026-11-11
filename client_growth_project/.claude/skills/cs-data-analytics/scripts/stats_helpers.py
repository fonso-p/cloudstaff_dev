"""Statistics, Lean Six Sigma and ops helpers.

Each helper returns plain numbers for the INDEPENDENT pandas side of QA. Where a matching
Excel formula template exists it is given as a constant so the workbook shows the live
version. Use Excel-2007-era functions only (NORMSINV, TDIST, CHIDIST, STDEV...).
"""
import math

import numpy as np
from scipy import stats

Z95 = 1.959963984540054

# Wilson score interval, Excel templates: .format(k="C{r}", n="B{r}")
WILSON_LO = ("=IFERROR((({k}/{n})+1.96^2/(2*{n})-1.96*SQRT(({k}/{n})*(1-{k}/{n})/{n}+1.96^2/(4*{n}^2)))"
             "/(1+1.96^2/{n}),0)")
WILSON_HI = ("=IFERROR((({k}/{n})+1.96^2/(2*{n})+1.96*SQRT(({k}/{n})*(1-{k}/{n})/{n}+1.96^2/(4*{n}^2)))"
             "/(1+1.96^2/{n}),0)")


def wilson_ci(k, n, z=1.96):
    """95% Wilson interval for a proportion k/n (better than +/- for small n or extreme p)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / den, (centre + half) / den


def two_proportion_test(k1, n1, k2, n2):
    """Two-sided z-test: is rate 1 really different from rate 2?"""
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or float("nan")
    z = (p1 - p2) / se
    return {"p1": p1, "p2": p2, "diff": p1 - p2, "z": z, "p_value": 2 * (1 - stats.norm.cdf(abs(z)))}


def chi_square(table):
    """Chi-square test of independence on a contingency table (list of lists)."""
    chi2, p, dof, expected = stats.chi2_contingency(np.array(table))
    small = int((np.array(expected) < 5).sum())
    return {"chi2": chi2, "p_value": p, "dof": dof, "cells_expected_below_5": small}


def compare_means(a, b):
    """Welch t-test plus Mann-Whitney (use MW when data are skewed, e.g. tenure, handle time)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    t = stats.ttest_ind(a, b, equal_var=False)
    mw = stats.mannwhitneyu(a, b, alternative="two-sided")
    return {"mean_a": a.mean(), "mean_b": b.mean(), "median_a": np.median(a), "median_b": np.median(b),
            "welch_p": t.pvalue, "mann_whitney_p": mw.pvalue}


def linear_trend(x, y):
    """Least-squares trend. Needs >= 3 points to say anything; p > 0.05 = no clear trend."""
    if len(x) < 3:
        return {"slope": 0.0, "p_value": 1.0, "r2": 0.0, "n": len(x)}
    r = stats.linregress(x, y)
    return {"slope": r.slope, "intercept": r.intercept, "p_value": r.pvalue, "r2": r.rvalue ** 2, "n": len(x)}


def imr_limits(values):
    """Individuals & moving range (I-MR) control chart limits.
    Excel: centre =AVERAGE(rng); MR-bar =AVERAGE(mr_rng); UCL = centre + 2.66*MRbar; LCL = centre - 2.66*MRbar."""
    v = np.asarray(values, float)
    mr = np.abs(np.diff(v))
    centre, mrbar = v.mean(), mr.mean() if len(mr) else 0.0
    ucl, lcl = centre + 2.66 * mrbar, centre - 2.66 * mrbar
    out = [i for i, x in enumerate(v) if x > ucl or x < lcl]
    return {"centre": centre, "mr_bar": mrbar, "ucl": ucl, "lcl": lcl, "out_of_control_idx": out,
            "run_of_8_same_side": _run_rule(v, centre)}


def _run_rule(v, c, k=8):
    run, side, hits = 0, 0, []
    for i, x in enumerate(v):
        s = 1 if x > c else (-1 if x < c else 0)
        run = run + 1 if s == side and s != 0 else 1
        side = s
        if run >= k:
            hits.append(i)
    return hits


def capability(values, lsl=None, usl=None):
    """Cp / Cpk. Cpk >= 1.33 capable, 1.0-1.33 marginal, < 1.0 not capable."""
    v = np.asarray(values, float)
    mu, sd = v.mean(), v.std(ddof=1)
    cp = (usl - lsl) / (6 * sd) if (usl is not None and lsl is not None and sd) else None
    parts = []
    if usl is not None and sd:
        parts.append((usl - mu) / (3 * sd))
    if lsl is not None and sd:
        parts.append((mu - lsl) / (3 * sd))
    return {"mean": mu, "sd": sd, "cp": cp, "cpk": min(parts) if parts else None}


def dpmo_sigma(defects, units, opportunities=1):
    """DPMO and short-term sigma level (with the conventional 1.5 shift).
    Excel: =NORMSINV(1-DPMO/1000000)+1.5"""
    dpmo = defects / (units * opportunities) * 1_000_000
    sigma = stats.norm.ppf(1 - dpmo / 1_000_000) + 1.5 if 0 < dpmo < 1_000_000 else (6.0 if dpmo == 0 else 0.0)
    return {"dpmo": dpmo, "sigma": sigma, "yield": 1 - dpmo / 1_000_000}


def pareto(series):
    """series: pandas Series of totals by category -> DataFrame sorted with share and cumulative share."""
    s = series.sort_values(ascending=False)
    total = s.sum()
    df = s.to_frame("value")
    df["share"] = df["value"] / total
    df["cumulative"] = df["share"].cumsum()
    df["vital_few"] = df["cumulative"].shift(fill_value=0) < 0.8
    return df


def min_sample_for_proportion(p=0.5, margin=0.05, z=1.96):
    """Rows needed to estimate a rate within +/- margin at 95% confidence."""
    return math.ceil(z * z * p * (1 - p) / (margin * margin))
