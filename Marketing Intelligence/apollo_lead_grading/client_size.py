"""Client size: the free-text Revenue and Employees columns of the growth-opportunity files -> numbers.

Reads   <YOGA_DIR>/*-growth-opportunity-*.csv        one row per existing client (AMER, APAC), researched size text
        <DATA_DIR>/*_Propensity_Extract_propensity_accounts.csv   INTERNAL: seats now, departments so far (by shortcode)
Writes  <YOGA_DIR>/client_size_<date>.csv             one row per client, raw text kept next to every parsed number

Purpose: Client Propensity's fit profiles (the Fit part of the EMEA lead grades: 5+ seats, 2nd department) are by
industry only, because company size was known for just 235 / 1,110 clients. These files give size for most clients,
on the same scale as Apollo's "# Employees" and "Annual Revenue" (USD) on the leads.

Rules (one figure per field, traceable to the text; decision 2026-11-26, user):
  1. Take the FIRST number or range in the text, wherever it is. Years (2025, FY26) are skipped; revenue needs a
     currency or a unit (M, K, million...) so counts aren't read as money.
  2. A range keeps low and high; the point value is their geometric mean ("<5M" -> 0 to 5M, point = half;
     "50+" -> low only, point = low).
  3. The point value goes into a standard bucket: LinkedIn / Apollo employee bands, ZoomInfo-style revenue brackets.
     *_band_order sorts the buckets; *_band_spans = the raw range crosses a bucket edge.
  4. Revenue currency: the code or symbol in the text; a bare "$" takes the HQ country's dollar (first office).
     Converted to USD with the fixed FX_TO_USD rates below (approximate, edit to refresh), then bucketed.
  5. needs_review lists why a person should check a row (no figure, onshore only, group / parent figure, >5x spread...).

Usage, from the Marketing Intelligence folder:
  ../.venv/Scripts/python.exe apollo_lead_grading/client_size.py [--yoga-dir PATH]
"""
import argparse
import datetime as dt
import glob
import math
import re
import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font

# ---------------------------------------------------------------- settings
_PROJECTS = [Path.home() / "OneDrive - Cloudstaff Pty Ltd" / "Desktop" / "Projects", Path.home() / "Desktop" / "Projects"]
PROJECTS = next((p for p in _PROJECTS if p.exists()), _PROJECTS[0])
DATA_DIR = PROJECTS / "Marketing Intelligence Priority" / "Data"
YOGA_DIR = DATA_DIR / "Yoga Data"
MYSTAFF_DIR = PROJECTS / "Client Propensity" / "Data"          # the MyStaff extract Client Propensity reads
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "references" / "mystaff_industry"))
from mystaff_industry import classify_frame                    # noqa: E402  same industry groups as Client Propensity

# Approximate USD per unit of each currency (late 2026, rounded). Size bands are wide, so +-5% doesn't move a band.
FX_TO_USD = {"USD": 1.0, "AUD": 0.65, "NZD": 0.59, "CAD": 0.72, "GBP": 1.27, "EUR": 1.08, "SGD": 0.75,
             "HKD": 0.128, "CHF": 1.13, "JPY": 0.0067, "PHP": 0.017, "INR": 0.012}
DOLLAR_BY_COUNTRY = {"AU": "AUD", "NZ": "NZD", "CA": "CAD", "SG": "SGD", "HK": "HKD"}   # bare "$" by HQ country
# Standard buckets (upper edge, label). Employees = LinkedIn / Apollo / HubSpot company-size bands; the first four match
# grade_leads.py BAND_EDGES and the rest roll up into its "500+". Revenue = ZoomInfo-style brackets in USD, so the
# many "<$5M" (ZoomInfo) texts fall on an edge, not across one.
BAND_EDGES = [(10, "1-10"), (50, "11-50"), (200, "51-200"), (500, "201-500"), (1000, "501-1,000"),
              (5000, "1,001-5,000"), (10000, "5,001-10,000"), (math.inf, "10,001+")]
REVENUE_EDGES = [(1e6, "<$1M"), (5e6, "$1M-5M"), (10e6, "$5M-10M"), (25e6, "$10M-25M"), (50e6, "$25M-50M"),
                 (100e6, "$50M-100M"), (250e6, "$100M-250M"), (500e6, "$250M-500M"), (1e9, "$500M-1B"),
                 (math.inf, "$1B+")]
