"""Early signal prediction: client feature table (what is known by day 90) and the three targets.

Scope and client list come from the approved client growth prep (data/client_profile.csv, commit 1bbef51):
clients whose first staff started Jan 2020 to Sep 2026, internal and test accounts excluded.
Stints come straight from the SC Engagement List; role titles from the billed report (icp_prep helpers, as in prep.py).

Every feature uses only stints and dates up to day 90 after the client's first start (day 0 = first Engagement Date).
Labels use what happened after that. Nothing measured after day 90 is a feature (plan section 4).
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "work", "icp_growth_potential"))
sys.path.insert(0, os.path.join(ROOT, "work", "client_growth_dashboard"))
import icp_prep as P  # noqa: E402  role matching and function families
import prep as CG     # noqa: E402  settings of the approved client growth prep (paths, extract date)

STAFF_SRC = CG.STAFF_SRC
EXTRACT = CG.EXTRACT                       # 2026-09-29
EARLY_DAY = 90                             # features use stints up to this day (approved 2026-10-10)
FAST_DAYS = 183
REGIONS = ["APAC", "AMER", "OPTI"]


def clean(v):
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip()


def stints(raw):
    """Valid, non-duplicate stints of in-scope clients, one row per source row (pos = 0-based file position)."""
    prof = pd.read_csv(os.path.join(ROOT, "data/client_profile.csv"), keep_default_na=False, na_values=[""])
    s = raw.copy()
    s["pos"] = np.arange(len(s))
    s["sc"] = s["Shortcode"].map(clean)
    s["ed"] = pd.to_datetime(s["Engagement Date"], errors="coerce")
    s["dd"] = pd.to_datetime(s["Disengagement Date"], errors="coerce")
    dup = raw.astype(str).duplicated(keep="first")
    s["include"] = s["sc"].isin(set(prof["shortcode"])) & ~dup.values
    s["valid"] = s["ed"].notna() & (s["dd"].isna() | (s["dd"] >= s["ed"]))
    start = pd.to_datetime(prof.set_index("shortcode")["start_date"])
    s["start"] = s["sc"].map(start)
    s["day"] = (s["ed"] - s["start"]).dt.days
    st = s[s["include"] & s["valid"]].copy()
    # role titles -> function (same matching as prep.py)
    st["nm"] = (st["First Name"].map(clean) + st["Last Name"].map(clean)).map(P.norm_name)
    m = P.match_roles(st[["pos", "sc", "nm", "ed"]], P.load_roles())
    st["role"] = st["pos"].map(m["role"])
    st["function"] = st["role"].map(P.role_function).fillna("Unknown")
    return s, st, prof


def active_on(st, day_offsets):
    """Staff on the books on start + d days (Engagement Date <= day <= Disengagement Date, or open), per client."""
    out = {}
    for d in day_offsets:
        t = st["start"] + pd.Timedelta(days=d)
        on = (st["ed"] <= t) & (st["dd"].isna() | (st["dd"] >= t))
        out[d] = on.groupby(st["sc"]).sum()
    return pd.DataFrame(out)


def peak_by_day(st, last_day):
    """Most staff on the books on any day from day 0 to last_day (event sweep; a stint counts on its start and end days)."""
    e = st[st["day"] <= last_day]
    ev = pd.concat([pd.DataFrame({"sc": e["sc"], "d": e["day"], "x": 1}),
                    pd.DataFrame({"sc": e["sc"], "d": (e["dd"] - e["start"]).dt.days + 1, "x": -1}).dropna()])
    ev = ev[ev["d"] <= last_day]
    ev = ev.groupby(["sc", "d"], as_index=False)["x"].sum().sort_values(["sc", "d"])
    ev["hc"] = ev.groupby("sc")["x"].cumsum()
    return ev.groupby("sc")["hc"].max()


def build_features(raw):
    """Client-level table: features known by day 90, ages, eligibility and the three targets."""
    s, st, prof = stints(raw)
    p = prof.set_index("shortcode")
    f = pd.DataFrame(index=p.index)
    f["client_name"] = p["client_name"]
    f["start_date"] = pd.to_datetime(p["start_date"])
    f["start_year"] = f["start_date"].dt.year
    f["start_quarter"] = "Q" + f["start_date"].dt.quarter.astype(str)
    f["age_days"] = (EXTRACT - f["start_date"]).dt.days
    f["region"] = p["region"]
    f["custom_division"] = p["custom_division"]
    f["industry"] = p["industry_rollup"]
    # ---- early signals (day 0 to day 90)
    seats = active_on(st, [30, 60, 90, 365, 730]).reindex(f.index, fill_value=0)
    f["seats_d30"], f["seats_d60"], f["seats_d90"] = seats[30], seats[60], seats[90]
    f["starting_seats"] = p["starting_seats"]                                   # staff at the end of month 1
    early = st[st["day"] < EARLY_DAY]
    g = early.groupby("sc")
    f["starts_d90"] = g.size().reindex(f.index, fill_value=0)
    f["starts_first_week"] = st[st["day"] < 7].groupby("sc").size().reindex(f.index, fill_value=0)
    f["adds_d31_90"] = st[(st["day"] >= 30) & (st["day"] < EARLY_DAY)].groupby("sc").size().reindex(f.index, fill_value=0)
    left = st[st["dd"].notna() & ((st["dd"] - st["start"]).dt.days < EARLY_DAY)]
    f["leavers_d90"] = left.groupby("sc").size().reindex(f.index, fill_value=0)
    f["peak_d90"] = peak_by_day(st, EARLY_DAY).reindex(f.index).fillna(0).astype(int)
    second = st.sort_values("ed").groupby("sc")["day"].apply(lambda d: d.iloc[1] if len(d) > 1 else np.nan)
    f["days_to_2nd_start"] = second.reindex(f.index)
    f["second_start_by_d90"] = (f["days_to_2nd_start"] < EARLY_DAY).astype(int)
    f["days_to_2nd_start_capped"] = f["days_to_2nd_start"].where(f["days_to_2nd_start"] < EARLY_DAY, EARLY_DAY)   # no 2nd start by day 90 = 90
    # Category (Engaged / RTG / Hub) is NOT used: it is a person-level current status, the same on every stint of a person and
    # almost always RTG only after a stint has ended, so it is not known at day 90 (reviewer round 1, confirmed 2026-10-10)
    f["functions_d90"] = early[early["function"] != "Unknown"].groupby("sc")["function"].nunique().reindex(f.index, fill_value=0)
    f["initial_function"] = p["initial_function"]
    f["function_known_d90"] = early.assign(k=early["function"] != "Unknown").groupby("sc")["k"].mean().reindex(f.index).fillna(0)
    # ---- outcomes (after day 90)
    f["days_to_5"] = p["days_to_5"]
    f["days_to_10"] = (pd.to_datetime(p["date_10"]) - f["start_date"]).dt.days
    f["seats_d365"], f["seats_d730"] = seats[365], seats[730]
    # Target A: reaches 5 within 12 months | aged 12+ months, had not reached 5 by day 90
    f["elig_A"] = (f["age_days"] >= 365) & ~(f["days_to_5"] <= EARLY_DAY)
    f["y_A"] = (f["days_to_5"] <= 365).astype(int)
    # Target B: reaches 10 within 24 months | aged 24+ months, had not reached 10 by day 90
    f["elig_B"] = (f["age_days"] >= 730) & ~(f["days_to_10"] <= EARLY_DAY)
    f["y_B"] = (f["days_to_10"] <= 730).astype(int)
    # Target C: keeps expanding | reached 5 within 12 months, aged 24+ months: staff on day 730 above staff on day 365
    f["elig_C"] = (f["age_days"] >= 730) & (f["days_to_5"] <= 365)
    f["y_C"] = (f["seats_d730"] > f["seats_d365"]).astype(int)
    # Watch list: clients 90 days to 12 months old (outcome for A not known yet)
    f["watch"] = (f["age_days"] >= EARLY_DAY) & (f["age_days"] < 365)
    f["reached5_by_d90"] = (f["days_to_5"] <= EARLY_DAY).astype(int)
    f["reached5_already"] = f["days_to_5"].notna().astype(int)        # reached 5 at any time up to the extract date
    return f, s, st


NUMERIC = ["seats_d30", "seats_d60", "seats_d90", "starting_seats", "starts_d90", "starts_first_week", "adds_d31_90", "leavers_d90",
           "peak_d90", "days_to_2nd_start_capped", "second_start_by_d90", "functions_d90", "function_known_d90"]
CATEGORICAL = ["region", "initial_function", "start_quarter"]
SENSITIVITY_TAGS = ["custom_division", "industry"]            # issue 1: today's MyStaff tags, sensitivity model only
FUNCTION_FEATURES = ["initial_function", "functions_d90", "function_known_d90"]   # issue 2: dropped in the no-function sensitivity model
SIZE_FEATURES = ["seats_d30", "seats_d60", "seats_d90", "starting_seats", "starts_d90", "starts_first_week", "adds_d31_90",
                 "leavers_d90", "peak_d90", "second_start_by_d90", "days_to_2nd_start_capped"]
# dropped in the "without staff and start counts" sensitivity model: every headcount, start or second-start signal (change log 2026-10-10)
