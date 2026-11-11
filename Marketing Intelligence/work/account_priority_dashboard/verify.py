"""Check the built dashboard's numbers against an independent pandas recount of accounts.csv.

Opens the page in headless Chrome or Edge and steps through several filter settings (each list; each list with
an industry and employee band). At each setting it reads the KPI tiles, the score-spread chart, the Act now
chart and the priority list order, then compares them with pandas. It must end with OVERALL: PASS.

Run from the "Marketing Intelligence" folder:
    ../.venv/Scripts/python.exe work/account_priority_dashboard/verify.py [built.html]
"""
import glob
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", ".claude", "skills", "cs-dashboard", "scripts"))
from check_page import browser  # noqa: E402

CASES = [("Marketing|New Logo", "All", "All"), ("Marketing|Organic Growth", "All", "All"), ("SDR|New Logo", "All", "All"),
         ("BDM|New Logo", "All", "All"), ("BDM|Organic Growth", "All", "All"), ("SDR|New Logo", "Logistics", "All"),
         ("BDM|Organic Growth", "All", "201-500"), ("Marketing|New Logo", "Healthcare", "Unknown"), ("BDM|New Logo", "Unknown", "All")]

PROBE = """<script>window.addEventListener('load',()=>setTimeout(()=>{const out=[];
showCharts=true; setChartsUi();
for (const [t,i,bd] of %s){ $('fRole').value=t.split('|')[0]; fillLists(); $('fList').value=t.split('|')[1]; fillTeamFilters();
  if(curTeam()!==t){out.push({case:[t,i,bd],missing:true});continue;}
  const has=(id,v)=>[...$(id).options].some(o=>o.value===v);
  if(!has('fInd',i)||!has('fBand',bd)){out.push({case:[t,i,bd],missing:true});continue;}
  $('fInd').value=i; $('fBand').value=bd; render();
  out.push({case:[t,i,bd], kpi:[...document.querySelectorAll('#kpis .kpi-value')].map(e=>e.textContent),
    hist:charts.cHist.data.datasets.map(d=>({tier:d.label,data:d.data})),
    reasons:Object.fromEntries(charts.cReasons.data.labels.map((l,j)=>[l,charts.cReasons.data.datasets[0].data[j]])),
    order:listRows(filt(),current).map(r=>r.account_id)});}
const p=document.createElement('pre');p.id='__verify';p.textContent=JSON.stringify(out);document.body.appendChild(p);},800));</script>"""


