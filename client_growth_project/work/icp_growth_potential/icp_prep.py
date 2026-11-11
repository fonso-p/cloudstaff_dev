"""Shared data preparation for the ICP / high-growth-potential account analysis.

Used by work/icp_growth_potential/build_icp_growth_potential.py and notebooks/icp_growth_potential.ipynb.
Plan: work/icp_growth_potential/plan.md (approved 2026-10-08).

Everything here is pandas only. The workbook recomputes every table with formulas on Raw Data;
values produced here (region, industry, role, function, date reached 5, peak seats) are written to
Raw Data as documented derived columns.
"""
import re
import datetime as dt

import numpy as np
import pandas as pd

ENG_SRC = "Marketing/SC Engagement List2026-10-07 07_48_09.xlsx"
MYSTAFF_SRC = "data/raw/manager_movements/mystaff client list.xlsx"
BILLED_SRC = "data/raw/monika_incremental_seats/2026 New Monthly Billed Report.xlsx"
EXTRACT = dt.datetime(2026, 10, 7)        # extract date, from the engagement list file name
COHORT_FROM = dt.datetime(2021, 1, 1)     # client starts 2021 to 2026 (requester, 2026-10-08)
FAST_DAYS = 183                           # fast = 5 seats within 6 months (requester, 2026-10-08)
MATCH_DAYS = 60                           # role match: kick-off within 60 days of Engagement Date
ROLE_TABS = (["All Billed New Staff 2.0", "2023 Closed Seats", "2024 Closed Seats", "Gross 2025"]
             + [f"{m} 2026" for m in ["January", "February", "March", "April", "May", "June",
                                      "July", "August", "September"]])
NAMED_INTERNAL = {"CLOUDSTAFF", "CLOUDSTAFFINC", "CSNOW", "OPAINTBIZ", "RTGBS", "RTGQA", "05655543", "CSFRLNCR"}

# ---------------------------------------------------------------- function families (ordered rules)
FUNCTIONS = [
    ("Executive Services (generic)", r"ex\w*c\w*tive ser\w*i\w*|exec\w* ser"),
    ("Software and IT", r"develop|software|engineer.*(software|qa|sqa|devops|data)|sqa|\bqa\b|quality assurance|"
                        r"tech\w* support|helpdesk|help desk|it support|\bit\b|network|system|devops|programmer|"
                        r"salesforce|full stack|web dev|data analy|data engineer|business analyst|configuration|"
                        r"cyber|cloud|level 1 support|tier \d support|desktop support|wordpress|shopify dev|data scien|\bnoc\b|"
                        r"power bi|\bai\b|product owner|technical lead|tech lead"),
    ("Engineering and Drafting", r"draft|cad\b|detailer|estimat|quantity surveyor|engineer|architect|3d|bim|"
                                 r"revit|civil|structural|mechanical|electrical|design engineer"),
    ("Accounting and Finance", r"account(ant|ing|s payable|s receivable|s officer|s assistant)|bookkeep|\bcpa\b|tax|"
                               r"audit|payroll|financ|billing|accounts|payable|receivable|collection|credit|"
                               r"paraplanner|loan|mortgage|payment|invoice|treasury|reconcil|revenue process|debt|bookeep|"
                               r"patient account|medical cod|insurance"),
    ("Property and Real Estate", r"property|real estate|leasing|tenan|strata|conveyanc"),
    ("Creative and Marketing", r"graphic|design|marketing|seo|content|social media|video|copywrit|creative|"
                               r"campaign|digital|animator|photo|ecommerce marketing|brand"),
    ("Sales and Lead Gen", r"sales|lead gen|appointment|telemarket|business development|\bsdr\b|"
                           r"inside sales|outbound|cold call|account manager|club owner|club agent"),
    ("Customer Service and Support", r"customer|client serv|call cent|contact cent|\bcsr\b|support|care|"
                                     r"travel|cruise|concierge|reservation|booking|claims|case|member|"
                                     r"order|chat|help|service rep|receptionist|scheduler|ticketing"),
    ("HR and Recruitment", r"recruit|\bhr\b|human resource|talent|onboarding"),
    ("Operations and Admin", r"admin|assistant|\bva\b|virtual|data entry|back.?office|operations|coordinator|"
                             r"processor|processing|purchas|logistic|shipment|dispatch|inventory|procure|"
                             r"paralegal|legal|compliance|project|manager|team lead|supervisor|director|"
                             r"officer|specialist|analyst|associate|consultant|clerk|document|records|roster|"
                             r"workforce|planner|trainer|training|advisor|executive"),
]
FUNC_RE = [(f, re.compile(p, re.I)) for f, p in FUNCTIONS]
FUNCTION_ORDER = [f for f, _ in FUNCTIONS] + ["Other", "Unknown"]


