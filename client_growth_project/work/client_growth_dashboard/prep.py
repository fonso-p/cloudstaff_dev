"""Client growth dashboard: data prep.

Reads (never edits):
  - SC Engagement List (staff stints)               -> the source of truth for seats, starts, churn, start month
  - mystaff 1005 v2.xlsx, sheet "MyStaff (2)"       -> client list (to 2 Oct 2026): Region, Custom_Division (Hubspot),
                                                      Industry Roll Up / Hubspot, Active, Internal, Total Staff, first staff date
  - mystaff 1005 v2.xlsx, sheet "Region Reference"  -> cross-check only (differences listed in QA)
  - 2026 New Monthly Billed Report                  -> role titles (for initial function), via icp_prep helpers
Writes to data/: client_reference.csv, client_profile.csv, client_monthly.csv, client_monthly.json,
                 qa_excluded.csv, qa_flags.csv, qa_mystaff_differences.csv, qa_region_reference_differences.csv

Run from the project root:  python work/client_growth_dashboard/prep.py
Plan: /Users/jobso/.claude/plans/recreate-it-insted-of-hidden-treasure.md (approved 2026-10-10)
"""
import json
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "work", "icp_growth_potential"))
import icp_prep as P  # role matching, function mapping, seat helpers  # noqa: E402

# ---------------------------------------------------------------- settings (edit these for a refresh)
STAFF_SRC = "data/Organic rate/SC Engagement List2026-09-29 11_25_26.xlsx"
CLIENT_SRC = "data/Organic rate/mystaff 1005 v2.xlsx"
CLIENT_SHEET = "MyStaff (2)"                # current MyStaff export (Date column runs to 2026-10-02)
REF_SHEET = "Region Reference"              # cross-check only
EXTRACT = pd.Timestamp("2026-09-29")        # engagement list extract date (file name)
COHORT_FROM = pd.Period("2020-01", "M")     # first client start month in scope
LAST_MONTH = pd.Period("2026-09", "M")      # last month in the monthly table (partial)
OUT = "data"

NAMED_INTERNAL = {"CLOUDSTAFF", "CLOUDSTAFFINC", "CSNOW", "OPAINTBIZ", "RTGBS", "RTGQA", "05655543", "5655543", "CSFRLNCR"}
EXCL_REGION = {"INTERNAL", "TEST", "-", "VAR"}
EXCL_DIVISION = {"HUB", "CS - INTERNAL", "TEST ACCOUNT", "NEWLY REGISTERED"}
OPTI_DIVISIONS = {"OPAU", "OPUS", "OPEM", "OPTI"}


def clean(v):
    """Trimmed text; NaN/None -> ''."""
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip()