def page_numbers(path):
    html = open(path, encoding="utf-8").read().replace("</body>", PROBE % json.dumps(CASES) + "</body>", 1)
    tmpdir = tempfile.mkdtemp()
    tmp = os.path.join(tmpdir, "page.html")
    open(tmp, "w", encoding="utf-8").write(html)
    args = [browser(), "--headless=new", "--disable-gpu", "--virtual-time-budget=20000", f"--user-data-dir={os.path.join(tmpdir, 'p')}", "--dump-dom", pathlib.Path(tmp).as_uri()]
    try:
        out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120).stdout
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    m = re.search(r'<pre id="__verify">(.*?)</pre>', out, re.S)
    if not m:
        sys.exit("NO RESULT (page did not finish loading)")
    return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def expected(df, team, ind, band):
    role, goal = team.split("|")
    d = df[(df.role == role) & (df.goal == goal)]
    if ind != "All":
        d = d[d.industry.fillna("Unknown") == ind]
    if band != "All":
        d = d[d.employee_band.fillna("Unknown") == band]
    n, hot = len(d), int(d.hot_trigger.notna().sum())
    kpi = [f"{n:,}", f"{hot:,}", f"{int((d.tier == 'Tier 1').sum()):,}", f"{round(100 * d.estimated_fields.notna().mean()) if n else 0:.0f}%" if n else "–"]
    hist = []
    for t in ["Tier 1", "Tier 2", "Tier 3"]:
        s = d[d.tier == t].priority_score
        hist.append({"tier": t, "data": [int(((s >= lo) & (s <= (100 if lo == 90 else lo + 9))).sum()) for lo in range(0, 100, 10)]})
    reasons = d.hot_trigger.value_counts().to_dict()
    order = d.sort_values(["sort_key", "company_name"], ascending=[False, True]).account_id.tolist()
    return kpi, hist, reasons, order


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("outputs/html/*_Account_Priority_Dashboard.html"))[-1]
    df = pd.concat([pd.read_csv(f, dtype={"employee_band": str}) for f in ["reference materials/data/accounts.csv", "work/account_priority_dashboard/accounts_extra.csv"]], ignore_index=True)
    df = df.merge(pd.read_csv("work/account_priority_dashboard/account_roles.csv"), on="account_id")
    # apply the Act now bonus independently of prep.py: workbook score + bonus for Act now accounts, capped at 100
    s = {r["key"]: r["value"] for f in ["reference materials/data/scoring_settings.json", "work/account_priority_dashboard/score_adjustments.json"]
         for r in json.load(open(f, encoding="utf-8"))}                  # later file wins (the adjustments)
    # rescore every account independently of prep.py: signals from the raw columns, points rounded to 1 decimal, seat growth for Organic Growth
    settings = [r for f in ["reference materials/data/scoring_settings.json", "work/account_priority_dashboard/score_adjustments.json"] for r in json.load(open(f, encoding="utf-8"))]
    news = {r["label"]: r["value"] for r in settings if r["kind"] == "news"}
    rec = [r["value"] for r in settings if r["kind"] == "recency"]
    seats = pd.read_csv("work/account_priority_dashboard/seat_growth.csv").set_index("account_id").seats_added_6m
    n = df.account_id.map(seats)
    share = pd.Series([np.nan if pd.isna(v) else s["seat_0"] if v <= 0 else s["seat_1_5"] if v <= 5 else s["seat_6_10"] if v <= 10 else s["seat_11"] for v in n], index=df.index, dtype=float)
    og = df.goal == "Organic Growth"
    r1 = lambda v: np.floor(v * 10 + 0.5 + 1e-9) / 10
    est = df.estimated_fields.fillna("")
    age = (pd.Timestamp("2026-11-08") - pd.to_datetime(df.news_signal_date)).dt.days
    rf = age.map(lambda a: 0 if pd.isna(a) else rec[0] if a <= 30 else rec[1] if a <= 90 else rec[2] if a <= 180 else rec[3])
    hire = np.where(df.hiring_spike.eq("Yes"), 1, np.minimum(df.job_postings_30d.fillna(0) / s["jobs_cap"], 1))
    web = np.where(est.str.contains("Website"), s["base_web"], s["tb_share"] * df.team_builder_visit.eq("Yes") + s["ff_share"] * (df.form_fill_30d.fillna(0) > 0) + s["vol_share"] * np.minimum(df.web_visits_30d.fillna(0) / s["vol_cap"], 1))
    nj = np.where(est.str.contains("News"), s["base_news"], s["news_share"] * df.news_signal.map(news).fillna(0) * rf + s["jobs_share"] * hire)
    pts = r1(web * np.where(og, s["web_max_og"], s["web_max_nl"])) + r1(nj * np.where(og, s["news_max_og"], s["news_max_nl"])) \
        + (df.diamond_referral.eq("Yes") & ~og) * s["dia_max"] + (df.prior_bpo_flag.eq("Yes") & ~og) * s["bpo_max"] \
        + np.where(og, r1(share.fillna(s["base_seats"]) * s["seat_max_og"]), 0)
    df["estimated_fields"] = df.estimated_fields.where(~(og & share.isna()), "seat")
    base = r1(pts)
    hot = df.hot_trigger.notna()
    raw = base * df.industry_modifier
    pre = np.floor(raw.clip(upper=100) + 0.5)
    df["assigned_team"] = np.where(og, "AM", np.where(df.diamond_referral.eq("Yes") | hot | (pre >= s["bdm_min"]), "BDM", "SDR"))
    bonus = df.hot_trigger.eq("Diamond referral").map({True: s["hot_bonus_diamond"], False: s["hot_bonus"]}) * hot
    df["priority_score"] = np.floor((raw + bonus).clip(upper=100) + 0.5)
    df["tier"] = pd.cut(df.priority_score, [-1, s["tier2"] - 0.5, s["tier1"] - 0.5, 101], labels=["Tier 3", "Tier 2", "Tier 1"]).astype(str)
    df["sort_key"] = df.priority_score + 1000 * hot
    print(f"Act now bonus +{s['hot_bonus']} applied to {int(hot.sum())} accounts")
    ok = True
    for got in page_numbers(path):
        team, ind, band = got["case"]
        if got.get("missing"):
            print(f"{team:<25} {ind:<12} {band:<8} SKIP (option not on this list)")
            continue
        kpi, hist, reasons, order = expected(df, team, ind, band)
        checks = {"KPIs": got["kpi"] == kpi, "score spread": got["hist"] == hist,
                  "Act now reasons": got["reasons"] == {k: int(v) for k, v in reasons.items()}, "list order": got["order"] == order}
        ok &= all(checks.values())
        print(f"{team:<25} {ind:<12} {band:<8} KPIs {got['kpi']} | " + ", ".join(f"{k}: {'ok' if v else 'MISMATCH'}" for k, v in checks.items()))
        if not checks["KPIs"]:
            print("     expected KPIs", kpi)
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