def role_function(title):
    t = "" if title is None or (isinstance(title, float) and np.isnan(title)) else str(title).strip()
    if t in ("", "--", "-", "NA", "N/A") or re.match(r"(?i)^(crk|ceb|mnl|work from home)", t):
        return "Unknown"
    for f, rx in FUNC_RE:
        if rx.search(t):
            return f
    return "Other"


def norm_name(s):
    return re.sub(r"[^a-z]", "", "" if s is None or (isinstance(s, float) and np.isnan(s)) else str(s).lower())


# ---------------------------------------------------------------- client type (rule approved 2026-09-30)
def client_types(df):
    sc = df["Shortcode"].map(lambda v: "" if v is None else str(v).strip())
    nm = df["Client Name"].map(lambda v: "" if v is None else str(v).strip())
    hub_share = df["Category"].eq("Hub").groupby(sc).mean()
    rows_per_sc = sc.value_counts()

    def one(code, name):
        if code == "":
            return "Blank shortcode"
        if code == "CSTREENGAGE":
            return "Disengaged Staff Pool"
        if code.startswith("CSS") and not name.upper().startswith("CS ") and rows_per_sc[code] == 1:
            return "Test record"
        if (code in NAMED_INTERNAL or re.match(r"(?i)^(CS |CSDEVS|Ojt )", name)
                or re.search(r"(?i)cloudstaff|ready ?to ?go", name)):
            return "Internal unit"
        if hub_share[code] >= 0.5:
            return "Internal unit (Hub 50%+)"
        return "Client"

    by_sc = {}
    for code, name in zip(sc, nm):
        by_sc.setdefault(code, one(code, name))
    return sc, by_sc


# ---------------------------------------------------------------- MyStaff enrichment
APAC_COUNTRIES = {"australia", "new zealand", "philippines", "hong kong", "singapore", "malaysia", "india",
                  "japan", "china", "indonesia", "thailand", "vietnam", "south korea", "korea", "taiwan", "fiji",
                  "papua new guinea"}
APAC_CCY = {"AUD", "NZD", "PHP", "HKD", "SGD", "JPY", "INR", "MYR"}


def opti_region(country, tz, ccy):
    c = str(country or "").strip().lower()
    if c:
        return ("APAC" if c in APAC_COUNTRIES else "AMER"), "office country"
    t = str(tz or "").strip().lower()
    if t:
        return ("APAC" if any(k in t for k in ["australia", "new zealand", "philippines", "hong kong",
                                               "singapore", "asia"]) else "AMER"), "timezone"
    k = str(ccy or "").strip().upper()
    if k:
        return ("APAC" if k in APAC_CCY else "AMER"), "billing currency"
    return None, "no location data"


def clean_industry(rollup, hub):
    r = str(rollup or "").strip()
    if r in ("", "-", "0", "nan"):
        h = str(hub or "").strip()
        return ("Unknown" if h in ("", "-", "0", "nan") else h), ("HubSpot industry" if h not in ("", "-", "0", "nan") else "none")
    return r, "Industry Roll Up"