WIDE_SPREAD = 5                       # high / low above this -> needs review
STANDARD_BANDS = {(1, 10), (2, 10), (11, 50), (51, 200), (201, 500), (501, 1000), (1001, 5000), (5001, 10000)}

# ---------------------------------------------------------------- text patterns
DASH = r"\s*(?:-|–|—|to)\s*"
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
CUR = r"(?:USD|AUD|NZD|CAD|GBP|EUR|SGD|HKD|CHF|JPY|PHP|INR|US\$|A\$|AU\$|NZ\$|C\$|CA\$|S\$|HK\$|\$|£|€|¥)"
UNIT = r"(?:k|thousand|m|mn|mm|million|b|bn|billion)(?![a-z])"
MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
CUR_CODE = {"US$": "USD", "A$": "AUD", "AU$": "AUD", "NZ$": "NZD", "C$": "CAD", "CA$": "CAD", "S$": "SGD", "HK$": "HKD",
            "£": "GBP", "€": "EUR", "¥": "JPY"}
MONEY = re.compile(rf"(?P<cur>{CUR})?\s*~?\s*\$?\s*(?P<num>{NUM})\s*(?P<unit>{UNIT})?(?P<plus>\+)?", re.I)
COUNT = re.compile(rf"(?P<num>{NUM})(?P<plus>\+)?", re.I)
BELOW = re.compile(r"(?:<|under|sub-?|less than|up to|below)\s*$", re.I)
ABOVE = re.compile(r"(?:>|over|more than|above)\s*$", re.I)
UNDISCLOSED = re.compile(   # "- (not disclosed; estimated ...)": flagged for review
    r"^\s*(?:-|–|n/?a\b|not (?:publicly )?disclosed|undisclosed|unknown)", re.I)
YEAR = re.compile(r"\b(?:FY)?(20[12]\d)\b")
REVIEW_WORDS = {
    "onshore only": r"\bonshore\b",
    "group / parent figure": r"\b(?:group|parent|consolidated|combined|affiliated|holding|globally|global|network)\b",
    "includes Cloudstaff / offshore staff": r"\b(?:cloudstaff|offshore)\b",
    "defunct / acquired": r"\b(?:defunct|ceased|acquired by|wound up|liquidat\w*)\b",
}
REVIEW_RE = {k: re.compile(v, re.I) for k, v in REVIEW_WORDS.items()}
# Revenue texts that quote something else (audit 2026-11-26: real-estate sales transacted, GCI, portfolio value...)
NOT_REVENUE = re.compile(r"transact|sales value|property sales|\bGCV\b|\bGCI\b|gross written|cumulative|portfolio|"
                         r"assets under|\bAUM\b|funds under", re.I)
RPE_RANGE = (15_000, 2_000_000)       # USD revenue per employee outside this -> both figures flagged for review


def _num(s):
    return float(s.replace(",", ""))


def parse_money(text):
    """First money figure or range in text -> (low, high, currency or None, matched text). Needs a currency or a unit
    so years and counts aren't read as money. Values in the currency's units."""
    hits = [m for m in MONEY.finditer(text) if m.group("cur") or m.group("unit")]
    for m in hits:
        if not m.group("unit") and _num(m.group("num")) < 1000:
            nxt = re.match(rf"{DASH}<?\s*{MONEY.pattern}", text[m.end():], re.I)   # "$30–35M": unit on the 2nd number
            if not (nxt and nxt.group("unit")):
                continue                                                           # "$5" with no unit: not a revenue
        cur = m.group("cur")
        lo = _num(m.group("num"))
        unit = (m.group("unit") or "").lower()
        hi, span_end = None, m.end()
        nxt = re.match(rf"{DASH}<?\s*(?P<cur2>{CUR})?\s*~?\s*\$?\s*(?P<num2>{NUM})\s*(?P<unit2>{UNIT})?", text[m.end():], re.I)
        if nxt and not YEAR.fullmatch(nxt.group("num2")):
            hi = _num(nxt.group("num2"))
            unit2 = (nxt.group("unit2") or unit).lower()
            unit = unit or unit2
            hi *= MULT.get(unit2, 1)
            cur = cur or nxt.group("cur2")
            span_end = m.end() + nxt.end()
        lo *= MULT.get(unit, 1)
        if hi is not None and BELOW.search(text[:m.start()]):    # "<$1M–$2M" = 0 to 2M (audit 2026-11-26)
            lo = 0.0
        if hi is None and m.group("plus"):
            hi = math.inf
        elif hi is None:
            before = text[:m.start()]
            if BELOW.search(before):
                lo, hi = 0.0, lo
            elif ABOVE.search(before):
                hi = math.inf
            else:
                hi = lo
        if lo == 0 and hi == 0:
            continue
        if not cur or cur == "$":
            cur = currency_in(text) or cur
        return lo, hi, cur, text[m.start():span_end].strip()
    return None


