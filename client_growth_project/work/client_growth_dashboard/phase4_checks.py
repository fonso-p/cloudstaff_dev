"""Phase 4 checks: trace clients from the raw engagement list to the monthly table to the dashboard, and tie totals.

1. Trace: for 5 clients, recompute starts / churn / active at month end straight from the raw rows
   (independent of prep.py), compare every month with data/client_monthly.csv, then compare the client's
   totals with what the built dashboard shows in its Clients table.
2. Totals: dashboard (computed in the browser) vs prep.py outputs: clients, starts, churn, net, active staff now,
   status counts, and the Overview KPI text.
3. JavaScript errors on load (via check_page.py).
Run from the project root:  python work/client_growth_dashboard/phase4_checks.py
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_page  # noqa: E402

import prep  # noqa: E402  (only the settings are used: the trace below is recomputed independently)

STAFF_SRC = prep.STAFF_SRC
LAST_MONTH = prep.LAST_MONTH
CHROME = check_page.CHROME
FIXED = ["ARRIVIA", "AVETTA"]          # largest client and the largest MyStaff staff-count difference
N_RANDOM = 3
SEED = 20261010


def raw_monthly(raw, sc):
    """Independent month-by-month recount for one shortcode from the raw rows."""
    r = raw[raw["Shortcode"].astype(str).str.strip() == sc].copy()
    n_raw = len(r)
    r = r.drop_duplicates()                                                  # exact duplicate rows
    ed = pd.to_datetime(r["Engagement Date"], errors="coerce")
    dd = pd.to_datetime(r["Disengagement Date"], errors="coerce")
    ok = ed.notna() & (dd.isna() | (dd >= ed))                               # stints that end before they start are not seats
    ed, dd = ed[ok], dd[ok]
    first = ed.min().to_period("M")
    days = pd.date_range(ed.min(), max(ed.max(), dd.max() if dd.notna().any() else ed.max()), freq="D").to_numpy()[:, None]
    on = (ed.to_numpy() <= days) & (dd.isna().to_numpy() | (dd.to_numpy() >= days))   # on the books that day (start and end day both count)
    peak_day = int(on.sum(axis=1).max())
    out = []
    for m in pd.period_range(first, LAST_MONTH, freq="M"):
        me = m.to_timestamp(how="end").normalize()
        out.append(dict(month=str(m), starts=int((ed.dt.to_period("M") == m).sum()), churned=int((dd.dt.to_period("M") == m).sum()),
                        active_month_end=int(((ed <= me) & (dd.isna() | (dd > me))).sum())))
    return n_raw, int(ok.sum()), pd.DataFrame(out), peak_day


def dashboard_dump(html_path, codes):
    """Load the built page in headless Chrome (all scripts run), then read back what the page computed."""
    html = open(html_path, encoding="utf-8").read()
    probe = ("<script>window.addEventListener('load', () => setTimeout(() => {"
             "const f = filt(); const rows = clientRows(f, current.clients, current.W);"
             f"const want = {json.dumps(codes)};"
             "const out = {clients: D.clients.length, starts: sum(D.clients.map(c => sum(c.starts))), churn: sum(D.clients.map(c => sum(c.churn))),"
             " active_now: sum(D.clients.map(c => c.act[c.n - 1])),"
             " status: Object.fromEntries([...groupBy(D.clients, c => c.status)].map(([k, v]) => [k, v.length])),"
             " region: Object.fromEntries([...groupBy(D.clients, c => c.region)].map(([k, v]) => [k, v.length])),"
             " kpi_text: [...document.querySelectorAll('#p-overview .kpi')].map(k => k.innerText.replace(/\\s+/g, ' ').trim()),"
             " table_rows: rows.length, trace: rows.filter(r => want.includes(r.sc)),"
             " mv: moveRows(f, current.clients, current.W).filter(r => want.includes(r.sc)),"
             " stage_tie: STAGES.map(([a, b], i) => [stageStats(current.clients, a, b).total, sum(moveRows(f, current.clients, current.W).map(r => r['sn' + i] ?? 0))]),"
             " act: Object.fromEntries(D.clients.filter(c => want.includes(c.shortcode)).map(c => [c.shortcode, c.act]))};"
             "const p = document.createElement('pre'); p.id = '__probe'; p.textContent = JSON.stringify(out); document.body.appendChild(p);"
             "}, 2500));</script></body>")
    html = html.replace("</body>", probe, 1)
    tmp = os.path.join(tempfile.mkdtemp(), "probe.html")
    open(tmp, "w", encoding="utf-8").write(html)
    args = [CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=20000", "--dump-dom", "file://" + tmp]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=90).stdout
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        subprocess.run(["pkill", "-f", tmp])
    m = re.search(r'<pre id="__probe">(.*?)</pre>', out, re.S)
    if not m:
        sys.exit("Dashboard probe returned no result")
    return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def main():
    html_path = sorted(glob.glob("outputs/html/*_Client_Growth_Dashboard.html"))[-1]
    mon = pd.read_csv("data/client_monthly.csv", keep_default_na=False, na_values=[""])
    prof = pd.read_csv("data/client_profile.csv", keep_default_na=False, na_values=[""])
    excl = pd.read_csv("data/qa_excluded.csv")
    raw = pd.read_excel(STAFF_SRC, dtype=object)

    others = prof[~prof["shortcode"].isin(FIXED)].sample(N_RANDOM, random_state=SEED)["shortcode"].tolist()
    codes = FIXED + others
    dash = dashboard_dump(html_path, codes)
    dash_rows = {r["sc"]: r for r in dash["trace"]}
    mv_rows = {r["sc"]: r for r in dash["mv"]}
    stages = [(1, 3), (4, 6), (7, 12), (13, 24), (25, 36), (37, None)]
    fails = 0

    print("=" * 100, "\n1. TRACE: raw rows -> monthly table -> dashboard\n" + "=" * 100)
    for sc in codes:
        n_raw, n_valid, ind, peak_day = raw_monthly(raw, sc)
        m = mon[mon["shortcode"] == sc][["month", "starts", "churned", "active_month_end"]].reset_index(drop=True)
        p = prof[prof["shortcode"] == sc].iloc[0]
        d = dash_rows.get(sc, {})
        same_months = ind.equals(m)
        act_js = dash["act"].get(sc, [])
        same_js_act = act_js == m["active_month_end"].tolist()
        checks = {
            "monthly table = raw recount (every month)": same_months,
            "dashboard month-end staff = monthly table": same_js_act,
            "dashboard starts = raw": d.get("starts") == int(ind["starts"].sum()),
            "dashboard churned = raw": d.get("churn") == int(ind["churned"].sum()),
            "dashboard net = raw starts - churn": d.get("net") == int(ind["starts"].sum() - ind["churned"].sum()),
            "dashboard current staff = raw active end 2026-09": d.get("cur") == int(ind["active_month_end"].iloc[-1]),
            "dashboard start month = raw first month": d.get("start") == ind["month"].iloc[0],
            "dashboard starting seats = raw month-1 staff": d.get("startSeats") == int(ind["active_month_end"].iloc[0]),
            "dashboard peak seats = raw highest staff on any day": d.get("peakSeats") == peak_day,
        }
        # movement table: launch and each lifecycle stage (growth after launch) recomputed from the raw recount
        mv = mv_rows.get(sc, {})
        checks["movement table launch added / churned = raw month 1"] = (mv.get("lAdd"), mv.get("lOut")) == (int(ind["starts"].iloc[0]), int(ind["churned"].iloc[0]))
        ok_st = True
        for i, (a, b) in enumerate(stages):
            if len(ind) < (b or a):
                ok_st &= f"sa{i}" not in mv
                continue
            seg = ind.iloc[(1 if a == 1 else a - 1):(b or len(ind))]
            ok_st &= (mv.get(f"sa{i}"), mv.get(f"so{i}"), mv.get(f"sn{i}"), mv.get(f"se{i}")) == (
                int(seg["starts"].sum()), int(seg["churned"].sum()), int(seg["starts"].sum() - seg["churned"].sum()), int(seg["active_month_end"].iloc[-1]))
        checks["movement table added / churned / net / staff per stage = raw"] = ok_st
        fails += sum(not v for v in checks.values())
        print(f"\n{p['client_name']} ({sc}) | {p['region']} | {p['custom_division']} | {p['status']}")
        print(f"  raw rows {n_raw}, valid stints {n_valid}, months {len(ind)} ({ind['month'].iloc[0]} to {ind['month'].iloc[-1]})")
        print(f"  raw: starts {ind['starts'].sum()}, churned {ind['churned'].sum()}, staff end 2026-09 {ind['active_month_end'].iloc[-1]}, peak month-end {ind['active_month_end'].max()}, peak any day {peak_day}")
        print(f"  dashboard row: starts {d.get('starts')}, churned {d.get('churn')}, net {d.get('net')}, current {d.get('cur')}, start {d.get('start')}, "
              f"starting seats {d.get('startSeats')}, peak {d.get('peakSeats')}")
        for k, v in checks.items():
            print(f"    {'PASS' if v else 'FAIL'}  {k}")
        if not same_months:
            diff = ind.merge(m, on="month", how="outer", suffixes=("_raw", "_table"), indicator=True)
            print(diff[(diff["_merge"] != "both") | (diff["starts_raw"] != diff["starts_table"]) | (diff["churned_raw"] != diff["churned_table"])
                       | (diff["active_month_end_raw"] != diff["active_month_end_table"])].head(10).to_string(index=False))

    print("\n" + "=" * 100, "\n2. TOTALS: dashboard (browser) vs prep.py outputs\n" + "=" * 100)
    rows_excluded = int(excl["rows"].sum())
    tot = [
        ("Clients", dash["clients"], len(prof)),
        ("Clients in Clients table (default filters)", dash["table_rows"], len(prof)),
        ("Starts", dash["starts"], int(mon["starts"].sum())),
        ("Churned", dash["churn"], int(mon["churned"].sum())),
        ("Active staff now (end 2026-09)", dash["active_now"], int(prof["current_seats"].sum())),
        ("Net seats", dash["starts"] - dash["churn"], int(prof["net_seats"].sum())),
        ("Source rows = used + excluded", len(raw), None),
    ]
    for k in sorted(set(prof["status"])):
        tot.append((f"Status: {k}", dash["status"].get(k), int((prof["status"] == k).sum())))
    for k in sorted(set(prof["region"])):
        tot.append((f"Region: {k}", dash["region"].get(k), int((prof["region"] == k).sum())))
    qa = json.load(open("data/client_monthly.json"))["qa"]
    print(f"{'Measure':48} {'Dashboard':>12} {'prep.py':>12}  Result")
    for name, a, b in tot:
        if b is None:   # row tie-out
            ok = len(raw) == qa["included_rows"] + rows_excluded == qa["source_rows"]
            print(f"{name:48} {qa['included_rows']:>12,} + {rows_excluded:,} = {len(raw):,}  {'PASS' if ok else 'FAIL'}")
        else:
            ok = a == b
            print(f"{name:48} {a:>12,} {b:>12,}  {'PASS' if ok else 'FAIL'}")
        fails += not ok
    for i, (lt, mt) in enumerate(dash["stage_tie"]):
        ok = lt == mt
        fails += not ok
        print(f"{'Lifecycle total net = movement table, stage ' + str(i + 1):48} {lt:>12,} {mt:>12,}  {'PASS' if ok else 'FAIL'}")
    kpi_active = next((t for t in dash["kpi_text"] if t.startswith("Active staff now")), "")
    ok = f"{int(prof['current_seats'].sum()):,}" in kpi_active
    fails += not ok
    print(f"{'Overview KPI text':48} '{kpi_active}'  {'PASS' if ok else 'FAIL'}")
    print(f"  (starts include valid stints only; {qa['included_rows']:,} rows used includes stints that end before they start, which count for the start month only)")

    print("\n" + "=" * 100, "\n3. JAVASCRIPT ERRORS ON LOAD\n" + "=" * 100)
    errs = check_page.run(html_path)
    ok = errs == "[]"
    fails += not ok
    print(f"errors: {errs}  {'PASS' if ok else 'FAIL'}")
    print(f"\nFile: {html_path} ({os.path.getsize(html_path) / 1e6:.2f} MB)")
    print(f"\nOVERALL: {'PASS' if fails == 0 else f'FAIL ({fails} checks)'}")
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
