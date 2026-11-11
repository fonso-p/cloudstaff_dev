"""Full QA of the client growth dashboard: every file and every number on the page, checked independently.

Part A - files: raw engagement list -> exclusions -> monthly table -> profile -> JSON -> HTML, plus MyStaff tags.
Part B - page: the built dashboard is opened in headless Chrome at several filter settings; every chart, every table,
         every "Numbers behind this chart" panel, the Clients and movement tables, the QA page and the Insights text
         are compared with values recomputed here in pandas (this file does not reuse the page's code or prep.py's logic).
Prints each check with PASS / FAIL and ends with OVERALL. Run from the project root (takes about 10 minutes):
    python work/client_growth_dashboard/qa_full.py
"""
import glob
import html as htmllib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prep  # noqa: E402  (settings only: paths, dates, exclusion code lists)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REGIONS = ["APAC", "AMER", "OPTI"]
STAGES = [(1, 3), (4, 6), (7, 12), (13, 24), (25, 36), (37, None)]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BASE = dict(win=6, thr=5, region="All", division="All", industry="All", status="All", segment="All", year="All")
COMBOS = [dict(BASE), dict(BASE, win=3, thr=3, region="APAC"), dict(BASE, win=12, thr=10, region="AMER", year="2022")]
PAGES = ["overview", "insights", "path", "lifecycle", "buckets", "divisions", "season", "movement", "profile", "clients", "qa"]

RESULTS = []          # (section, check, ok, detail)


def check(section, name, ok, detail=""):
    RESULTS.append((section, name, bool(ok), detail))
    if not ok:
        print(f"  FAIL  [{section}] {name}  {detail}"[:400])


# ---------------------------------------------------------------- helpers
def seg3(h):
    return "0 staff" if h <= 0 else "1-4" if h <= 4 else "5-10" if h <= 10 else "10+"


def bucket4(h):
    return "0" if h <= 0 else "1-2" if h <= 2 else "3-4" if h <= 4 else "5-9" if h <= 9 else "10+"


SEG_ORDER, BK_ORDER = ["0 staff", "1-4", "5-10", "10+"], ["0", "1-2", "3-4", "5-9", "10+"]
SEG_LABEL = {"0 staff": "0 staff", "1-4": "1 to 4 staff", "5-10": "5 to 10 staff", "10+": "More than 10 staff"}


def move(a, b, fn, order):
    i, j = order.index(fn(a)), order.index(fn(b))
    return "up" if j > i else "down" if j < i else "stay"