def parse_count(text):
    """First head count or range -> (low, high, matched text). Skips years and FY labels."""
    for m in COUNT.finditer(text):
        n = _num(m.group("num"))
        tail = text[m.end():m.end() + 12]
        if YEAR.fullmatch(m.group("num")) or re.match(r"\s*(?:%|years?|offices?|locations?|clients?|seats?)", tail, re.I) \
                or text[max(0, m.start() - 2):m.start()].upper().endswith("FY"):
            continue
        nxt = re.match(rf"{DASH}(?P<n2>{NUM})(?P<plus2>\+)?", text[m.end():], re.I)
        before = text[:m.start()]
        if nxt and not YEAR.fullmatch(nxt.group("n2")):
            return n, _num(nxt.group("n2")), text[m.start():m.end() + nxt.end()].strip()
        if m.group("plus") or ABOVE.search(before):
            return n, math.inf, m.group(0)
        if BELOW.search(before):
            return 0.0, n, m.group(0)
        return n, n, m.group(0)
    return None


def currency_in(text):
    m = re.search(r"\b(USD|AUD|NZD|CAD|GBP|EUR|SGD|HKD|CHF|JPY|PHP|INR)\b|(US\$|AU?\$|NZ\$|CA?\$|S\$|HK\$|£|€|¥)", text)
    if not m:
        return None
    return m.group(1) or CUR_CODE.get(m.group(2), CUR_CODE.get(m.group(2).replace("AU$", "A$")))


def pick(text, parser):
    """Rule 1: the first number or range anywhere in the text."""
    if not isinstance(text, str) or not text.strip() or text.strip().lower() == "nan":
        return None, "blank"
    got = parser(text)
    return (got, "first figure") if got else (None, "no figure")


def point(lo, hi):
    if hi == math.inf:
        return lo
    if lo <= 0:
        return hi / 2
    return math.sqrt(lo * hi)


def band(v, edges):
    if v is None or pd.isna(v):
        return None
    return next(lbl for edge, lbl in edges if v <= edge)


def band_order(v, edges):
    """1 = smallest bucket, for sorting and comparing."""
    lbl = band(v, edges)
    return None if lbl is None else [b for _, b in edges].index(lbl) + 1


def spans(lo, hi, edges):
    """The raw range crosses a bucket edge ("<$5M" = $0-5M spans <$1M and $1M-5M)."""
    if lo is None or hi is None:
        return None
    return band(max(lo, 1), edges) != band(hi, edges)


def basis(text, how):
    t = (text or "").lower()
    if how in ("blank", "no figure"):
        return how
    if re.search(r"\b(reported|annual report|asx|sec\b|10-k|statutory|press release|filing|audited)", t) \
            and not re.search(r"estimat|inferred", t.split(";")[0]):
        return "reported"
    if re.search(r"inferred|assessed|based on|indicative|suggest", t):
        return "inferred"
    return "estimate"


def year_of(text):
    ys = [int(y) for y in YEAR.findall(text or "")]
    return max(ys) if ys else None


def review_flags(text, lo, hi, how):
    out = [k for k, rx in REVIEW_RE.items() if rx.search(text or "")]
    if how in ("blank", "no figure"):
        out.insert(0, how)
    elif UNDISCLOSED.match(text or ""):
        out.append("not disclosed (estimate)")
    if lo and hi and hi != math.inf and hi / lo > WIDE_SPREAD:
        out.append(f"wide range (>{WIDE_SPREAD}x)")
    return out