def load_mystaff(path=MYSTAFF_SRC):
    m = pd.read_excel(path, sheet_name="MyStaff", dtype=str).fillna("")
    m = m.drop_duplicates("Shortcode")
    out = {}
    for _, r in m.iterrows():
        reg = r["Region"].strip()
        brand = "Cloudstaff"
        how = "MyStaff Region"
        if reg == "OPTI":
            brand = "OPTI"
            reg, how = opti_region(r["Office Address Country"], r["Timezone"], r["Billing Currency"])
        elif reg not in ("APAC", "AMER"):
            how = f"MyStaff Region '{reg}' (out of scope)"
            reg = None
        ind, ind_src = clean_industry(r["Industry Roll Up"], r["Industry Hubspot"])
        out[r["Shortcode"]] = {"region": reg, "region_rule": how, "brand": brand, "industry": ind,
                               "industry_src": ind_src, "internal": r["Internal (Yes / No)"] == "Yes",
                               "mystaff_region": r["Region"]}
    return out


# ---------------------------------------------------------------- roles from the billed report
def load_roles(path=BILLED_SRC):
    xl = pd.ExcelFile(path)
    frames = []
    for s in ROLE_TABS:
        d = pd.read_excel(xl, s, dtype=str).fillna("")
        d.columns = [str(c) for c in d.columns]
        frames.append(pd.DataFrame({
            "src": s, "sc": d.get("Client Shortcode", "").astype(str).str.strip(),
            "nm": (d.get("Resource (First Name)", "") + d.get("Resource (Last Name)", "")).map(norm_name),
            "kick": pd.to_datetime(d.get("Kick-off Date", ""), errors="coerce"),
            "role": d.get("Role", "").astype(str).str.strip()}))
    r = pd.concat(frames, ignore_index=True)
    r = r[(r["role"] != "") & (r["role"] != "--") & (r["nm"] != "") & r["kick"].notna()]
    return r.drop_duplicates(["nm", "kick", "role", "sc"])


def match_roles(e, roles):
    """e: frame with pos, sc, nm, ed. Returns Series pos -> (role, rule). Best = same shortcode, then closest date."""
    cand = e[["pos", "sc", "nm", "ed"]].merge(roles, on="nm", suffixes=("", "_r"))
    cand["gap"] = (cand["kick"] - cand["ed"]).dt.days.abs()
    cand = cand[cand["gap"] <= MATCH_DAYS]
    cand["same_sc"] = (cand["sc"] == cand["sc_r"]).astype(int)
    cand = cand.sort_values(["pos", "same_sc", "gap"], ascending=[True, False, True]).drop_duplicates("pos")
    return cand.set_index("pos")[["role", "src", "same_sc", "gap"]]


# ---------------------------------------------------------------- headcount helpers
def seats_on(stints, sc, day):
    """Active valid stints per shortcode on a given day (Series day per shortcode or scalar)."""
    v = stints.merge(day.rename("cp"), left_on="sc", right_index=True) if isinstance(day, pd.Series) else stints.assign(cp=day)
    a = v[(v["ed"] <= v["cp"]) & (v["dd"].isna() | (v["dd"] >= v["cp"]))]
    return a.groupby("sc").size().reindex(sc, fill_value=0)


def peak_and_date5(stints, threshold=5):
    """Per shortcode: peak concurrent seats and the first date with 5+ concurrent seats.

    Event sweep: +1 on Engagement Date, -1 on the day after Disengagement Date (a stint counts on both its
    start and end dates, matching the Engagement Date <= day <= Disengagement Date rule)."""
    ev = pd.concat([
        pd.DataFrame({"sc": stints["sc"], "d": stints["ed"], "x": 1}),
        pd.DataFrame({"sc": stints["sc"], "d": stints["dd"] + pd.Timedelta(days=1), "x": -1}).dropna(subset=["d"]),
    ])
    ev = ev.groupby(["sc", "d"], as_index=False)["x"].sum().sort_values(["sc", "d"])
    ev["hc"] = ev.groupby("sc")["x"].cumsum()
    peak = ev.groupby("sc")["hc"].max()
    d5 = ev[ev["hc"] >= threshold].groupby("sc")["d"].min()
    return peak, d5