def json_safe(o):
    """Recursively turn NaN/NaT/numpy values into JSON-safe Python values (NaN -> null)."""
    if isinstance(o, dict):
        return {str(k): json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if np.isnan(o) else float(o)
    if o is pd.NaT or (isinstance(o, str) and o in ("nan", "NaT")):
        return None
    if isinstance(o, pd.Timestamp):
        return o.isoformat()[:10]
    return o


# ---------------------------------------------------------------- 1 load sources
def load_staff():
    s = pd.read_excel(STAFF_SRC, dtype=object)
    s["row"] = np.arange(2, len(s) + 2)                      # Excel row number in the source file
    s["sc"] = s["Shortcode"].map(clean)
    s["ed"] = pd.to_datetime(s["Engagement Date"], errors="coerce")
    s["dd"] = pd.to_datetime(s["Disengagement Date"], errors="coerce")
    s["valid"] = s["dd"].isna() | (s["dd"] >= s["ed"])
    s["dup"] = s.drop(columns=["row"]).astype(str).duplicated(keep="first")
    return s


def build_reference(staff_codes):
    """One row per shortcode from MyStaff (2): region, brand, Custom Division, industry roll-up, Active, Internal."""
    M = pd.read_excel(CLIENT_SRC, sheet_name=CLIENT_SHEET, dtype=str).dropna(how="all")
    M["sc"] = M["Shortcode"].map(clean)
    M = M.drop_duplicates("sc").set_index("sc")
    R = pd.read_excel(CLIENT_SRC, sheet_name=REF_SHEET, dtype=str).dropna(how="all")
    R["sc"] = R["Client Shortcode"].map(clean)
    R = R.drop_duplicates("sc").set_index("sc")

    def val(sc, col):
        return clean(M.at[sc, col]) if sc in M.index else ""

    rows, ref_diff = [], []
    for sc in sorted(staff_codes):
        region_raw, division = val(sc, "Region"), val(sc, "Custom_Division (Hubspot)")
        ind, isrc = val(sc, "Industry Roll Up"), "Industry Roll Up"
        if ind in ("", "-", "0"):
            ind, isrc = val(sc, "Industry Hubspot"), "Industry Hubspot"
            ind = "" if ind in ("-", "0") else ind
        reg = region_raw.upper()
        reg = {"EMEA": "AMER"}.get(reg, reg)                    # EMEA folded into AMER (agreed)
        brand = "OPTI" if (reg == "OPTI" or division.upper() in OPTI_DIVISIONS) else "Cloudstaff"
        if brand == "OPTI":
            reg = "OPTI"                                        # OPTI analysed as its own region (agreed)
        div_clean = division
        if division in ("", "-") or division.upper() in ("APAC", "AMER", "EMEA"):
            div_clean = f"Unassigned ({reg or 'Unknown'})"
        rows.append({"shortcode": sc, "in_mystaff": sc in M.index, "client_ref_name": val(sc, "Client"),
                     "region_raw": region_raw, "region": reg or "Unknown", "brand": brand,
                     "custom_division_raw": division, "custom_division": div_clean,
                     "industry_rollup": ind or "Unknown", "industry_source": isrc if ind else "none",
                     "active_flag": val(sc, "Active") if val(sc, "Active") in ("Yes", "No") else "Unknown",
                     "internal_flag": val(sc, "Internal (Yes / No)"),
                     "mystaff_total_staff": val(sc, "Total Staff"),
                     "mystaff_first_staff_date": val(sc, "Date of First Staff Engagement")})
        # cross-check against the Region Reference sheet (flag only)
        if sc in R.index:
            for col_m, col_r in [("Region", "Region"), ("Custom_Division (Hubspot)", "Custom Division"), ("Active", "Active?")]:
                a_, b_ = val(sc, col_m), clean(R.at[sc, col_r])
                if a_.upper() != b_.upper() and not (a_ in ("", "-") and b_ in ("", "-")):
                    ref_diff.append({"shortcode": sc, "field": col_m, "mystaff_2": a_, "region_reference": b_})
    pd.DataFrame(ref_diff).to_csv(f"{OUT}/qa_region_reference_differences.csv", index=False)
    return pd.DataFrame(rows).set_index("shortcode")


# ---------------------------------------------------------------- 2 scope and exclusions
def exclusion_reason(sc, name, ref, hub_share, rows_per_sc):
    """Why a shortcode is out of scope ('' = in scope). Order = first rule that applies."""
    if sc == "":
        return "Blank shortcode"
    if sc == "CSTREENGAGE":
        return "Disengaged Staff Pool (CSTREENGAGE)"
    if sc.startswith("CSS") and not name.upper().startswith("CS ") and rows_per_sc[sc] == 1:
        return "Test record (single-row CSS code)"
    if sc in NAMED_INTERNAL or re.match(r"(?i)^(CS |CSDEVS|Ojt )", name) or re.search(r"(?i)cloudstaff|ready ?to ?go", name):
        return "Internal unit (name rule, approved 2026-09-30)"
    if hub_share.get(sc, 0) >= 0.5:
        return "Internal unit (50%+ Hub rows)"
    r = ref.loc[sc]                                         # not in MyStaff: kept, region "Unknown", listed in QA (plan step 1)
    if r["internal_flag"] == "Yes":
        return "Internal = Yes in MyStaff"
    if r["region_raw"].upper() in EXCL_REGION:
        return f"Region tagged {r['region_raw']}"
    if r["custom_division_raw"].upper() in EXCL_DIVISION:
        return f"Custom Division {r['custom_division_raw']}"
    if r["industry_rollup"].upper().startswith(("CLOUDSTAFF", "TEST RECORD")):
        return f"Industry roll-up {r['industry_rollup']}"
    return ""


def main():
    s = load_staff()
    N = len(s)
    names = s.groupby("sc")["Client Name"].first().map(clean)
    hub_share = s["Category"].eq("Hub").groupby(s["sc"]).mean().to_dict()
    rows_per_sc = s["sc"].value_counts()
    ref = build_reference(set(s["sc"]) - {""})
    reason = {sc: exclusion_reason(sc, names.get(sc, ""), ref, hub_share, rows_per_sc) if sc else "Blank shortcode"
              for sc in s["sc"].unique()}
    s["excl"] = s["sc"].map(reason)
    s.loc[s["dup"] & s["excl"].eq(""), "excl"] = "Exact duplicate row"

    # client start month = first valid Engagement Date (engagement list is the basis)
    ok = s["excl"].eq("") & s["valid"]
    start = s[ok].groupby("sc")["ed"].min()
    no_valid = set(s.loc[s["excl"].eq(""), "sc"]) - set(start.index)
    # no valid stint = no start month: counted with the never-staffed MyStaff clients (Jobs, 2026-10-10); rows still listed in QA
    s.loc[s["sc"].isin(no_valid) & s["excl"].eq(""), "excl"] = "Never staffed: only stint ends before it starts (counted as never staffed)"
    pre = set(start[start.dt.to_period("M") < COHORT_FROM].index)
    s.loc[s["sc"].isin(pre) & s["excl"].eq(""), "excl"] = f"Client started before {COHORT_FROM}"
    s["inc"] = s["excl"].eq("")
    start = start[~start.index.isin(pre)]

    # ---------------------------------------------------------------- 3 QA outputs
    qa_ex = (s[~s["inc"]].groupby(["excl", "sc"]).agg(client=("Client Name", "first"), rows=("row", "size"))
             .reset_index().rename(columns={"excl": "reason", "sc": "shortcode"}))
    qa_ex["evidence"] = qa_ex["shortcode"].map(lambda c: f"region={ref.at[c, 'region_raw']}; internal={ref.at[c, 'internal_flag']}; "
                                                         f"division={ref.at[c, 'custom_division_raw']}" if c in ref.index else "")
    qa_ex.to_csv(f"{OUT}/qa_excluded.csv", index=False)
    inc = s[s["inc"]]
    # flags cover ALL source rows; 'excluded_reason' shows whether the row is also out of scope
    flags = pd.concat([
        s[~s["valid"]].assign(flag="Disengagement Date before Engagement Date (not counted as seat/churn)"),
        s[s["ed"] > EXTRACT].assign(flag="Engagement Date after extract date"),
        s[s["dd"].isna() & s["Engagement Status"].eq("disengage")].assign(flag="Status disengage but no Disengagement Date (treated as active)"),
        s[s["Engagement Status"].eq("bench")].assign(flag="Engagement Status bench (dates used as given)"),
    ]).rename(columns={"excl": "excluded_reason"})
    flags["in_scope"] = flags["excluded_reason"].eq("")
    flags = flags[["flag", "in_scope", "excluded_reason", "row", "sc", "Client Name", "CSID", "Engagement ID", "Engagement Date",
                   "Disengagement Date", "Engagement Status"]]
    flags.to_csv(f"{OUT}/qa_flags.csv", index=False)

    # staff on the books on the extract date, by where they sit in this analysis (to reconcile with headcount reports)
    on = s[(s["ed"] <= EXTRACT) & (s["dd"].isna() | (s["dd"] >= EXTRACT))]
    on_bucket = np.where(on["inc"], "In the dashboard (clients started from " + str(COHORT_FROM) + ")", on["excl"])
    active_recon = (pd.crosstab(pd.Series(on_bucket, index=on.index, name="where"), on["Category"].fillna("Blank"))
                    .assign(Total=lambda d: d.sum(axis=1)).sort_values("Total", ascending=False).reset_index().to_dict(orient="records"))

    # ---------------------------------------------------------------- 4 monthly table (valid stints of in-scope clients)
    st = inc[inc["valid"]][["sc", "ed", "dd", "row", "CSID", "First Name", "Last Name", "Category"]].copy()
    st["sm"], st["em"] = st["ed"].dt.to_period("M"), st["dd"].dt.to_period("M")
    months = pd.period_range(COHORT_FROM, LAST_MONTH, freq="M")
    starts = st.groupby(["sc", "sm"]).size()
    churn = st[st["dd"].notna()].groupby(["sc", "em"]).size()
    recs = []
    for sc, sdt in start.items():
        m0 = sdt.to_period("M")
        act = 0
        for i, m in enumerate(pd.period_range(m0, LAST_MONTH, freq="M"), start=1):
            a, c = int(starts.get((sc, m), 0)), int(churn.get((sc, m), 0))
            act += a - c
            recs.append((sc, str(m), i, a, c, a - c, act))
    mon = pd.DataFrame(recs, columns=["shortcode", "month", "months_since_start", "starts", "churned", "net_seats", "active_month_end"])

    # independent check: active at month end recount from the stint dates (start <= month end and (no end or end > month end))
    chk = mon.groupby("shortcode").tail(1).set_index("shortcode")["active_month_end"]
    me = LAST_MONTH.to_timestamp(how="end").normalize()
    recount = st[(st["ed"] <= me) & (st["dd"].isna() | (st["dd"] > me))].groupby("sc").size().reindex(chk.index, fill_value=0)
    mismatch = int((chk != recount).sum())

    # ---------------------------------------------------------------- 5 client profile (account / ICP fields)
    stv = st.rename(columns={"sc": "sc"})
    peak_date5 = P.peak_and_date5(stv[["sc", "ed", "dd"]], 5)
    peak_date10 = P.peak_and_date5(stv[["sc", "ed", "dd"]], 10)
    idx = start.index
    prof = pd.DataFrame(index=idx)
    prof["start_date"] = start
    prof["start_month"] = start.dt.to_period("M").astype(str)
    me1 = (start.dt.to_period("M").dt.to_timestamp(how="end")).dt.normalize()
    prof["starting_seats"] = mon[mon["months_since_start"] == 1].set_index("shortcode")["active_month_end"].reindex(idx)
    prof["seats_day90"] = P.seats_on(stv[["sc", "ed", "dd"]], idx, start + pd.Timedelta(days=90))
    prof["peak_seats"] = peak_date5[0].reindex(idx).fillna(0).astype(int)
    prof["months_to_5"] = ((peak_date5[1].reindex(idx) - start).dt.days / 30.4375).round(1)
    prof["months_to_10"] = ((peak_date10[1].reindex(idx) - start).dt.days / 30.4375).round(1)
    d5, d10 = peak_date5[1].reindex(idx), peak_date10[1].reindex(idx)
    prof["date_5"] = d5.dt.strftime("%Y-%m-%d").where(d5.notna(), None)        # first day with 5+ staff at the same time
    prof["days_to_5"] = (d5 - start).dt.days
    prof["date_10"] = d10.dt.strftime("%Y-%m-%d").where(d10.notna(), None)
    last = mon.groupby("shortcode").tail(1).set_index("shortcode")
    prof["current_seats"] = last["active_month_end"].reindex(idx)
    g = mon.groupby("shortcode")
    prof["total_starts"], prof["total_churned"] = g["starts"].sum(), g["churned"].sum()
    prof["net_seats"] = g["net_seats"].sum()
    pk = mon.loc[mon.groupby("shortcode")["net_seats"].idxmax()].set_index("shortcode")
    prof["peak_net_month"], prof["peak_net_value"] = pk["month"], pk["net_seats"]
    prof["months_active"] = mon[mon["active_month_end"] > 0].groupby("shortcode").size().reindex(idx, fill_value=0)
    prof["months_observed"] = g.size()
    prof["retained"] = np.where(prof["current_seats"] > 0, "Retained", "Churned")
    # path to 5 seats: the four groups agreed for the High-Growth Account Profile (Jobs, 2026-10-08; fast = within 183 days)
    prof["path_group"] = np.select([prof["days_to_5"] <= 183, prof["days_to_5"] > 183, prof["current_seats"] > 0],
                                   ["Fast to 5 (within 6 months)", "Slow to 5 (after 6 months)", "Not yet at 5, still active"], "Churned without reaching 5")

    # roles -> initial function, second function, same vs new function expansion
    rr = st.reset_index(drop=True).copy()
    rr["pos"] = rr["row"]
    rr["nm"] = (rr["First Name"].map(clean) + rr["Last Name"].map(clean)).map(P.norm_name)
    roles = P.load_roles()
    m = P.match_roles(rr[["pos", "sc", "nm", "ed"]], roles)
    rr["role"] = rr["pos"].map(m["role"])
    rr["function"] = rr["role"].map(P.role_function)
    rr["day"] = (rr["ed"] - rr["sc"].map(start)).dt.days
    first30 = rr[(rr["day"] < 30) & (rr["function"] != "Unknown")]
    cnt = (first30.groupby(["sc", "function"]).agg(n=("pos", "size"), first=("ed", "min")).reset_index()
           .sort_values(["sc", "n", "first"], ascending=[True, False, True]).drop_duplicates("sc"))
    prof["initial_function"] = cnt.set_index("sc")["function"].reindex(idx).fillna("Unknown")
    later = rr[rr["day"] >= 30].copy()
    later["init"] = later["sc"].map(prof["initial_function"])
    later["kind"] = np.select([later["function"].eq("Unknown") | later["init"].eq("Unknown"), later["function"].eq(later["init"])],
                              ["Unknown", "Same function"], "New function")
    for k, col in [("Same function", "adds_same_function"), ("New function", "adds_new_function"), ("Unknown", "adds_unknown_function")]:
        prof[col] = later[later["kind"] == k].groupby("sc").size().reindex(idx, fill_value=0)
    prof["months_to_2nd_function"] = ((later[later["kind"] == "New function"].groupby("sc")["ed"].min().reindex(idx) - start).dt.days
                                      / 30.4375).round(1)
    role_match_rate = float(rr["role"].notna().mean())
    role_by_year = (rr.assign(y=rr["ed"].dt.year, hit=rr["role"].notna()).groupby("y")["hit"].agg(["size", "mean"])
                    .rename(columns={"size": "stints", "mean": "match_rate"}).reset_index().to_dict(orient="records"))

    # tags + status (Active flag from MyStaff, seats from the engagement list)
    prof = prof.join(ref[["client_ref_name", "region", "brand", "custom_division", "industry_rollup", "active_flag",
                          "mystaff_total_staff", "mystaff_first_staff_date"]])
    prof["client_name"] = names.reindex(idx)
    prof["status"] = np.select([(prof["active_flag"] == "Yes") & (prof["current_seats"] > 0),
                                (prof["active_flag"] == "Yes") & (prof["current_seats"] == 0),
                                prof["active_flag"] == "No"],
                               ["Active with staff", "Active, 0 staff", "Inactive"], "Unknown flag")
    prof["company_size"] = "not available"

    # ---------------------------------------------------------------- 6 MyStaff vs engagement-list differences (flag only)
    # MyStaff export runs to ~2 Oct 2026, the engagement list to 29 Sep 2026: small timing gaps are expected.
    eng_now = st[(st["ed"] <= EXTRACT) & (st["dd"].isna() | (st["dd"] >= EXTRACT))].groupby("sc").size().reindex(idx, fill_value=0)
    d = prof.copy()
    d["engagement_list_staff"] = eng_now
    d["mystaff_staff"] = pd.to_numeric(d["mystaff_total_staff"], errors="coerce")
    d["staff_diff"] = d["mystaff_staff"] - d["engagement_list_staff"]
    d["mystaff_first_month"] = pd.to_datetime(d["mystaff_first_staff_date"], errors="coerce").dt.to_period("M").astype(str)
    d["start_month_diff"] = d["mystaff_first_month"].ne(d["start_month"]) & d["mystaff_first_staff_date"].ne("")
    diff = d[(d["staff_diff"].fillna(0) != 0) | d["start_month_diff"]][["client_name", "region", "start_month", "mystaff_first_month",
                                                                         "engagement_list_staff", "mystaff_staff", "staff_diff"]]
    diff.to_csv(f"{OUT}/qa_mystaff_differences.csv", index_label="shortcode")

    # clients in MyStaff (2) with no staff ever in the engagement list (no start month, separate count only)
    allm = pd.read_excel(CLIENT_SRC, sheet_name=CLIENT_SHEET, dtype=str, usecols=["Shortcode", "Client", "Active", "Internal (Yes / No)", "Region"])
    allm["sc"] = allm["Shortcode"].map(clean)
    allm = allm[allm["sc"].ne("")]                            # the sheet carries ~1M blank rows
    ns = allm[(~allm["sc"].isin(set(s["sc"])) | allm["sc"].isin(no_valid)) & allm["Internal (Yes / No)"].ne("Yes") & ~allm["Region"].fillna("").str.upper().isin(EXCL_REGION)]
    never_staffed = {"total": int(len(ns)), "active_yes": int((ns["Active"] == "Yes").sum()),
                     "no_valid_stint": sorted(no_valid)}

    # same client name on different shortcodes (kept separate: the shortcode is the client unit)
    # every name a shortcode appears under (engagement list rows and MyStaff), compared without legal suffixes (as in Phase 1)
    nm = pd.concat([pd.DataFrame({"shortcode": s["sc"], "client": s["Client Name"].map(clean), "name_source": "engagement list"}),
                    pd.DataFrame({"shortcode": allm["sc"], "client": allm["Client"].map(clean), "name_source": "MyStaff"})])   # every MyStaff client
    nm = nm[nm["shortcode"].ne("") & nm["client"].ne("")].drop_duplicates(["shortcode", "client"])
    suffix = r"\b(pty|ltd|llc|inc|limited|co|corp|corporation|the|group|holdings|pte|plc)\b"
    nm["key"] = (nm["client"].str.lower().str.replace(r"[^a-z0-9 ]", " ", regex=True).str.replace(suffix, " ", regex=True)
                 .str.split().str.join(" "))
    nm["in_scope"] = nm["shortcode"].isin(idx)
    nm["has_staff"] = nm["shortcode"].isin(set(s["sc"])) & ~nm["shortcode"].isin(no_valid)
    nm["excluded_reason"] = nm["shortcode"].map(s.groupby("sc")["excl"].first()).fillna("")
    multi = nm.groupby("key")["shortcode"].nunique()
    pairs = nm[nm["key"].isin(multi[multi > 1].index) & nm["key"].ne("")].sort_values(["key", "shortcode"]).drop(columns="key")
    pairs.to_csv(f"{OUT}/qa_name_pairs.csv", index=False)
    staffed_keys = set(nm.loc[nm["has_staff"], "key"])          # name groups with at least one staffed shortcode
    in_staffed = nm[nm["key"].isin(staffed_keys) & nm["key"].isin(multi[multi > 1].index)]
    never_staffed["share_name_with_staffed_client"] = sorted(set(in_staffed.loc[in_staffed["shortcode"].isin(ns["sc"]), "shortcode"]))
    not_in_mystaff = sorted(ref.index[~ref["in_mystaff"]].intersection(idx))

    # ---------------------------------------------------------------- 7 save
    prof = prof.drop(columns=["mystaff_total_staff", "mystaff_first_staff_date"])
    ref.to_csv(f"{OUT}/client_reference.csv")
    prof.to_csv(f"{OUT}/client_profile.csv", index_label="shortcode")
    meta = prof[["client_name", "region", "brand", "custom_division", "industry_rollup", "active_flag", "status"]]
    mon_out = mon.merge(meta, left_on="shortcode", right_index=True)
    mon_out = mon_out[["client_name", "shortcode", "region", "brand", "custom_division", "industry_rollup", "active_flag", "status",
                       "month", "months_since_start", "starts", "churned", "net_seats", "active_month_end"]]
    mon_out.to_csv(f"{OUT}/client_monthly.csv", index=False)
    # compact JSON: per-client metadata + month arrays (index 0 = start month)
    clients = []
    for sc, p in prof.iterrows():
        clients.append({k: (None if (isinstance(v, float) and np.isnan(v)) else (v.isoformat()[:10] if isinstance(v, pd.Timestamp) else
                        (int(v) if isinstance(v, (np.integer,)) else v))) for k, v in p.items()} | {"shortcode": sc})
    arr = {sc: (grp["starts"].tolist(), grp["churned"].tolist()) for sc, grp in mon.groupby("shortcode", sort=False)}
    for c in clients:
        c["starts"], c["churn"] = arr[c["shortcode"]]
    qa = {"source_rows": N, "included_rows": int(s["inc"].sum()),
          "excluded": qa_ex.groupby("reason")["rows"].sum().to_dict(),
          "excluded_lists": qa_ex.to_dict(orient="records"),
          "flags": {f"{k[0]} | in scope: {k[1]}": int(v) for k, v in flags.groupby(["flag", "in_scope"]).size().items()},
          "flag_rows": flags.astype(str).to_dict(orient="records"),
          "mystaff_differences": {"clients_compared": int(len(d)), "staff_count_differs": int((d["staff_diff"].fillna(0) != 0).sum()),
                                  "start_month_differs": int(d["start_month_diff"].sum()), "compared_at": str(EXTRACT.date())},
          "mystaff_diff_rows": diff.reset_index().rename(columns={"index": "shortcode"}).astype(str).to_dict(orient="records"),
          "role_match_rate": role_match_rate, "role_match_by_year": role_by_year, "active_reconciliation": active_recon,
          "active_reconciliation_date": str(EXTRACT.date()),
          "name_pairs": pairs.to_dict(orient="records"), "not_in_mystaff_kept": not_in_mystaff,
          "never_staffed_mystaff_clients": never_staffed}
    json.dump(json_safe({"generated": pd.Timestamp.now().isoformat(timespec="seconds"), "extract": str(EXTRACT.date()),
                         "first_month": str(COHORT_FROM), "last_month": str(LAST_MONTH), "last_month_partial": True,
                         "clients": clients, "qa": qa}), open(f"{OUT}/client_monthly.json", "w"), default=str, allow_nan=False)

    # ---------------------------------------------------------------- 8 summary
    print(f"Source rows {N:,} | included {int(s['inc'].sum()):,} | excluded {int((~s['inc']).sum()):,} (ties to source: "
          f"{int(s['inc'].sum()) + int((~s['inc']).sum()) == N})")
    print("\nExcluded rows by reason:\n" + qa_ex.groupby("reason").agg(shortcodes=("shortcode", "size"), rows=("rows", "sum")).to_string())
    print("\nFlags (all source rows; in_scope = row is in the analysis):\n" + flags.groupby(["flag", "in_scope"]).size().to_string())
    print(f"\nClients in scope (start {COHORT_FROM} to {LAST_MONTH}): {len(prof):,}")
    print(pd.crosstab(prof["region"], prof["status"], margins=True).to_string())
    print("\nClients by start year and region:\n" + pd.crosstab(prof["start_date"].dt.year, prof["region"], margins=True).to_string())
    print("\nTop Custom Divisions:\n" + prof["custom_division"].value_counts().head(25).to_string())
    print(f"\nTotal active staff now (end {LAST_MONTH}): {int(prof['current_seats'].sum()):,}")
    print(f"Reconciliation: sum of monthly net seats = current seats for every client: {bool((prof['net_seats'] == prof['current_seats']).all())}; "
          f"independent month-end recount mismatches: {mismatch}")
    print(f"Role match rate (in-scope valid stints): {role_match_rate:.1%}")
    print(f"MyStaff (2) vs engagement list at {EXTRACT.date()}: compared {len(d):,} clients; staff count differs "
          f"{int((d['staff_diff'].fillna(0) != 0).sum()):,} (mostly timing, MyStaff runs to 2 Oct); first-staff month differs "
          f"{int(d['start_month_diff'].sum()):,}")
    print(f"Unknown region: {int((prof['region'] == 'Unknown').sum())} | MyStaff clients never staffed (non-internal): {never_staffed}")
    print(f"Region Reference cross-check differences: {len(pd.read_csv(f'{OUT}/qa_region_reference_differences.csv'))} field values")
    print("\n10 random clients (spot-check against the source):")
    for sc in prof.sample(10, random_state=7).index:
        p = prof.loc[sc]
        print(f"\n{sc} | {p['client_name']} | {p['region']} | {p['custom_division']} | start {p['start_month']} | "
              f"current {p['current_seats']} | peak {p['peak_seats']}")
        print(mon[(mon["shortcode"] == sc) & ((mon["starts"] > 0) | (mon["churned"] > 0))]
              [["month", "months_since_start", "starts", "churned", "net_seats", "active_month_end"]].to_string(index=False))


if __name__ == "__main__":
    main()