def parse_row(r):
    r = {k: (v if isinstance(v, str) and v.strip() else None) for k, v in r.items()}
    hq =str(r.get("Offices") or "").split(",")[0].strip().upper()
    out = {"shortcode": str(r["Client shortcode"]).strip().upper(), "client_name": r["Client name"],
           "source_file": r["_file"], "file_region": r["_region"], "hq_country": hq or None}

    # revenue
    rev_text = r.get("Revenue")
    got, how = pick(rev_text, parse_money)
    lo = hi = cur = None
    if got:
        lo, hi, cur, matched = got
        cur = CUR_CODE.get(cur, cur).upper() if cur and cur != "$" else None
        cur = cur or DOLLAR_BY_COUNTRY.get(hq, "USD")             # "~$2.4M USD" was caught by currency_in()
    fx = FX_TO_USD.get(cur) if cur else None
    usd = lambda v: None if v is None or fx is None else (v * fx if v != math.inf else None)   # noqa: E731
    rev_pt = usd(point(lo, hi)) if got and fx else None
    out.update({"revenue_raw": rev_text, "revenue_from": how, "revenue_matched": got[3] if got else None,
                "revenue_currency": cur, "revenue_low_usd": usd(lo), "revenue_high_usd": usd(hi), "revenue_usd": rev_pt,
                "revenue_band": band(rev_pt, REVENUE_EDGES), "revenue_band_order": band_order(rev_pt, REVENUE_EDGES),
                "revenue_band_spans": spans(usd(lo), usd(hi), REVENUE_EDGES) if got and fx else None,
                "revenue_basis": basis(rev_text, how),
                "revenue_year": year_of(rev_text)})
    rflags = review_flags(rev_text, lo, hi, how)
    if got and cur and cur not in FX_TO_USD:
        rflags.append(f"no FX rate for {cur}")
    if got and NOT_REVENUE.search(rev_text or ""):
        rflags.append("may not be revenue (transactions / GCI / portfolio / premium)")

    # employees
    emp_text = r.get("Employees")
    got, how = pick(emp_text, parse_count)
    if got and got[1] == 0:                                   # "0 reported W-2 employees at the Foundation"
        got, how = None, "no figure"
    elo = ehi = ept = None
    if got:
        elo, ehi, _ = got
        ept = round(point(elo, ehi))
    b = basis(emp_text, how)
    if got and (int(elo), int(ehi) if ehi != math.inf else -1) in STANDARD_BANDS:
        b = "band only"
    out.update({"employees_raw": emp_text, "employees_from": how, "employees_matched": got[2] if got else None,
                "employees_low": elo, "employees_high": None if ehi == math.inf else ehi, "employees": ept,
                "employee_band": band(ept, BAND_EDGES), "employee_band_order": band_order(ept, BAND_EDGES),
                "employee_band_spans": spans(elo, None if ehi == math.inf else ehi, BAND_EDGES) if got else None,
                "employees_basis": b, "employees_year": year_of(emp_text)})
    eflags = review_flags(emp_text, elo, ehi, how)
    if rev_pt and ept:                                        # one of the two is likely not this company's own figure
        rpe = rev_pt / ept
        if not RPE_RANGE[0] <= rpe <= RPE_RANGE[1]:
            msg = f"revenue per employee ${rpe:,.0f} outside ${RPE_RANGE[0]:,.0f}-${RPE_RANGE[1]:,.0f}"
            rflags.append(msg)
            eflags.append(msg)

    out["revenue_review"] = "; ".join(rflags) or None
    out["employees_review"] = "; ".join(eflags) or None
    out["needs_review"] = bool(rflags or eflags)
    return out


def load_internal():
    """Seats now and departments so far, from the newest Client Propensity extract (by shortcode)."""
    files = sorted(glob.glob(str(DATA_DIR / "*_Propensity_Extract_propensity_accounts.csv")))
    if not files:
        return None, None
    a = pd.read_csv(files[-1], usecols=["shortcode", "seats_current", "depts_so_far", "depts_so_far_names",
                                        "fit_growth_band", "fit_second_dept_band"])
    a["shortcode"] = a["shortcode"].astype(str).str.strip().str.upper()
    return a.drop_duplicates("shortcode"), Path(files[-1]).name


SIZE_COLS = ["employees", "employees_low", "employees_high", "employee_band", "employee_band_order",
             "employee_band_spans", "employees_basis", "employees_year", "employees_from", "revenue_usd",
             "revenue_low_usd", "revenue_high_usd", "revenue_band", "revenue_band_order", "revenue_band_spans",
             "revenue_currency",
             "revenue_basis", "revenue_year", "revenue_from", "needs_review", "employees_review", "revenue_review",
             "employees_raw", "revenue_raw", "source_file"]