def prepare(df):
    """df = raw engagement list as loaded by profile_data.load_source (one row per stint, file order).

    Returns (row-level frame aligned to df, client-level frame for the cohort, mystaff dict, roles)."""
    N = len(df)
    sc, type_by_sc = client_types(df)
    ctype = sc.map(type_by_sc)
    ed = pd.to_datetime(df["Engagement Date"], errors="coerce")
    dd = pd.to_datetime(df["Disengagement Date"], errors="coerce")
    dup = df.astype(str).duplicated(keep="first")
    valid = dd.isna() | (dd >= ed)
    ms = load_mystaff()

    is_client = (ctype == "Client") & ~dup
    start_all = ed[is_client].groupby(sc[is_client]).min()

    def scope(code, t, d):
        if d:
            return "Duplicate row"
        if t != "Client":
            return t
        info = ms.get(code)
        if info is None:
            return "Not in MyStaff client list"
        if info["internal"]:
            return "Internal (MyStaff flag)"
        if info["region"] is None:
            return "Region out of scope or unknown"
        if start_all[code] < COHORT_FROM:
            return "Client started before 2021"
        return "In scope"

    sc_scope = {}
    scope_row = [scope(c, t, d) if (c, d) not in sc_scope else sc_scope[(c, d)] for c, t, d in zip(sc, ctype, dup)]
    include = pd.Series(["Y" if s == "In scope" else "N" for s in scope_row])
    inc = include.eq("Y")

    rows = pd.DataFrame({"pos": range(N), "sc": sc, "csid": df["CSID"].astype(str), "ed": ed, "dd": dd,
                         "valid": valid, "scope": scope_row, "inc": inc, "category": df["Category"].astype(str),
                         "nm": (df["First Name"].fillna("").astype(str) + df["Last Name"].fillna("").astype(str)).map(norm_name)})
    rows["region"] = [ms[c]["region"] if i else None for c, i in zip(sc, inc)]
    rows["brand"] = [ms[c]["brand"] if i else None for c, i in zip(sc, inc)]
    rows["industry"] = [ms[c]["industry"] if i else None for c, i in zip(sc, inc)]
    rows["client_start"] = [start_all[c] if i else pd.NaT for c, i in zip(sc, inc)]
    rows["day"] = (rows["ed"] - rows["client_start"]).dt.days  # 0 = first day

    # roles for in-scope rows
    roles = load_roles()
    m = match_roles(rows[inc], roles)
    rows["role"] = rows["pos"].map(m["role"])
    rows["role_rule"] = rows["pos"].map(
        lambda p: None if p not in m.index else ("name + kick-off date + same shortcode" if m.at[p, "same_sc"] else "name + kick-off date"))
    rows["function"] = [role_function(r) if i else None for r, i in zip(rows["role"], inc)]

    # first stint per staff and client (organic rule)
    vr = rows[inc & valid]
    first_pos = set(vr.sort_values(["ed", "pos"]).drop_duplicates(["sc", "csid"])["pos"])
    rows["first_stint"] = [("Y" if p in first_pos else "N") if i else None for p, i in zip(rows["pos"], inc)]

    # client level
    st = vr[["sc", "ed", "dd"]]
    cl = vr.groupby("sc").agg(start=("client_start", "first"), region=("region", "first"),
                              brand=("brand", "first"), industry=("industry", "first"))
    # clients whose only rows are invalid stints still need a record
    allc = rows[inc].groupby("sc").agg(start=("client_start", "first"), region=("region", "first"),
                                       brand=("brand", "first"), industry=("industry", "first"))
    cl = allc
    idx = cl.index
    cl["age_days"] = (EXTRACT - cl["start"]).dt.days
    peak, d5 = peak_and_date5(st)
    cl["peak"] = peak.reindex(idx).fillna(0).astype(int)
    cl["date5"] = d5.reindex(idx)
    cl["days_to5"] = (cl["date5"] - cl["start"]).dt.days
    cl["date10"] = peak_and_date5(st, 10)[1].reindex(idx)
    cl["days_to10"] = (cl["date10"] - cl["start"]).dt.days
    cl["current"] = seats_on(st, idx, EXTRACT)
    cl["churned"] = cl["current"] == 0
    for n in [30, 90, 180, 365, 730, 1095]:
        cl[f"seats_d{n}"] = seats_on(st, idx, cl["start"] + pd.to_timedelta(n, "D"))
    cl["group"] = np.select(
        [cl["days_to5"].notna() & (cl["days_to5"] <= FAST_DAYS), cl["days_to5"].notna(), ~cl["churned"]],
        ["1 Fast 5+", "2 Slow 5+", "3 Not reached 5, active"], "4 Churned, never 5")

    fr = rows[inc & (rows["first_stint"] == "Y")]
    cl["adds_31_90"] = fr[(fr["day"] >= 30) & (fr["day"] < 90)].groupby("sc").size().reindex(idx, fill_value=0)
    vv = rows[inc & valid & rows["dd"].notna()]
    cl["leavers_90"] = vv[(vv["dd"] - vv["client_start"]).dt.days < 90].groupby("sc").size().reindex(idx, fill_value=0)
    cl["rtg_d30"] = fr[(fr["day"] < 30) & (fr["category"] == "RTG")].groupby("sc").size().reindex(idx, fill_value=0)

    # initial function: most common known function among first-month starts (ties: earliest start)
    f1 = fr[fr["day"] < 30].copy()
    f1["known"] = ~f1["function"].isin(["Unknown"])
    k = f1[f1["known"]]
    cnt = k.groupby(["sc", "function"]).agg(n=("pos", "size"), first=("ed", "min"), fpos=("pos", "min")).reset_index()
    cnt = cnt.sort_values(["sc", "n", "first", "fpos"], ascending=[True, False, True, True]).drop_duplicates("sc")
    cl["initial_function"] = cnt.set_index("sc")["function"].reindex(idx).fillna("Unknown")
    cl["role_m1_matched"] = k.groupby("sc").size().reindex(idx, fill_value=0)

    # expansion: adds after day 30 classified against initial function
    rows["client_initial_function"] = rows["sc"].map(cl["initial_function"])
    later = fr[fr["day"] >= 30].copy()
    later["init"] = later["sc"].map(cl["initial_function"])
    later["kind"] = np.select([later["function"].eq("Unknown") | later["init"].eq("Unknown"),
                               later["function"].eq(later["init"])], ["Unknown", "Same function"], "New function")
    rows["expansion_kind"] = rows["pos"].map(later.set_index("pos")["kind"])
    for kind in ["Same function", "New function", "Unknown"]:
        cl[f"adds_{kind}"] = later[later["kind"] == kind].groupby("sc").size().reindex(idx, fill_value=0)
    # time to second function: first first-stint with a known function different from the initial one
    nf = later[later["kind"] == "New function"]
    cl["date_2nd_fn"] = nf.groupby("sc")["ed"].min().reindex(idx)
    cl["days_to_2nd_fn"] = (cl["date_2nd_fn"] - cl["start"]).dt.days
    cl["functions_by_d90"] = fr[(fr["day"] < 90) & ~fr["function"].eq("Unknown")].groupby("sc")["function"].nunique().reindex(idx, fill_value=0)

    # after reaching 5: Active / Churned n days after the date reached 5, or Too early if that day is after the extract
    for n in [365, 730, 1095]:
        cp = cl["date5"] + pd.to_timedelta(n, "D")
        s5 = seats_on(st, idx, cp.dropna()).reindex(idx).fillna(0)
        cl[f"status_5p{n}"] = np.select([cl["date5"].isna(), cp > EXTRACT, s5 > 0], [None, "Too early", "Active"], "Churned")
    cl["date2_before5"] = np.where(cl["date5"].isna(), None,
                                   np.where(cl["date_2nd_fn"].notna() & (cl["date_2nd_fn"] <= cl["date5"]), "Yes", "No"))
    cl["client_row_pos"] = rows[inc].drop_duplicates("sc").set_index("sc")["pos"].reindex(idx)
    return rows, cl, ms, roles