def med(v):
    v = [x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return float(np.median(v)) if v else None


def mean(v):
    return float(np.mean(v)) if len(v) else None


def wilson(k, n):
    if not n:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d, c = 1 + z * z / n, p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


NUM = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def nums(text):
    return [float(x.replace(",", "").replace("+", "")) for x in NUM.findall(text or "")]


def close(a, b, tol):
    if a is None or b is None or (isinstance(b, float) and math.isnan(b)):
        return a is None or (isinstance(a, float) and math.isnan(a))
    return abs(a - b) <= tol


def cell_ok(text, expected):
    """expected: str (exact text), None ('–'), or list of (value, decimals) compared with rounding tolerance."""
    text = (text or "").strip()
    if isinstance(expected, str):
        return text == expected
    if expected is None:
        return text in ("–", "")
    got = nums(text)
    if len(got) != len(expected):
        return False
    return all(abs(g - v) <= 0.5 * 10 ** -d + 1e-9 for g, (v, d) in zip(got, expected))


def P(v, d=1):       # a percentage as shown on the page
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else [(100 * v, d)]


def N(v, d=0):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else [(v, d)]


def compare_table(section, name, dom, expected_rows, key_cols):
    """dom: [[header...], [cells...], ...]; expected_rows: {key tuple: {col index: expected}}."""
    body = [r for r in dom[1:] if r]
    got = {tuple(r[i] for i in key_cols): r for r in body}
    check(section, f"{name}: row count", len(body) == len(expected_rows), f"page {len(body)} vs expected {len(expected_rows)}")
    bad = []
    for k, cols in expected_rows.items():
        r = got.get(k)
        if r is None:
            bad.append(f"missing row {k}")
            continue
        for ci, exp in cols.items():
            if not cell_ok(r[ci], exp):
                bad.append(f"{k} col {dom[0][ci] if ci < len(dom[0]) else ci}: page '{r[ci]}' vs {exp}")
    check(section, f"{name}: every cell", not bad, "; ".join(bad[:6]) + (f" (+{len(bad) - 6} more)" if len(bad) > 6 else ""))


# ---------------------------------------------------------------- independent model of the clients (from the monthly CSV)
class Model:
    def __init__(self, mon, prof, extract, last_month):
        self.prof = prof.set_index("shortcode")
        self.first = pd.Period(mon["month"].min(), "M")
        self.last = last_month
        self.last_full = last_month.year if last_month.month == 12 else last_month.year - 1
        self.C = {}
        for sc, g in mon.sort_values(["shortcode", "months_since_start"]).groupby("shortcode", sort=False):
            p = self.prof.loc[sc]
            st, ch, act = g["starts"].tolist(), g["churned"].tolist(), g["active_month_end"].tolist()
            m0 = pd.Period(g["month"].iat[0], "M")
            self.C[sc] = dict(sc=sc, st=st, ch=ch, act=act, n=len(act), m0=m0, p=p,
                              aged12=(extract - pd.Timestamp(p["start_date"])).days >= 365)

    def month(self, c, i):
        return c["m0"] + i

    def clients(self, f):
        out = []
        for c in self.C.values():
            p = c["p"]
            if f["region"] != "All" and p["region"] != f["region"]:
                continue
            if f["division"] != "All" and p["custom_division"] != f["division"]:
                continue
            if f["industry"] != "All" and p["industry_rollup"] != f["industry"]:
                continue
            if f["status"] != "All" and p["status"] != f["status"]:
                continue
            out.append(c)
        return out

    def windows(self, cl, f):
        N_, W = f["win"], []
        for c in cl:
            for k in range(1, c["n"] // N_ + 1):
                a, b = (k - 1) * N_, k * N_ - 1
                s_hc = c["act"][0] if k == 1 else c["act"][a - 1]
                frm = 1 if k == 1 else a
                w = dict(c=c, k=k, year=self.month(c, a).year, startHC=s_hc, endHC=c["act"][b], net=c["act"][b] - s_hc,
                         starts=sum(c["st"][frm:b + 1]), churn=sum(c["ch"][frm:b + 1]))
                if f["segment"] != "All" and seg3(s_hc) != f["segment"]:
                    continue
                if f["year"] != "All" and w["year"] != int(f["year"]):
                    continue
                w["hit"] = w["net"] >= f["thr"]
                W.append(w)
        return W

    @staticmethod
    def stage(c, a, b):
        if c["n"] < (b if b else a):
            return None
        end = b if b else c["n"]
        prev = c["act"][0] if a == 1 else c["act"][a - 2]
        return dict(net=c["act"][end - 1] - prev, months=end - a + 1)

    def stage_stats(self, cl, a, b):
        v = [x for x in (self.stage(c, a, b) for c in cl) if x]
        nets = [x["net"] / x["months"] if b is None else x["net"] for x in v]
        n = len(v)
        return dict(n=n, grow=sum(x["net"] > 0 for x in v) / (n or 1), shrink=sum(x["net"] < 0 for x in v) / (n or 1),
                    avg=mean(nets), med=med(nets), total=sum(x["net"] for x in v))

    def season(self, cl, year, skip, measure):
        tot = [0] * 12
        for c in cl:
            for i in range(skip, c["n"]):
                m = self.month(c, i)
                if (m.year != int(year)) if year != "All" else (m.year > self.last_full):
                    continue
                v = c["st"][i] if measure == "starts" else c["ch"][i] if measure == "churn" else c["st"][i] - c["ch"][i]
                tot[m.month - 1] += v
        return tot

    def months_in(self, year):
        return 12 if (year == "All" or int(year) <= self.last_full) else self.last.month


def gof(obs, exp):
    keep = [i for i, e in enumerate(exp) if e > 0]
    o, x = [obs[i] for i in keep], [exp[i] for i in keep]
    so, se = sum(o), sum(x)
    if not so or not se or len(keep) < 2:
        return None
    stat = sum((v - e * so / se) ** 2 / (e * so / se) for v, e in zip(o, x))
    return float(stats.chi2.sf(stat, len(keep) - 1))


# ---------------------------------------------------------------- page probe (headless Chrome)
def probe(html_path):
    html = open(html_path, encoding="utf-8").read()
    js = """<script>window.addEventListener('load', () => setTimeout(() => {
  const OUT = [], set = (id, v) => { document.getElementById(id).value = String(v); };
  const grab = sec => { const ch = {}, tb = {}, det = {};
    sec.querySelectorAll('canvas').forEach(cv => { const c = charts[cv.id]; if (c) ch[cv.id] = {labels: c.data.labels, sets: c.data.datasets.map(d => ({label: d.label, data: d.data}))};
      const d = cv.closest('.card-body').querySelector('details.chart-data'); if (d) det[cv.id] = [...d.querySelectorAll('tr')].map(tr => [...tr.children].map(td => td.textContent.trim())); });
    sec.querySelectorAll('.tbl-wrap[id]').forEach(t => { tb[t.id] = [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(td => td.textContent.trim())); });
    return {ch, tb, det, kpi: [...sec.querySelectorAll('.kpi')].map(k => [...k.children].map(x => x.textContent.trim()).join(' | ')),
      ins: [...sec.querySelectorAll('.ins')].map(k => k.textContent.replace(/\\s+/g, ' ').trim())}; };
  for (const F of __COMBOS__) {
    set('fWin', F.win); set('fThr', F.thr); set('fReg', F.region); set('fDiv', F.division); set('fInd', F.industry); set('fSta', F.status); set('fSeg', F.segment); set('fYear', F.year);
    const R = {};
    for (const p of __PAGES__) { go(p); R[p] = grab(document.getElementById('p-' + p)); }
    go('overview'); R.move = moveRows(filt(), current.clients, current.W);   // a page that applies every window setting
    R.filt = filt();
    OUT.push(R);
  }
  const pre = document.createElement('pre'); pre.id = '__qa'; pre.textContent = JSON.stringify(OUT); document.body.appendChild(pre);
}, 1500));</script></body>""".replace("__COMBOS__", json.dumps(COMBOS)).replace("__PAGES__", json.dumps(PAGES))
    html = html.replace("</body>", js, 1)
    tmp = os.path.join(tempfile.mkdtemp(), "qa.html")
    open(tmp, "w", encoding="utf-8").write(html)
    args = [CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=120000", "--window-size=1440,1000", "--dump-dom", "file://" + tmp]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=300).stdout
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        subprocess.run(["pkill", "-f", tmp])
    m = re.search(r'<pre id="__qa">(.*?)</pre>', out, re.S)
    if not m:
        sys.exit("Page probe returned no result")
    txt = htmllib.unescape(m.group(1))                     # the DOM dump escapes &, <, >, quotes and non-breaking spaces
    return json.loads(txt)


# ================================================================ PART A: files
def part_a():
    print("\n== A. Files: raw data, exclusions, monthly table, profile, JSON, HTML, MyStaff")
    S = "A"
    raw = pd.read_excel(prep.STAFF_SRC, dtype=object)
    raw["sc"] = raw["Shortcode"].map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip())
    raw["ed"] = pd.to_datetime(raw["Engagement Date"], errors="coerce")
    raw["dd"] = pd.to_datetime(raw["Disengagement Date"], errors="coerce")
    mon = pd.read_csv("data/client_monthly.csv", keep_default_na=False, na_values=[""])
    prof = pd.read_csv("data/client_profile.csv", keep_default_na=False, na_values=[""])
    ref = pd.read_csv("data/client_reference.csv", keep_default_na=False, na_values=[""], dtype={"shortcode": str})
    exl = pd.read_csv("data/qa_excluded.csv", keep_default_na=False, na_values=[""], dtype={"shortcode": str})
    flg = pd.read_csv("data/qa_flags.csv", keep_default_na=False, na_values=[""], dtype={"sc": str})
    dif = pd.read_csv("data/qa_mystaff_differences.csv", keep_default_na=False, na_values=[""])
    nmp = pd.read_csv("data/qa_name_pairs.csv", keep_default_na=False, na_values=[""], dtype={"shortcode": str})
    J = json.load(open("data/client_monthly.json"))
    q = J["qa"]
    html_path = sorted(glob.glob("outputs/html/*_Client_Growth_Dashboard.html"))[-1]
    html = open(html_path, encoding="utf-8").read()
    emb = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    insc = set(prof["shortcode"])

    # A1 row tie-out
    check(S, "source rows = JSON source_rows", len(raw) == q["source_rows"], f"{len(raw)} vs {q['source_rows']}")
    check(S, "used + excluded rows = source rows", q["included_rows"] + int(exl["rows"].sum()) == len(raw), f"{q['included_rows']} + {int(exl['rows'].sum())} vs {len(raw)}")
    check(S, "excluded rows by reason: CSV = JSON", exl.groupby("reason")["rows"].sum().to_dict() == {k: int(v) for k, v in q["excluded"].items()})
    check(S, "excluded list: CSV = JSON (every row)", len(exl) == len(q["excluded_lists"]) and
          set(zip(exl["reason"], exl["shortcode"].fillna(""), exl["rows"])) == {(r["reason"], r["shortcode"] or "", r["rows"]) for r in q["excluded_lists"]})
    # every raw row: in scope or excluded; per shortcode rows add up
    per_sc = raw.groupby("sc").size()
    dup = raw.drop(columns=["sc", "ed", "dd"]).astype(str).duplicated(keep="first")
    ins_rows = int(raw["sc"].isin(insc).sum()) - int((dup & raw["sc"].isin(insc)).sum())
    check(S, "rows of in-scope clients (less exact duplicates) = used rows", ins_rows == q["included_rows"], f"{ins_rows} vs {q['included_rows']}")
    exl_sc = exl.assign(shortcode=exl["shortcode"].fillna("")).groupby("shortcode")["rows"].sum()   # blank shortcode rows are listed as ''
    bad = [sc for sc, n in per_sc.items() if (sc not in insc) and exl_sc.get(sc, 0) != n]
    check(S, "every out-of-scope shortcode has all its rows in the excluded list", not bad, f"{len(bad)} shortcodes, e.g. {bad[:5]}")
    both = set(exl.loc[~exl["reason"].eq("Exact duplicate row"), "shortcode"]) & insc
    check(S, "no in-scope client is also listed as excluded (other than duplicate rows)", not both, str(sorted(both)[:5]))

    # A2 independent re-derivation of the exclusion rules (from the README definitions)
    ms = pd.read_excel(prep.CLIENT_SRC, sheet_name=prep.CLIENT_SHEET, dtype=str,
                       usecols=["Shortcode", "Client", "Region", "Custom_Division (Hubspot)", "Industry Roll Up", "Industry Hubspot", "Active",
                                "Internal (Yes / No)", "Total Staff", "Date of First Staff Engagement"])
    ms["sc"] = ms["Shortcode"].fillna("").str.strip()
    ms = ms[ms["sc"].ne("")].drop_duplicates("sc").set_index("sc").fillna("")
    for col in ms.columns:
        ms[col] = ms[col].astype(str).str.strip()
    name = raw.groupby("sc")["Client Name"].first().fillna("").astype(str).str.strip()
    hub = raw["Category"].eq("Hub").groupby(raw["sc"]).mean()

    def reason(sc):
        nm = name.get(sc, "")
        if sc == "":
            return "Blank shortcode"
        if sc == "CSTREENGAGE":
            return "CSTREENGAGE"
        if sc.startswith("CSS") and not nm.upper().startswith("CS ") and per_sc[sc] == 1:
            return "CSS test"
        if sc in prep.NAMED_INTERNAL or re.match(r"(?i)^(CS |CSDEVS|Ojt )", nm) or re.search(r"(?i)cloudstaff|ready ?to ?go", nm):
            return "Internal name"
        if hub.get(sc, 0) >= 0.5:
            return "Hub"
        if sc in ms.index:
            r = ms.loc[sc]
            ind = r["Industry Roll Up"] if r["Industry Roll Up"] not in ("", "-", "0") else r["Industry Hubspot"]
            if r["Internal (Yes / No)"] == "Yes":
                return "Internal = Yes"
            if r["Region"].upper() in prep.EXCL_REGION:
                return "Region"
            if r["Custom_Division (Hubspot)"].upper() in prep.EXCL_DIVISION:
                return "Division"
            if ind.upper().startswith(("CLOUDSTAFF", "TEST RECORD")):
                return "Industry"
        return ""
    valid = raw["ed"].notna() & (raw["dd"].isna() | (raw["dd"] >= raw["ed"]))
    r1 = {sc: reason(sc) for sc in per_sc.index}
    cand = [sc for sc, rr in r1.items() if rr == ""]
    first = raw[valid & raw["sc"].isin(cand) & ~dup].groupby("sc")["ed"].min()
    expected_in = {sc for sc in cand if sc in first.index and first[sc] >= pd.Timestamp(prep.COHORT_FROM.start_time)}
    check(S, "in-scope clients re-derived from the rules = profile clients", expected_in == insc,
          f"only in rules: {sorted(expected_in - insc)[:5]}; only in profile: {sorted(insc - expected_in)[:5]}")

    # A3 monthly table recounted from raw for every in-scope client
    st = raw[raw["sc"].isin(insc) & ~dup & valid]
    exp_rows = []
    for sc, g in st.groupby("sc"):
        ed, dd = g["ed"], g["dd"]
        for m in pd.period_range(ed.min().to_period("M"), prep.LAST_MONTH, freq="M"):
            me = m.to_timestamp(how="end").normalize()
            exp_rows.append((sc, str(m), int((ed.dt.to_period("M") == m).sum()), int((dd.dt.to_period("M") == m).sum()),
                             int(((ed <= me) & (dd.isna() | (dd > me))).sum())))
    e = pd.DataFrame(exp_rows, columns=["shortcode", "month", "starts", "churned", "active_month_end"])
    mm = mon.merge(e, on=["shortcode", "month"], how="outer", suffixes=("", "_raw"), indicator=True)
    diff = mm[(mm["_merge"] != "both") | (mm["starts"] != mm["starts_raw"]) | (mm["churned"] != mm["churned_raw"]) | (mm["active_month_end"] != mm["active_month_end_raw"])]
    check(S, f"monthly table = raw recount ({len(e):,} client-months)", diff.empty, f"{len(diff)} differences, e.g. {diff.head(3).to_dict('records')}")
    check(S, "monthly net_seats = starts - churned", (mon["net_seats"] == mon["starts"] - mon["churned"]).all())
    check(S, "monthly months_since_start runs 1..n with no gaps", mon.groupby("shortcode")["months_since_start"].apply(lambda s: list(s) == list(range(1, len(s) + 1))).all())

    # A4 profile vs monthly table
    g = mon.groupby("shortcode")
    pp = prof.set_index("shortcode")
    tests = {
        "total_starts": g["starts"].sum(), "total_churned": g["churned"].sum(), "net_seats": g["net_seats"].sum(),
        "current_seats": g["active_month_end"].last(), "starting_seats": g["active_month_end"].first(), "months_observed": g.size(),
        "months_active": mon[mon["active_month_end"] > 0].groupby("shortcode").size().reindex(pp.index, fill_value=0),
        "start_month": g["month"].first()}
    for col, ser in tests.items():
        d = (pp[col] != ser.reindex(pp.index))
        check(S, f"profile {col} = monthly table", not d.any(), f"{int(d.sum())} clients, e.g. {list(pp.index[d][:3])}")
    pk = mon.loc[mon.groupby("shortcode")["net_seats"].idxmax()].set_index("shortcode")
    check(S, "profile peak net month / value = monthly table", ((pp["peak_net_month"] == pk["month"].reindex(pp.index)) & (pp["peak_net_value"] == pk["net_seats"].reindex(pp.index))).all())
    check(S, "profile retained = current seats > 0", (pp["retained"].eq("Retained") == (pp["current_seats"] > 0)).all())
    stat = np.select([(pp["active_flag"] == "Yes") & (pp["current_seats"] > 0), (pp["active_flag"] == "Yes") & (pp["current_seats"] == 0), pp["active_flag"] == "No"],
                     ["Active with staff", "Active, 0 staff", "Inactive"], "Unknown flag")
    check(S, "profile status follows the agreed rule", (pp["status"] == stat).all())
    check(S, "profile peak seats (any day) >= highest month-end staff", (pp["peak_seats"] >= g["active_month_end"].max().reindex(pp.index)).all())
    check(S, "months to 5 set only when peak >= 5", ((pp["months_to_5"].notna()) == (pp["peak_seats"] >= 5)).all())
    check(S, "months to 10 set only when peak >= 10", ((pp["months_to_10"].notna()) == (pp["peak_seats"] >= 10)).all())

    # A5 tags: profile = reference = monthly CSV = MyStaff (independent derivation)
    rf = ref.set_index("shortcode")
    for col in ["region", "brand", "custom_division", "industry_rollup", "active_flag"]:
        d = pp[col] != rf[col].reindex(pp.index)
        check(S, f"profile {col} = client_reference", not d.any(), f"{int(d.sum())} differ")
        dm = mon.merge(pp[[col]], left_on="shortcode", right_index=True, suffixes=("", "_p"))
        check(S, f"monthly CSV {col} = profile", (dm[col] == dm[col + "_p"]).all())

    def my_region(r):
        reg = {"EMEA": "AMER"}.get(r["Region"].upper(), r["Region"].upper())
        if reg == "OPTI" or r["Custom_Division (Hubspot)"].upper() in prep.OPTI_DIVISIONS:
            reg = "OPTI"
        return reg or "Unknown"

    def my_div(r, reg):
        d = r["Custom_Division (Hubspot)"]
        return f"Unassigned ({reg})" if d in ("", "-") or d.upper() in ("APAC", "AMER", "EMEA") else d

    def my_ind(r):
        i = r["Industry Roll Up"]
        if i in ("", "-", "0"):
            i = r["Industry Hubspot"]
            i = "" if i in ("-", "0") else i
        return i or "Unknown"
    bad = defaultdict(list)
    for sc in pp.index:
        if sc not in ms.index:
            bad["not in MyStaff"].append(sc)
            continue
        r = ms.loc[sc]
        reg = my_region(r)
        if pp.at[sc, "region"] != reg:
            bad["region"].append(sc)
        if pp.at[sc, "custom_division"] != my_div(r, reg):
            bad["division"].append(sc)
        if pp.at[sc, "industry_rollup"] != my_ind(r):
            bad["industry"].append(sc)
        if pp.at[sc, "active_flag"] != (r["Active"] if r["Active"] in ("Yes", "No") else "Unknown"):
            bad["active"].append(sc)
    for k in ["region", "division", "industry", "active"]:
        check(S, f"{k} re-derived from MyStaff (2) for every client", not bad[k], f"{len(bad[k])} differ, e.g. {bad[k][:5]}")
    check(S, "clients not in MyStaff are listed on the QA page", sorted(bad["not in MyStaff"]) == sorted(q["not_in_mystaff_kept"]))

    # A6 MyStaff differences recomputed
    v2 = raw[raw["sc"].isin(insc) & ~dup & valid]
    eng = v2[(v2["ed"] <= prep.EXTRACT) & (v2["dd"].isna() | (v2["dd"] >= prep.EXTRACT))].groupby("sc").size().reindex(pp.index, fill_value=0)
    mys = pd.to_numeric(ms["Total Staff"].reindex(pp.index), errors="coerce")
    sdiff = (mys - eng).fillna(0)
    fm = pd.to_datetime(ms["Date of First Staff Engagement"].reindex(pp.index), errors="coerce").dt.to_period("M").astype(str)
    smd = (fm != pp["start_month"]) & ms["Date of First Staff Engagement"].reindex(pp.index).ne("")
    exp_codes = set(pp.index[(sdiff != 0) | smd])
    check(S, "MyStaff differences file = recomputed (staff count and start month)", exp_codes == set(dif["shortcode"]),
          f"only recomputed: {sorted(exp_codes - set(dif['shortcode']))[:5]}; only in file: {sorted(set(dif['shortcode']) - exp_codes)[:5]}")
    check(S, "MyStaff difference counts in JSON", q["mystaff_differences"]["staff_count_differs"] == int((sdiff != 0).sum()) and q["mystaff_differences"]["start_month_differs"] == int(smd.sum()),
          f"{q['mystaff_differences']} vs {int((sdiff != 0).sum())}, {int(smd.sum())}")
    d2 = dif.set_index("shortcode")
    check(S, "MyStaff difference values (staff, diff) = recomputed", all(int(d2.at[sc, "engagement_list_staff"]) == eng[sc] and
          (pd.isna(d2.at[sc, "staff_diff"]) or int(d2.at[sc, "staff_diff"]) == int(sdiff[sc])) for sc in d2.index))

    # A7 never staffed
    no_valid = set(q["never_staffed_mystaff_clients"].get("no_valid_stint", []))
    ns = ms[(~ms.index.isin(set(raw["sc"])) | ms.index.isin(no_valid)) & ms["Internal (Yes / No)"].ne("Yes") & ~ms["Region"].str.upper().isin(prep.EXCL_REGION)]
    check(S, "never-staffed MyStaff clients recomputed", len(ns) == q["never_staffed_mystaff_clients"]["total"] and int((ns["Active"] == "Yes").sum()) == q["never_staffed_mystaff_clients"]["active_yes"],
          f"{len(ns)} / {int((ns['Active'] == 'Yes').sum())} vs {q['never_staffed_mystaff_clients']}")

    # A8 flags recomputed from raw
    fl = {
        "Disengagement Date before Engagement Date (not counted as seat/churn)": int((raw["ed"].notna() & raw["dd"].notna() & (raw["dd"] < raw["ed"])).sum()),
        "Engagement Date after extract date": int((raw["ed"] > prep.EXTRACT).sum()),
        "Status disengage but no Disengagement Date (treated as active)": int((raw["dd"].isna() & raw["Engagement Status"].eq("disengage")).sum()),
        "Engagement Status bench (dates used as given)": int(raw["Engagement Status"].eq("bench").sum())}
    for k, v in fl.items():
        check(S, f"flag count = raw: {k[:45]}", int((flg["flag"] == k).sum()) == v, f"{int((flg['flag'] == k).sum())} vs {v}")
    check(S, "flags CSV = JSON flag counts", {f"{a} | in scope: {b}": int(n) for (a, b), n in flg.groupby(["flag", "in_scope"]).size().items()} == q["flags"])
    check(S, "flag rows: CSV = JSON", len(flg) == len(q["flag_rows"]))
    check(S, "flag in_scope matches the client list", (flg["in_scope"] == flg["sc"].isin(insc)).all())

    # A8b path to 5 seats: first day with 5 / 10 staff at the same time, peak, group (own day-by-day sweep; a stint counts on its start and end days)
    bad = defaultdict(list)
    for sc, gg in st.groupby("sc"):
        ev = pd.concat([pd.Series(1, index=gg["ed"]), pd.Series(-1, index=gg["dd"].dropna() + pd.Timedelta(days=1))]).groupby(level=0).sum().sort_index().cumsum()
        d5 = ev[ev >= 5].index.min() if (ev >= 5).any() else None
        d10 = ev[ev >= 10].index.min() if (ev >= 10).any() else None
        r = pp.loc[sc]
        start = gg["ed"].min()
        if int(ev.max()) != r["peak_seats"]:
            bad["peak"].append(sc)
        if (d5.strftime("%Y-%m-%d") if d5 is not None else None) != (r["date_5"] if pd.notna(r["date_5"]) else None):
            bad["date_5"].append(sc)
        if (d10.strftime("%Y-%m-%d") if d10 is not None else None) != (r["date_10"] if pd.notna(r["date_10"]) else None):
            bad["date_10"].append(sc)
        days = (d5 - start).days if d5 is not None else None
        if (days is None and pd.notna(r["days_to_5"])) or (days is not None and days != r["days_to_5"]):
            bad["days_to_5"].append(sc)
        grp = ("Fast to 5 (within 6 months)" if days <= 183 else "Slow to 5 (after 6 months)") if days is not None else \
              ("Not yet at 5, still active" if r["current_seats"] > 0 else "Churned without reaching 5")
        if grp != r["path_group"]:
            bad["group"].append(sc)
    for k in ["peak", "date_5", "date_10", "days_to_5", "group"]:
        check(S, f"path to 5: {k} re-derived from raw stints for every client", not bad[k], f"{len(bad[k])} differ, e.g. {bad[k][:5]}")
    # A8c staff on the books on the extract date: every active stint lands in exactly one row of the reconciliation
    on = raw[(raw["ed"] <= prep.EXTRACT) & (raw["dd"].isna() | (raw["dd"] >= prep.EXTRACT))]
    rec = pd.DataFrame(q["active_reconciliation"])
    check(S, "headcount reconciliation total = active stints on the extract date", int(rec["Total"].sum()) == len(on), f"{int(rec['Total'].sum())} vs {len(on)}")
    ind = rec[rec["where"].str.startswith("In the dashboard")]
    on_in = on[on["sc"].isin(insc) & ~dup.reindex(on.index)]
    check(S, "reconciliation: staff in the dashboard = in-scope active stints", int(ind["Total"].sum()) == len(on_in), f"{int(ind['Total'].sum())} vs {len(on_in)}")
    for cat in [c for c in rec.columns if c not in ("where", "Total")]:
        check(S, f"reconciliation: category {cat} total", int(rec[cat].sum()) == int(on["Category"].fillna("Blank").eq(cat).sum()))

    # A9 name pairs, JSON clients, embedded data
    check(S, "name pairs: CSV = JSON", len(nmp) == len(q["name_pairs"]))
    jc = {c["shortcode"]: c for c in J["clients"]}
    check(S, "JSON clients = profile clients", set(jc) == insc)
    arr_ok = all(jc[sc]["starts"] == gg["starts"].tolist() and jc[sc]["churn"] == gg["churned"].tolist() for sc, gg in mon.sort_values(["shortcode", "months_since_start"]).groupby("shortcode"))
    check(S, "JSON month arrays = monthly CSV (every client, every month)", arr_ok)
    bad = []
    for _, r in prof.iterrows():
        c = jc[r["shortcode"]]
        for col in prof.columns:
            v = r[col]
            jv = c.get(col)
            if (pd.isna(v) and jv is not None) or (not pd.isna(v) and (str(jv)[:10] != str(v)[:10] if isinstance(v, str) else abs(float(jv) - float(v)) > 1e-9)):
                bad.append((r["shortcode"], col, v, jv))
    check(S, "JSON client fields = profile CSV (every field)", not bad, str(bad[:3]))
    check(S, "data embedded in the HTML = data/client_monthly.json", emb == J)
    return J, mon, prof


# ================================================================ PART B: page
def part_b(J, mon, prof):
    print("\n== B. Page: every chart, table and text vs independent recomputation")
    html_path = sorted(glob.glob("outputs/html/*_Client_Growth_Dashboard.html"))[-1]
    pages = probe(html_path)
    M = Model(mon, prof, pd.Timestamp(J["extract"]), pd.Period(J["last_month"], "M"))
    q = J["qa"]
    for ci, (F, R) in enumerate(zip(COMBOS, pages)):
        S = f"B{ci + 1}"
        print(f"  -- filters {S}: {F}")
        check(S, "filters applied on the page", all(str(R["filt"][k]) == str(v) for k, v in F.items()), str(R["filt"]))
        cl = M.clients(F)
        W = M.windows(cl, F)
        byc = defaultdict(list)
        for w in W:
            byc[w["c"]["sc"]].append(w)
        hitters = sum(any(w["hit"] for w in ws) for ws in byc.values())

        # every "Numbers behind this chart" panel = its chart
        for pg, Rp in R.items():
            if not isinstance(Rp, dict) or "ch" not in Rp:
                continue
            for cid, chd in Rp["ch"].items():
                det = Rp["det"].get(cid)
                ok = det is not None and len(det) - 1 == len(chd["labels"])
                if ok:
                    is_pct = any(h.endswith("(%)") for h in det[0])
                    for i, lab in enumerate(chd["labels"]):
                        for j, ds in enumerate(chd["sets"]):
                            v = ds["data"][i]
                            exp = None if v is None else [((100 * v) if is_pct else v, 1 if is_pct else (0 if float(v).is_integer() else 2))]
                            ok &= cell_ok(det[i + 1][j + 1], exp)
                check(S, f"{pg}/{cid}: numbers panel = chart values", ok)

        # ---- Overview
        ov = R["overview"]
        kt = " | ".join(ov["kpi"])
        lo, hi = wilson(hitters, len(byc))
        exp_k = [hitters, len(byc), sum(w["net"] for w in W), sum(w["starts"] for w in W), sum(w["churn"] for w in W),
                 sum(int(c["p"]["current_seats"]) for c in cl), sum(c["p"]["status"] == "Active, 0 staff" for c in cl)]
        got = [nums(t) for t in ov["kpi"]]
        ok = (got[0][0] == exp_k[0] and close(got[1][0], 100 * hitters / len(byc), 0.05) and got[1][1] == exp_k[1] and close(got[1][3], 100 * lo, 0.05) and close(got[1][4], 100 * hi, 0.05)
              and got[2][0] == exp_k[2] and got[2][1] == exp_k[3] and got[3][0] == exp_k[4] and got[4][0] == exp_k[5] and got[5][1] == exp_k[6])
        check(S, "overview KPI tiles", ok, f"page {kt} vs {exp_k}")
        cw = ov["ch"]["cWin"]
        K = min(12, max([1] + [w["k"] for w in W]))
        exp = {r: [sum(1 for w in W if w["k"] == kk and w["hit"] and w["c"]["p"]["region"] == r) for kk in range(1, K + 1)] for r in REGIONS}
        check(S, "overview hits by window by region", {d["label"]: d["data"] for d in cw["sets"]} == exp and len(cw["labels"]) == K)
        yrs = list(range(M.first.year, M.last.year + 1))
        exp = {r: [sum(c["st"][i] - c["ch"][i] for c in cl if c["p"]["region"] == r for i in range(c["n"]) if M.month(c, i).year == y) for y in yrs] for r in REGIONS}
        check(S, "overview net seats by calendar year by region", {d["label"]: d["data"] for d in ov["ch"]["cYear"]["sets"]} == exp)

        # ---- Lifecycle
        lf = R["lifecycle"]
        labs = ["Months 1-3 (after launch)", "Months 4-6", "Months 7-12", "Months 13-24", "Months 25-36", "Months 37+"]
        exp = {r: [M.stage_stats([c for c in cl if c["p"]["region"] == r], a, b)["grow"] for a, b in STAGES] for r in REGIONS}
        got = {d["label"]: d["data"] for d in lf["ch"]["cLife"]["sets"]}
        check(S, "lifecycle % growing by stage and region", all(close(g, e, 1e-9) for r in REGIONS for g, e in zip(got[r], exp[r])))
        al = [M.stage_stats(cl, a, b) for a, b in STAGES]
        got = {d["label"]: d["data"] for d in lf["ch"]["cLife2"]["sets"]}
        check(S, "lifecycle average and median by stage", all(close(got["Average"][i], al[i]["avg"], 1e-9) and close(got["Median"][i], al[i]["med"], 1e-9) for i in range(6)))
        rows = {}
        for r in ["All"] + REGIONS:
            sub = cl if r == "All" else [c for c in cl if c["p"]["region"] == r]
            for (a, b), lab in zip(STAGES, labs):
                s = M.stage_stats(sub, a, b)
                rows[(r, lab)] = {2: N(s["n"]), 3: P(s["grow"]), 4: P(s["shrink"]), 5: N(s["avg"], 2), 6: N(s["med"], 1), 7: N(s["total"])}
        compare_table(S, "lifecycle detail table", lf["tb"]["tLife"], rows, [0, 1])
        divs = defaultdict(list)
        for c in cl:
            divs[c["p"]["custom_division"]].append(c)
        rows = {}
        for d, cc in divs.items():
            if len(cc) < 20:
                continue
            row = {1: N(len(cc))}
            for i, (a, b) in enumerate(STAGES):
                s = M.stage_stats(cc, a, b)
                row[2 + i] = None if s["n"] < 10 else [(s["avg"], 2), (100 * s["grow"], 0), (s["n"], 0)]
            rows[(d,)] = row
        compare_table(S, "lifecycle by division table", lf["tb"]["tLifeDiv"], rows, [0])

        # ---- Size buckets
        bk = R["buckets"]
        Wb = [w for w in W if w["startHC"] > 0]
        exp_avg, exp_med, mv = [], [], {"up": [], "stay": [], "down": []}
        for b in BK_ORDER[1:]:
            ws = [w for w in Wb if bucket4(w["startHC"]) == b]
            exp_avg.append(mean([w["net"] for w in ws]))
            exp_med.append(med([w["net"] for w in ws]))
            for d in mv:
                mv[d].append(sum(move(w["startHC"], w["endHC"], bucket4, BK_ORDER) == d for w in ws) / (len(ws) or 1))
        g1 = {d["label"]: d["data"] for d in bk["ch"]["cBk"]["sets"]}
        g2 = {d["label"]: d["data"] for d in bk["ch"]["cBk2"]["sets"]}
        check(S, "size buckets average / median chart", all(close(g1["Average net"][i], exp_avg[i], 1e-9) and close(g1["Median net"][i], exp_med[i], 1e-9) for i in range(4)))
        check(S, "size buckets up / stayed / down chart", all(close(g2[lab][i], mv[d][i], 1e-9) for lab, d in [("Moved up", "up"), ("Stayed", "stay"), ("Moved down", "down")] for i in range(4)))
        rows = {}
        for r in ["All"] + REGIONS:
            for b in BK_ORDER[1:]:
                ws = [w for w in Wb if bucket4(w["startHC"]) == b and (r == "All" or w["c"]["p"]["region"] == r)]
                n = len(ws) or 1
                cnt = {d: sum(move(w["startHC"], w["endHC"], bucket4, BK_ORDER) == d for w in ws) for d in ["up", "stay", "down"]}
                rows[(r, b)] = {2: N(len(ws)), 3: N(len({w["c"]["sc"] for w in ws})), 4: N(mean([w["net"] for w in ws]), 2), 5: N(med([w["net"] for w in ws]), 1),
                                6: P(sum(w["net"] > 0 for w in ws) / n), 7: P(sum(w["net"] < 0 for w in ws) / n), 8: P(sum(w["hit"] for w in ws) / n),
                                9: [(100 * cnt["up"] / n, 1), (cnt["up"], 0)], 10: [(100 * cnt["stay"] / n, 1), (cnt["stay"], 0)], 11: [(100 * cnt["down"] / n, 1), (cnt["down"], 0)]}
        compare_table(S, "size bucket detail table", bk["tb"]["tBk"], rows, [0, 1])

        # ---- Divisions and industry
        dv = R["divisions"]
        for key, cid, tid in [("custom_division", "cDiv", "tDiv"), ("industry_rollup", "cInd", "tInd")]:
            grp = defaultdict(list)
            for w in W:
                grp[w["c"]["p"][key]].append(w)
            rows, vals = {}, {}
            for kk, ws in grp.items():
                ccs = defaultdict(list)
                for w in ws:
                    ccs[w["c"]["sc"]].append(w)
                hc = sum(any(x["hit"] for x in v) for v in ccs.values())
                lo, hi = wilson(hc, len(ccs))
                rows[(kk,)] = {1: N(len(ccs)), 2: N(len(ws)), 3: P(hc / len(ccs)), 4: [(100 * lo, 1), (100 * hi, 1)], 5: P(sum(x["hit"] for x in ws) / len(ws)),
                               6: N(mean([x["net"] for x in ws]), 2), 7: N(med([x["net"] for x in ws]), 1), 8: N(sum(x["net"] for x in ws)), 9: N(sum(x["churn"] for x in ws))}
                vals[f"{kk} ({len(ccs)})"] = (hc / len(ccs), len(ccs) < 20)
            compare_table(S, f"{tid} detail table", dv["tb"][tid], rows, [0])
            ch = dv["ch"][cid]
            ok = len(ch["labels"]) == min(30, len(vals)) and all(lab in vals and close(v, vals[lab][0], 1e-9) for lab, v in zip(ch["labels"], ch["sets"][0]["data"]))
            exp_seq = sorted(vals.values(), key=lambda v: (v[1], -v[0]))[:30]           # 20+ groups first, then by rate, top 30
            got_seq = [vals[lab] for lab in ch["labels"] if lab in vals]
            ok &= len(got_seq) == len(exp_seq) and all(a[1] == b[1] and close(a[0], b[0], 1e-9) for a, b in zip(got_seq, exp_seq))
            check(S, f"{cid} chart: values, order and top-30 selection", ok)

        # ---- Seasonality (page defaults: skip first 3 months, measure starts)
        se = R["season"]
        Sst, Sch, Snt = (M.season(cl, F["year"], 3, m) for m in ("starts", "churn", "net"))
        got = {d["label"]: d["data"] for d in se["ch"]["cSeason"]["sets"]}
        check(S, "seasonality starts / churn / net by month", got["Starts"] == Sst and got["Churn"] == Sch and got["Net seats"] == Snt)
        bt = sum(Sst)

        def index(arr):
            t = sum(arr)
            return [(v / t) / (Sst[i] / bt) if t and bt and Sst[i] else None for i, v in enumerate(arr)]
        got = {d["label"]: d["data"] for d in se["ch"]["cSeasonReg"]["sets"]}
        ok = all(close(g, e, 1e-9) if e is not None else g is None for r in REGIONS for g, e in zip(got[r], index(M.season([c for c in cl if c["p"]["region"] == r], F["year"], 3, "starts"))))
        check(S, "seasonal index by region", ok)
        rows = {}
        for d, cc in divs.items():
            arr = M.season(cc, F["year"], 3, "starts")
            if sum(abs(x) for x in arr) < 40:
                continue
            p = gof(arr, Sst)
            idx = index(arr)
            pk = MONTHS[arr.index(max(arr))]
            ptxt = "–" if p is None else ("< 0.0001" if p < 0.0001 else f"{p:.4f}")
            row = {1: N(len(cc)), 2: N(sum(arr)), 15: pk}
            for i in range(12):
                row[3 + i] = None if idx[i] is None else N(idx[i], 2)
            row[16] = None if p is None else (ptxt if p < 0.0001 else [(p, 4)])
            label = d + (" under 20 clients" if len(cc) < 20 else "")
            rows[(label,)] = row
        compare_table(S, "seasonality division table", se["tb"]["tSeason"] if "tSeason" in se["tb"] else [[]], rows, [0])

        # ---- Segment movement and peak months
        mo = R["movement"]
        segs = ["1-4", "5-10", "10+"]
        res = {}
        for s_ in segs:
            ws = [w for w in W if seg3(w["startHC"]) == s_]
            res[s_] = (len(ws), {d: sum(move(w["startHC"], w["endHC"], seg3, SEG_ORDER) == d for w in ws) for d in ["up", "stay", "down"]})
        got = {d["label"]: d["data"] for d in mo["ch"]["cMove"]["sets"]}
        check(S, "segment movement chart", all(close(got[lab][i], (res[s_][1][d] / res[s_][0]) if res[s_][0] else 0, 1e-9)
                                               for i, s_ in enumerate(segs) for lab, d in [("Moved up", "up"), ("Stayed", "stay"), ("Moved down", "down")]))
        rows = {(SEG_LABEL[s_],): {1: N(n), 2: [(c["up"], 0), (100 * c["up"] / (n or 1), 1)], 3: [(c["stay"], 0), (100 * c["stay"] / (n or 1), 1)],
                                   4: [(c["down"], 0), (100 * c["down"] / (n or 1), 1)]} for s_, (n, c) in res.items()}
        compare_table(S, "movement by starting segment table", mo["tb"]["tMove"], rows, [0])
        ks = sorted({w["k"] for w in W})[:12]
        rows = {}
        for kk in ks:
            row = {}
            for j, s_ in enumerate(["1-4", "5-10"]):
                ws = [w for w in W if w["k"] == kk and seg3(w["startHC"]) == s_]
                up = sum(move(w["startHC"], w["endHC"], seg3, SEG_ORDER) == "up" for w in ws)
                row[1 + j] = [(100 * up / len(ws), 1), (len(ws), 0)] if ws else [(len(ws), 0)]
            rows[(f"Window {kk}",)] = row
        compare_table(S, "movement by window table", mo["tb"]["tMoveWin"], rows, [0])
        pc = [0] * 12
        for c in cl:
            if not c["aged12"]:
                continue
            best, bi = -math.inf, None
            for i in range(3, c["n"]):
                m = M.month(c, i)
                if m.year > M.last_full:
                    continue
                v = c["st"][i] - c["ch"][i]
                if v > best:
                    best, bi = v, m
            if bi is not None and best > 0:
                pc[bi.month - 1] += 1
        got = {d["label"]: d["data"] for d in mo["ch"]["cPeak"]["sets"]}
        check(S, "peak growth months chart", got["Clients with their peak month here"] == pc and got["Net seats (all clients)"] == Snt)

        # ---- Account profile
        pr = R["profile"]

        def prow(cc):
            e12 = [c for c in cc if c["aged12"]]
            r5 = [c for c in e12 if pd.notna(c["p"]["months_to_5"]) and c["p"]["months_to_5"] <= 12]
            reached = [c for c in cc if pd.notna(c["p"]["months_to_5"])]
            kf = [c for c in cc if c["p"]["initial_function"] != "Unknown"]
            f2 = [c for c in kf if pd.notna(c["p"]["months_to_2nd_function"])]
            known = sum(c["p"]["adds_same_function"] + c["p"]["adds_new_function"] for c in cc)
            n = len(cc) or 1
            return {1: N(len(cc)), 2: N(med([c["p"]["starting_seats"] for c in cc]), 1), 3: N(med([c["p"]["seats_day90"] for c in cc]), 1),
                    4: [(100 * len(r5) / len(e12), 1), (len(e12), 0)] if e12 else [(0, 0)], 5: P(len(reached) / n), 6: N(med([c["p"]["months_to_5"] for c in reached]), 1),
                    7: P(len(f2) / (len(kf) or 1)), 8: N(med([c["p"]["months_to_2nd_function"] for c in f2]), 1),
                    9: P(sum(c["p"]["adds_new_function"] for c in cc) / known) if known else None, 10: P(sum(c["p"]["current_seats"] > 0 for c in cc) / n),
                    11: N(med([c["p"]["months_active"] for c in cc]), 0), 12: N(med([c["p"]["current_seats"] for c in cc]), 1), 13: N(med([c["p"]["peak_seats"] for c in cc]), 1)}
        rows = {("All filtered",): prow(cl)}
        for r in REGIONS:
            rows[(r,)] = prow([c for c in cl if c["p"]["region"] == r])
        compare_table(S, "account profile by region table", pr["tb"]["tProf"], rows, [0])

        def sb(c):
            s_ = c["p"]["starting_seats"]
            return "0-1 seat" if s_ <= 1 else "2 seats" if s_ == 2 else "3-4 seats" if s_ <= 4 else "5+ seats"
        got = {d["label"]: d["data"] for d in pr["ch"]["cProf1"]["sets"]}
        ok = True
        for r in REGIONS:
            for i, b in enumerate(["0-1 seat", "2 seats", "3-4 seats"]):
                g_ = [c for c in cl if c["p"]["region"] == r and c["aged12"] and sb(c) == b]
                e = (sum(pd.notna(c["p"]["months_to_5"]) and c["p"]["months_to_5"] <= 12 for c in g_) / len(g_)) if g_ else None
                ok &= close(got[r][i], e, 1e-9) if e is not None else got[r][i] is None
        check(S, "reach 5 by starting seats chart", ok)

        def rate_rows(keyf, dim):
            out = {}
            grp = defaultdict(list)
            for c in cl:
                if c["aged12"]:
                    grp[keyf(c)].append(c)
            for kk, g_ in grp.items():
                h = sum(pd.notna(c["p"]["months_to_5"]) and c["p"]["months_to_5"] <= 12 for c in g_)
                lo, hi = wilson(h, len(g_))
                out[(dim, kk)] = {2: N(len(g_)), 3: N(h), 4: P(h / len(g_)), 5: P(lo), 6: P(hi)}
            return out
        rows = {}
        for keyf, dim in [(sb, "Starting seats"), (lambda c: c["p"]["initial_function"], "Initial function"),
                          (lambda c: c["p"]["custom_division"], "Custom division"), (lambda c: c["p"]["industry_rollup"], "Industry roll-up")]:
            rows.update(rate_rows(keyf, dim))
        compare_table(S, "reach-5 rate table", pr["tb"]["tProf2"], rows, [0, 1])
        fr = {k_[1]: v for k_, v in rate_rows(lambda c: c["p"]["initial_function"], "f").items() if v[2][0][0] >= 20}
        ch = pr["ch"]["cProf2"]
        ok = sorted(ch["labels"]) == sorted(fr) and all(close(100 * v, fr[lab][4][0][0], 1e-6) for lab, v in zip(ch["labels"], ch["sets"][0]["data"]))
        check(S, "reach 5 by initial function chart (groups of 20+)", ok)

        # ---- Path to 5 seats page
        pt = R["path"]
        PATHS = ["Fast to 5 (within 6 months)", "Slow to 5 (after 6 months)", "Not yet at 5, still active", "Churned without reaching 5"]
        SHORT = dict(zip(PATHS, ["Fast to 5", "Slow to 5", "Not yet at 5", "Churned without 5"]))
        nn = len(cl)
        kp = [nums(t) for t in pt["kpi"]]
        check(S, "path KPI tiles (count and share per group)", all(kp[i][-3] == sum(c["p"]["path_group"] == p_ for c in cl) and close(kp[i][-2], 100 * sum(c["p"]["path_group"] == p_ for c in cl) / (nn or 1), 0.05)
                                                                 and kp[i][-1] == nn for i, p_ in enumerate(PATHS)), " | ".join(pt["kpi"]))
        regs = [r for r in REGIONS if any(c["p"]["region"] == r for c in cl)]
        got = {d["label"]: d["data"] for d in pt["ch"]["cPathReg"]["sets"]}
        check(S, "path group mix by region chart", all(close(got[SHORT[p_]][i], sum(c["p"]["path_group"] == p_ for c in cl if c["p"]["region"] == r) / (sum(c["p"]["region"] == r for c in cl) or 1), 1e-9)
                                                       for p_ in PATHS for i, r in enumerate(regs)))
        reached = [c for c in cl if pd.notna(c["p"]["date_5"])]
        bands = [(0, 30), (31, 91), (92, 183), (184, 365), (366, 730), (731, 10 ** 9)]
        got = {d["label"]: d["data"] for d in pt["ch"]["cPathSpeed"]["sets"]}
        check(S, "time to 5 bands by region chart", all(got[r] == [sum(1 for c in reached if c["p"]["region"] == r and a <= c["p"]["days_to_5"] <= b) for a, b in bands] for r in regs))

        def prof_row(cc):
            kf = [c for c in cc if c["p"]["initial_function"] != "Unknown"]
            f2 = [c for c in kf if pd.notna(c["p"]["months_to_2nd_function"])]
            rc = [c for c in cc if pd.notna(c["p"]["date_5"])]
            same, nw, unk = (sum(int(c["p"][k_]) for c in cc) for k_ in ("adds_same_function", "adds_new_function", "adds_unknown_function"))
            reg = lambda r: sum(c["p"]["region"] == r for c in cc)
            return {1: N(len(cc)), 2: P(len(cc) / (nn or 1)), 3: N(reg("APAC")), 4: N(reg("AMER")), 5: N(reg("OPTI")), 6: N(med([c["p"]["starting_seats"] for c in cc]), 1),
                    7: N(med([c["p"]["seats_day90"] for c in cc]), 1), 8: N(med([c["p"]["months_to_5"] for c in rc]), 1), 9: N(med([c["p"]["peak_seats"] for c in cc]), 1),
                    10: N(med([c["p"]["current_seats"] for c in cc]), 1), 11: P(sum(c["p"]["current_seats"] > 0 for c in cc) / (len(cc) or 1)), 12: N(med([c["p"]["months_active"] for c in cc]), 0),
                    13: N(med([c["n"] for c in cc]), 0), 14: P(len(f2) / (len(kf) or 1)), 15: N(med([c["p"]["months_to_2nd_function"] for c in f2]), 1),
                    16: N(same), 17: N(nw), 18: N(unk), 19: P(nw / (same + nw)) if same + nw else None}
        rows = {("All filtered clients",): prof_row(cl)}
        for p_ in PATHS:
            rows[(p_,)] = prof_row([c for c in cl if c["p"]["path_group"] == p_])
        compare_table(S, "path profile of each group table", pt["tb"]["tPathProf"], rows, [0])
        el = [c for c in cl if c["aged12"] and c["p"]["starting_seats"] < 5]
        r12 = lambda c: pd.notna(c["p"]["date_5"]) and c["p"]["months_to_5"] <= 12
        sbk = lambda c: "0-1 seat" if c["p"]["starting_seats"] <= 1 else "2 seats" if c["p"]["starting_seats"] == 2 else "3-4 seats"
        rows = {}
        for dim, fn, mn in [("Region", lambda c: c["p"]["region"], 20), ("Starting seats", sbk, 1), ("Initial function", lambda c: None if c["p"]["initial_function"] == "Unknown" else c["p"]["initial_function"], 20),
                            ("Industry roll-up", lambda c: c["p"]["industry_rollup"], 20), ("Custom division", lambda c: c["p"]["custom_division"], 20)]:
            grp = defaultdict(list)
            for c in el:
                if fn(c) is not None:
                    grp[fn(c)].append(c)
            for k_, g_ in grp.items():
                if len(g_) < mn:
                    continue
                h = sum(map(r12, g_))
                lo, hi = wilson(h, len(g_))
                rc = [c for c in g_ if pd.notna(c["p"]["date_5"])]
                rows[(dim, k_)] = {2: N(len(g_)), 3: N(h), 4: P(h / len(g_)), 5: [(100 * lo, 1), (100 * hi, 1)],
                                   6: P(sum(pd.notna(c["p"]["days_to_5"]) and c["p"]["days_to_5"] <= 183 for c in g_) / len(g_)), 7: N(med([c["p"]["months_to_5"] for c in rc]), 1)}
        compare_table(S, "what predicts reaching 5 table", pt["tb"]["tPathPred"], rows, [0, 1])
        rows = {}
        for r in ["All"] + regs:
            cc = [c for c in reached if r == "All" or c["p"]["region"] == r]
            m = len(cc) or 1
            row = {1: N(len(cc)), 2: P(sum(c["p"]["current_seats"] > 0 for c in cc) / m), 3: P(sum(c["p"]["current_seats"] >= 5 for c in cc) / m),
                   4: P(sum(pd.notna(c["p"]["date_10"]) for c in cc) / m), 8: N(med([c["p"]["current_seats"] for c in cc]), 1), 9: N(med([c["p"]["peak_seats"] for c in cc]), 1)}
            for j, X in enumerate([12, 24, 36]):
                e_ = []
                for c in cc:
                    i5_ = (pd.Period(c["p"]["date_5"][:7], "M") - c["m0"]).n
                    if i5_ + X <= c["n"] - 1:
                        e_.append(c["act"][i5_ + X] > 0)
                row[5 + j] = [(100 * sum(e_) / len(e_), 1), (len(e_), 0)] if e_ else None
            rows[("All filtered" if r == "All" else r,)] = row
        compare_table(S, "what happens after reaching 5 table", pt["tb"]["tPathAfter"], rows, [0])
        got = {d["label"]: d["data"] for d in pt["ch"]["cPathTraj"]["sets"]}
        ok = True
        for p_ in PATHS:
            g_ = [c for c in cl if c["p"]["path_group"] == p_]
            for i, mth in enumerate([1, 3, 6, 12, 24, 36]):
                v = [c["act"][mth - 1] for c in g_ if c["n"] >= mth]
                ok &= close(got[SHORT[p_]][i], med(v), 1e-9) if v else got[SHORT[p_]][i] is None
        check(S, "seat path by group chart (medians)", ok)

        # ---- Clients table (every client)
        restrict = F["segment"] != "All" or F["year"] != "All"
        rows = {}
        for c in cl:
            if restrict and c["sc"] not in byc:
                continue
            p = c["p"]
            fh = next((w["k"] for w in byc.get(c["sc"], []) if w["hit"]), None)
            rows[(c["sc"],)] = {0: p["client_name"], 2: p["region"], 3: p["custom_division"], 4: p["industry_rollup"], 5: p["status"], 6: p["path_group"], 7: p["start_month"],
                                8: SEG_LABEL[seg3(p["starting_seats"])], 9: N(p["starting_seats"]), 10: N(p["total_starts"]), 11: N(p["total_churned"]), 12: N(p["net_seats"]),
                                13: N(p["current_seats"]), 14: N(p["peak_seats"]), 15: p["peak_net_month"], 16: f"Window {fh}" if fh else "–",
                                17: p["initial_function"], 18: N(p["months_to_5"], 1) if pd.notna(p["months_to_5"]) else None,
                                19: N(p["months_to_2nd_function"], 1) if pd.notna(p["months_to_2nd_function"]) else None, 20: N(p["months_active"])}
        compare_table(S, "clients table (every client)", R["clients"]["tb"]["tClients"], rows, [1])

        # ---- client movement table (every client, raw values)
        mvr = {r["sc"]: r for r in R["move"]}
        bad = []
        check(S, "movement table: client count", len(mvr) == len(rows), f"{len(mvr)} vs {len(rows)}")
        for c in cl:
            if (c["sc"],) not in rows:
                continue
            r = mvr.get(c["sc"])
            if r is None:
                bad.append((c["sc"], "missing"))
                continue
            exp = {"lAdd": c["st"][0], "lOut": c["ch"][0], "launch": c["act"][0], "now": c["act"][-1], "addAll": int(c["p"]["total_starts"]), "outAll": int(c["p"]["total_churned"]),
                   "segStart": seg3(c["act"][0]), "segNow": seg3(c["act"][-1]), "nWin": len(byc.get(c["sc"], [])), "hits": sum(w["hit"] for w in byc.get(c["sc"], []))}
            for i, (a, b) in enumerate(STAGES):
                if c["n"] < (b if b else a):
                    exp[f"sa{i}"] = None
                    continue
                frm, to = (1 if a == 1 else a - 1), (b if b else c["n"]) - 1
                exp.update({f"sa{i}": sum(c["st"][frm:to + 1]), f"so{i}": sum(c["ch"][frm:to + 1]), f"se{i}": c["act"][to]})
                exp[f"sn{i}"] = exp[f"sa{i}"] - exp[f"so{i}"]
            for w in byc.get(c["sc"], []):
                exp.update({f"wa{w['k']}": w["starts"], f"wo{w['k']}": w["churn"], f"wn{w['k']}": w["net"], f"ws{w['k']}": w["startHC"], f"we{w['k']}": w["endHC"]})
            for kk, v in exp.items():
                if r.get(kk) != v:
                    bad.append((c["sc"], kk, r.get(kk), v))
        check(S, "movement table: launch, every stage and every window (added, churned, net, staff)", not bad, str(bad[:4]))

        # ---- Insights text
        txt = " || ".join(R["insights"]["ins"])
        nC = len(byc)
        exp_bits = [f"{hitters:,} of {nC:,} clients"] if nC else []
        if nC:
            exp_bits.append(f"({100 * hitters / nC:.1f}%")
        for r in REGIONS if F["region"] == "All" else []:
            ids = [s for s, ws in byc.items() if ws[0]["c"]["p"]["region"] == r]
            if ids:
                exp_bits.append(f"{r} {100 * sum(any(w['hit'] for w in byc[s]) for s in ids) / len(ids):.1f}% (n {len(ids):,})")
        if W:
            exp_bits.append(f"added {sum(w['starts'] for w in W):,} staff and {sum(w['churn'] for w in W):,} ended")
        miss = [b for b in exp_bits if b not in txt]
        check(S, "insights text carries the recomputed numbers", not miss, f"missing: {miss}")

    # ---- QA page (filter independent: first probe)
    R = pages[0]["qa"]
    S = "B-QA"
    exl = pd.read_csv("data/qa_excluded.csv", keep_default_na=False, na_values=[""], dtype={"shortcode": str})
    agg = exl.groupby("reason")["rows"].sum()
    rows = {(k,): {1: N(int(v))} for k, v in agg.items()}
    rows[("Total excluded",)] = {1: N(int(agg.sum()))}
    rows[("Rows used",)] = {1: N(q["included_rows"])}
    rows[("Source rows",)] = {1: N(q["source_rows"])}
    compare_table(S, "excluded rows by reason table", R["tb"]["tQaEx"], rows, [0])
    compare_table(S, "flag counts table", R["tb"]["tQaFlag"], {(k,): {1: N(v)} for k, v in q["flags"].items()}, [0])
    check(S, "excluded shortcode list: every row shown", len(R["tb"]["tQaList"]) - 1 == len(exl))
    check(S, "MyStaff differences: every row shown", len(R["tb"]["tQaDiff"]) - 1 == len(pd.read_csv("data/qa_mystaff_differences.csv")))
    check(S, "flagged row detail: every row shown", len(R["tb"]["tQaFlagRows"]) - 1 == len(pd.read_csv("data/qa_flags.csv")))
    check(S, "name pairs: every row shown", len(R["tb"]["tQaNames"]) - 1 == len(pd.read_csv("data/qa_name_pairs.csv")))
    compare_table(S, "role match by year table", R["tb"]["tQaRole"], {(str(r["y"]),): {1: N(r["stints"]), 2: P(r["match_rate"])} for r in q["role_match_by_year"]}, [0])
    rc = q["active_reconciliation"]
    cols = [k for k in rc[0] if k != "where"]
    rows = {(r["where"],): {1 + j: N(r[k]) for j, k in enumerate(cols)} for r in rc}
    rows[("All staff on the books",)] = {1 + j: N(sum(r[k] for r in rc)) for j, k in enumerate(cols)}
    compare_table(S, "staff on the books reconciliation table", R["tb"]["tQaRecon"], rows, [0])
    kp = [nums(t) for t in R["kpi"]]
    ok = kp[0][0] == q["source_rows"] and kp[1][0] == q["included_rows"] and kp[2][0] == q["source_rows"] - q["included_rows"] and close(kp[3][0], 100 * q["role_match_rate"], 0.05) \
        and kp[4][0] == q["never_staffed_mystaff_clients"]["total"]
    check(S, "QA KPI tiles", ok, " | ".join(R["kpi"]))


def main():
    J, mon, prof = part_a()
    part_b(J, mon, prof)
    print("\n== C. Statistics vs scipy (verify_stats.py)")
    out = subprocess.run([sys.executable, "work/client_growth_dashboard/verify_stats.py"], capture_output=True, text=True).stdout
    check("C", "every test on the page = scipy (6 filter settings)", "PASS" in out.splitlines()[-1], out.splitlines()[-1])
    fails = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS)} checks, {len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for sec in dict.fromkeys(r[0] for r in RESULTS):
        rs = [r for r in RESULTS if r[0] == sec]
        print(f"  {sec:6} {sum(r[2] for r in rs):>4} / {len(rs)}")
    print(f"\nOVERALL: {'PASS' if not fails else 'FAIL'}")
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