def client_table(size):
    """Every internal client account in the newest Propensity extract (all its columns), plus name / industry / region
    from the Priority List and the parsed size. One row per account; size is blank where the growth files lack it."""
    acc_file = sorted(glob.glob(str(DATA_DIR / "*_Propensity_Extract_propensity_accounts.csv")))[-1]
    acc = pd.read_csv(acc_file)
    acc["shortcode"] = acc["shortcode"].astype(str).str.strip().str.upper()
    # Industry the way Client Propensity gets it: MyStaff (HubSpot industry, else Cloudstaff roll-up) -> industry group
    ms_file = sorted(glob.glob(str(MYSTAFF_DIR / "CONFIDENTIAL Mystaff*.xlsx")))[-1]
    ms = pd.read_excel(ms_file, sheet_name="MyStaff", usecols=["Shortcode", "Client", "Industry Hubspot", "Industry Roll Up",
                                                              "Office Address Country"], dtype=str)
    ms["shortcode"] = ms.pop("Shortcode").str.strip().str.upper()
    ms = classify_frame(ms.dropna(subset=["shortcode"]).drop_duplicates("shortcode"))
    ms = ms.rename(columns={"Client": "company_name", "industry_group": "industry", "Office Address Country": "office_country"})
    t = acc.merge(ms[["shortcode", "company_name", "industry", "industry_sector", "office_country"]], on="shortcode", how="left")
    pl_file = sorted(glob.glob(str(DATA_DIR / "priority_company_info_combined*.xlsx")))
    pl_file = [f for f in pl_file if "MOCK" not in f.upper()][-1]
    pl = pd.read_excel(pl_file, sheet_name="Priority List", usecols=["account_id", "company_name", "region"])
    t = t.merge(pl.drop_duplicates("account_id").rename(columns={"company_name": "_pl_name"}), on="account_id", how="left")
    s = size.drop_duplicates("shortcode").set_index("shortcode")
    t["company_name"] = t["company_name"].fillna(t.pop("_pl_name")).fillna(t["shortcode"].map(s["client_name"]))
    t["hq_country"] = t["shortcode"].map(s["hq_country"])
    for c in SIZE_COLS:
        t[c] = t["shortcode"].map(s[c])
    t.insert(2, "has_size", t["employees"].notna() | t["revenue_usd"].notna())
    t.insert(3, "seats_now_zero", t["seats_current"].fillna(0).eq(0))
    front = ["account_id", "shortcode", "company_name", "industry", "industry_sector", "region", "office_country",
             "hq_country", "has_size", "seats_current", "seats_now_zero"]
    t = t[front + [c for c in t.columns if c not in front]]
    return t, Path(acc_file).name, f"{Path(ms_file).name} (name, industry); {Path(pl_file).name} (region, name fallback)"


