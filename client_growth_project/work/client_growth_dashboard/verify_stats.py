"""Check the dashboard's JavaScript statistics against scipy (Phase 3 requirement).

Python side: rebuilds the windows independently from data/client_monthly.csv (not the JSON the page uses),
             then runs scipy.stats.kruskal, chi2_contingency (default Yates for 2x2) and chisquare.
JS side:     takes the data and the <script id="core"> block from the built dashboard, runs runTests(f)
             in headless Chrome for the same filters, and reads the results back.
Prints one comparison table; every statistic and p-value must agree to 1e-6.

Run from the project root:  python work/client_growth_dashboard/verify_stats.py
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TOL = 1e-6

# filter combinations to compare (same keys as the dashboard filter bar)
BASE = dict(win=6, thr=5, region="All", division="All", industry="All", status="All", segment="All", year="All")
COMBOS = [
    dict(BASE),
    dict(BASE, win=3, thr=3, region="APAC"),
    dict(BASE, win=12, thr=10, region="AMER", year="2022"),
    dict(BASE, win=5, thr=5, status="Active with staff", segment="1-4"),
    dict(BASE, win=6, thr=3, division="USTL"),
    dict(BASE, win=3, thr=5, year="2026"),
]


# ---------------- Python side (independent)
def seg3(h):
    return "0 staff" if h <= 0 else "1-4" if h <= 4 else "5-10" if h <= 10 else "10+"


def load_monthly():
    m = pd.read_csv("data/client_monthly.csv", keep_default_na=False, na_values=[""])
    m = m.sort_values(["shortcode", "months_since_start"])
    return m


def windows(m, f):
    """One row per complete window k of length N, from the monthly active_month_end column."""
    keep = m
    for col, key in [("region", "region"), ("custom_division", "division"), ("industry_rollup", "industry"), ("status", "status")]:
        if f[key] != "All":
            keep = keep[keep[col] == f[key]]
    N, rows = f["win"], []
    for sc, g in keep.groupby("shortcode", sort=False):
        act = g["active_month_end"].to_numpy()
        months = pd.PeriodIndex(g["month"], freq="M")
        for k in range(1, len(act) // N + 1):
            a, b = (k - 1) * N, k * N - 1
            start_hc = act[0] if k == 1 else act[a - 1]          # window 1 counts growth after launch (from end of month 1)
            prev = start_hc
            rows.append(dict(shortcode=sc, region=g["region"].iat[0], division=g["custom_division"].iat[0], industry=g["industry_rollup"].iat[0],
                             k=k, year=months[a].year, start_hc=start_hc, end_hc=act[b], net=act[b] - prev))
    w = pd.DataFrame(rows, columns=["shortcode", "region", "division", "industry", "k", "year", "start_hc", "end_hc", "net"])
    w["seg"] = w["start_hc"].map(seg3)
    if f["segment"] != "All":
        w = w[w["seg"] == f["segment"]]
    if f["year"] != "All":
        w = w[w["year"] == int(f["year"])]
    w["hit"] = w["net"] >= f["thr"]
    return keep, w


def kw(groups):
    groups = {k: v for k, v in groups.items() if len(v)}
    if len(groups) < 2:
        return None
    try:
        r = stats.kruskal(*groups.values())
    except ValueError:      # all values identical
        return None
    return dict(stat=r.statistic, p=r.pvalue, df=len(groups) - 1, N=sum(map(len, groups.values())))


def chi_tab(tab):
    tab = np.array([r for r in tab if sum(r) > 0])
    if len(tab) < 2 or (tab.sum(axis=0) == 0).any():
        return None
    r = stats.chi2_contingency(tab)          # Yates correction is applied by scipy when df = 1
    return dict(stat=r.statistic, p=r.pvalue, df=int(r.dof), N=int(tab.sum()))


def bucket4(h):
    return "0" if h <= 0 else "1-2" if h <= 2 else "3-4" if h <= 4 else "5-9" if h <= 9 else "10+"


def py_tests(m, f, last_month, prof, extract):
    keep, w = windows(m, f)
    out = {}
    ws = w[w["start_hc"] > 0]                                  # segment tests leave out windows starting with 0 staff
    out["kw_segment"] = kw({s: g["net"].to_numpy() for s, g in ws.groupby("seg")})
    per = w.groupby("shortcode").agg(region=("region", "first"), division=("division", "first"), industry=("industry", "first"), avg=("net", "mean"), hit=("hit", "any"))
    out["kw_region"] = kw({r: g["avg"].to_numpy() for r, g in per.groupby("region")})
    out["kw_division"] = kw({d: g["avg"].to_numpy() for d, g in per.groupby("division")})
    segs = [s for s in ["1-4", "5-10", "10+"] if (ws["seg"] == s).any()]
    out["chi_segment"] = chi_tab([[int(ws[ws.seg == s].hit.sum()), int((~ws[ws.seg == s].hit).sum())] for s in segs])
    regs = [r for r in ["APAC", "AMER", "OPTI", "Unknown"] if (per["region"] == r).any()]
    out["chi_region"] = chi_tab([[int(per[per.region == r].hit.sum()), int((~per[per.region == r].hit).sum())] for r in regs])
    # client hit in any window vs division / industry, groups with 20+ clients in view
    for tid, col in [("chi_division", "division"), ("chi_industry", "industry")]:
        cnt = per.groupby(col)["hit"].agg(["sum", "size"])
        cnt = cnt[cnt["size"] >= 20]
        out[tid] = chi_tab([[int(r["sum"]), int(r["size"] - r["sum"])] for _, r in cnt.iterrows()])
    # window moved up a size bucket vs size at window start (1-2, 3-4, 5-9)
    order = ["0", "1-2", "3-4", "5-9", "10+"]
    wb = ws.assign(b0=ws["start_hc"].map(bucket4), b1=ws["end_hc"].map(bucket4))
    wb["up"] = wb["b1"].map(order.index) > wb["b0"].map(order.index)
    out["chi_bucket_up"] = chi_tab([[int(wb[wb.b0 == b].up.sum()), int((~wb[wb.b0 == b].up).sum())] for b in ["1-2", "3-4", "5-9"]])
    # reached 5 within 12 months vs starting seats, clients aged 12+ months (client filters only)
    pc = prof[prof["shortcode"].isin(set(keep["shortcode"]))].copy()
    pc = pc[(extract - pd.to_datetime(pc["start_date"])).dt.days >= 365]
    pc["sb"] = pd.cut(pc["starting_seats"], [-1, 1, 2, 4], labels=["0-1", "2", "3-4"])
    pc = pc[pc["sb"].notna()]
    pc["r5"] = pc["months_to_5"].notna() & (pc["months_to_5"] <= 12)
    out["chi_reach5"] = chi_tab([[int(g["r5"].sum()), int((~g["r5"]).sum())] for _, g in pc.groupby("sb", observed=True)])
    # path to 5 group vs region; reached 5 within 12 months by region / function / industry / division; after-5 retention; speed by region
    paths = ["Fast to 5 (within 6 months)", "Slow to 5 (after 6 months)", "Not yet at 5, still active", "Churned without reaching 5"]
    pa = prof[prof["shortcode"].isin(set(keep["shortcode"]))].copy()
    regs = [r for r in ["APAC", "AMER", "OPTI", "Unknown"] if (pa["region"] == r).any()]
    out["chi_path_region"] = chi_tab([[int(((pa.region == r) & (pa.path_group == g)).sum()) for g in paths] for r in regs])
    age = (extract - pd.to_datetime(pa["start_date"])).dt.days
    el = pa[(age >= 365) & (pa["starting_seats"] < 5)].copy()
    el["r12"] = el["date_5"].notna() & (el["months_to_5"] <= 12)
    for tid, col in [("chi_reach_region", "region"), ("chi_reach_function", "initial_function"), ("chi_reach_industry", "industry_rollup"), ("chi_reach_division", "custom_division")]:
        e2 = el[el[col] != "Unknown"] if col == "initial_function" else el
        cnt = e2.groupby(col)["r12"].agg(["sum", "size"])
        cnt = cnt[cnt["size"] >= 20]
        out[tid] = chi_tab([[int(r["sum"]), int(r["size"] - r["sum"])] for _, r in cnt.iterrows()])
    a24 = pa[age >= 730]
    out["chi_after5"] = chi_tab([[int((g["current_seats"] > 0).sum()), int((g["current_seats"] <= 0).sum())] for _, g in a24.groupby(a24["date_5"].notna())])
    spd = pa[pa["date_5"].notna() & (pa["starting_seats"] < 5)]
    out["kw_speed_region"] = kw({r: g["days_to_5"].to_numpy() for r, g in spd.groupby("region")})
    # seasonality: starts by calendar month, skipping each client's first 3 months, complete years (or the chosen year)
    s = keep[keep["months_since_start"] > 3].copy()
    per_m = pd.PeriodIndex(s["month"], freq="M")
    s["y"], s["mo"] = per_m.year, per_m.month
    last_full = last_month.year if last_month.month == 12 else last_month.year - 1
    s = s[s["y"] <= last_full] if f["year"] == "All" else s[s["y"] == int(f["year"])]
    n_months = 12 if (f["year"] == "All" or int(f["year"]) <= last_full) else last_month.month
    obs = s.groupby("mo")["starts"].sum().reindex(range(1, n_months + 1), fill_value=0).to_numpy()
    if obs.sum() > 0:
        r = stats.chisquare(obs)
        out["chi_season"] = dict(stat=r.statistic, p=r.pvalue, df=n_months - 1, N=int(obs.sum()))
    else:
        out["chi_season"] = None
    return out


# ---------------- JS side (the dashboard's own code)
def js_tests(html_path, combos):
    html = open(html_path, encoding="utf-8").read()
    data = re.search(r'<script id="data" type="application/json">.*?</script>', html, re.S).group(0)
    core = re.search(r'<script id="core">.*?</script>', html, re.S).group(0)
    harness = ("<script>const __R = " + json.dumps(combos) + ".map(f => Object.fromEntries(runTests(f).map(t => [t.id, t.res])));"
               "const p = document.createElement('pre'); p.id = '__out'; p.textContent = JSON.stringify(__R); document.body.appendChild(p);</script>")
    page = f"<!doctype html><html><head><meta charset='utf-8'></head><body>{data}{core}{harness}</body></html>"
    tmp = os.path.join(tempfile.mkdtemp(), "verify.html")
    open(tmp, "w", encoding="utf-8").write(page)
    args = [CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=10000", "--dump-dom", "file://" + tmp]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=90).stdout
    except subprocess.TimeoutExpired as e:      # headless Chrome sometimes does not exit; the dump is still usable
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        subprocess.run(["pkill", "-f", tmp])
    m = re.search(r'<pre id="__out">(.*?)</pre>', out, re.S)
    if not m:
        sys.exit("JS harness returned no result")
    return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def main():
    html_path = sorted(glob.glob("outputs/html/*_Client_Growth_Dashboard.html"))[-1]
    m = load_monthly()
    prof = pd.read_csv("data/client_profile.csv", keep_default_na=False, na_values=[""])
    extract = pd.Timestamp(json.load(open("data/client_monthly.json"))["extract"])   # extract date only (a setting)
    last_month = pd.Period(m["month"].max(), freq="M")
    js_all = js_tests(html_path, COMBOS)
    rows, worst = [], 0.0
    for i, f in enumerate(COMBOS, 1):
        label = f"#{i} win {f['win']}, thr {f['thr']}" + "".join(f", {k} {v}" for k, v in f.items() if k not in ("win", "thr") and v != "All")
        py = py_tests(m, f, last_month, prof, extract)
        for tid, pr in py.items():
            jr = js_all[i - 1].get(tid)
            if pr is None or jr is None:
                ok = pr is None and jr is None
                rows.append([label, tid, "n/a", "n/a", "n/a", "n/a", "", "both not testable" if ok else "MISMATCH (one side not testable)"])
                worst = worst if ok else 1.0
                continue
            d_stat, d_p = abs(pr["stat"] - jr["stat"]), abs(pr["p"] - jr["p"])
            same_n = pr["N"] == jr["N"] and pr["df"] == jr["df"]
            worst = max(worst, d_stat, d_p, 0.0 if same_n else 1.0)
            rows.append([label, tid, f"{pr['stat']:.6f}", f"{jr['stat']:.6f}", f"{pr['p']:.3e}", f"{jr['p']:.3e}",
                         f"N {pr['N']} df {pr['df']}", "match" if (d_stat < TOL and d_p < TOL and same_n) else f"MISMATCH dstat {d_stat:.2e} dp {d_p:.2e} N {jr['N']}"])
    t = pd.DataFrame(rows, columns=["filters", "test", "scipy stat", "JS stat", "scipy p", "JS p", "n", "result"])
    with pd.option_context("display.width", 250, "display.max_colwidth", 60, "display.max_rows", 200):
        print(t.to_string(index=False))
    print(f"\nDashboard: {html_path}")
    print(f"Largest absolute difference (stat or p): {worst:.2e}  ->  {'PASS' if worst < TOL else 'FAIL'} (tolerance {TOL})")
    sys.exit(0 if worst < TOL else 1)


if __name__ == "__main__":
    main()