def write_workbook(dest, clients, size, sources):
    n = len(clients)
    active = clients["seats_current"].fillna(0) > 0
    about = pd.DataFrame([
        ("What this is", "Internal clients (Client Propensity extract) with company size joined on, from the AMER / APAC "
                         "growth-opportunity research files. Built by apollo_lead_grading/client_size.py."),
        ("Built", dt.date.today().isoformat()),
        ("Client accounts", f"{sources['accounts']} ({n} accounts, {active.sum()} with seats now)"),
        ("Name / industry / region", sources["priority"]),
        ("seats_now_zero", "0 seats in the dashboard's current count (MyStaff Total Staff). Kept: the growth files list "
                           "some of these, likely recent churn or a count lag. Exclude them for an active-client view."),
        ("Size source", ", ".join(sources["size_files"])),
        ("Accounts with size", f"{clients['has_size'].sum()} of {n}; {clients.loc[active, 'has_size'].sum()} of "
                               f"{active.sum()} with seats now"),
        ("Rule: which figure", "The first number or range in the text (years skipped; revenue needs a currency or unit)."),
        ("Rule: point value", "Geometric mean of low and high. '<X' = X/2. 'X+' = X."),
        ("Rule: revenue", "Converted to USD (Apollo's revenue field on the leads is USD). Bare '$' = HQ country's dollar. "
                          "FX: " + ", ".join(f"{k} {v}" for k, v in FX_TO_USD.items() if k != "USD")),
        ("Rule: bands", "Point value -> standard bucket. employee_band = LinkedIn / Apollo bands: "
                        + ", ".join(b for _, b in BAND_EDGES) + ". revenue_band (USD) = ZoomInfo-style brackets: "
                        + ", ".join(b for _, b in REVENUE_EDGES) + ". *_band_order sorts them (1 = smallest); "
                        "*_band_spans = TRUE when the raw range crosses a bucket edge."),
        ("basis", "reported = filing / annual report / ASX / press release; band only = a LinkedIn-style band; "
                  "inferred = researcher's judgement; estimate = third-party data provider"),
        ("needs_review", "Why a person should check the row: onshore only, group / parent / network figure, "
                         "includes Cloudstaff or offshore staff, defunct / acquired, wide range (>5x), no figure"),
        ("Caveat", "Size is today's (2024-2026), not size when the client signed. Client headcount may or may not "
                   "include their Cloudstaff seats."),
    ], columns=["item", "value"])
    review = size.loc[size["needs_review"], ["shortcode", "client_name", "employees", "employees_review", "employees_raw",
                                             "revenue_usd", "revenue_review", "revenue_raw"]]
    unmatched = size.loc[~size["shortcode"].isin(clients["shortcode"]), ["shortcode", "client_name", "source_file"]]
    sheets = {"About": about, "clients": clients, "size_needs_review": review, "size_not_in_client_data": unmatched}
    with pd.ExcelWriter(dest, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "B2" if name != "About" else "A2"
            if name != "About":
                ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(df.columns, 1):
                width = 90 if col in ("value",) else 60 if col.endswith("_raw") else min(40, max(10, len(col) + 2))
                ws.column_dimensions[ws.cell(1, i).column_letter].width = width
            for c in ws[1]:
                c.font = Font(bold=True)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yoga-dir", type=Path, default=YOGA_DIR)
    args = ap.parse_args()

    frames = []
    for f in sorted(args.yoga_dir.glob("*-growth-opportunity-*.csv")):
        d = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
        frames.append(d.assign(_file=f.name, _region=f.name.split("-")[0].upper()))
    if not frames:
        raise SystemExit(f"no *-growth-opportunity-*.csv in {args.yoga_dir}")
    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame([parse_row(r) for r in raw.to_dict("records")])

    internal, internal_src = load_internal()
    if internal is not None:
        out = out.merge(internal, on="shortcode", how="left", indicator="_m")
        out["in_client_data"] = out.pop("_m").eq("both")

    stamp = dt.date.today().isoformat()
    dest = args.yoga_dir / f"client_size_{stamp}.csv"
    out.to_csv(dest, index=False, encoding="utf-8-sig")

    n = len(out)
    print(f"{n} clients from {len(frames)} files -> {dest}")
    for fld in ("revenue_usd", "employees"):
        print(f"  {fld}: {out[fld].notna().sum()} parsed ({out[fld].notna().mean():.0%})")
    print("  revenue from:", out["revenue_from"].value_counts().to_dict())
    print("  employees from:", out["employees_from"].value_counts().to_dict())
    print("  revenue currency:", out["revenue_currency"].value_counts(dropna=False).to_dict())
    print("  employee band:", out["employee_band"].value_counts(dropna=False).to_dict())
    print("  revenue band:", out["revenue_band"].value_counts(dropna=False).to_dict())
    print(f"  needs review: {out['needs_review'].sum()}")
    if internal is not None:
        print(f"  matched to client data ({internal_src}): {out['in_client_data'].sum()} / {n}")
        clients, acc_src, pl_src = client_table(out)
        xl = write_workbook(args.yoga_dir / f"clients_with_size_{stamp}.xlsx", clients, out,
                            {"accounts": acc_src, "priority": pl_src, "size_files": sorted(out["source_file"].unique())})
        active = clients["seats_current"].fillna(0) > 0
        print(f"{len(clients)} client accounts ({active.sum()} with seats now) -> {xl}")
        print(f"  with size: {clients['has_size'].sum()} all, {clients.loc[active, 'has_size'].sum()} with seats now")


if __name__ == "__main__":
    main()
