"""Lickimat replenishment: data engineering and scoring.

Steps (each is one function below, so a source can later be swapped for an API without touching the rest):
    1. load      read the Amazon inventory exports, Mich's reco sheets and the SKU economics
    2. harmonise map each market's column names to one schema; one row per market x snapshot x SKU
    3. sku map   base code per SKU; flag SKUs that do not fit the pattern and ASINs with several SKUs
    4. join      economics (SKU, then unique ASIN), Mich's reco (snapshot date, day/month swap fixed), previous snapshot
    5. rules     rules.assess() per row, plus exception flags
    6. checks    reconciliation counts for the QA page
    7. write     one JSON file for the dashboard

Usage:  .venv/Scripts/python.exe Lickimat/prep.py [--src DIR] [--out DIR]
Raw files are read from the Desktop project folder and outputs are written there, never into the repo.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules  # noqa: E402

DEFAULT_SRC = os.path.expanduser(r"~/Desktop/Projects/Client/Lickimat")
INV_FILE = "INVENTORY_RECOMMENDATION2.xlsx"
ECON_FILE = "LICKIMAT TABLE .xlsx"
CURRENCY = {"UK": "GBP", "US": "USD", "AU": "AUD", "DE": "EUR"}
ECON_MONTHS = {"UK": 12, "US": 15, "AU": 12, "DE": 12}   # window stated in each '<market> Table' sheet title

# ---- 2. one schema for all markets: target name -> candidate source columns (first found wins)
SCHEMA = {
    "snap": ["snapshot-date"], "sku": ["sku"], "asin": ["asin"], "name": ["product-name"],
    "avail": ["available"], "inb": ["inbound-quantity"], "inb_ship": ["inbound-shipped"],
    "unf": ["unfulfillable-quantity"],
    "s7": ["units-shipped-t7", "units-shipped-last-7-days"],
    "s30": ["units-shipped-t30", "units-shipped-last-30-days"],
    "s90": ["units-shipped-t90", "units-shipped-last-90-days"],
    "price": ["your-price"], "sale_price": ["sales-price"], "featured": ["featuredoffer-price"],
    "alert": ["alert"],
    "amz": ["Recommended ship-in quantity", "recommended-order-quantity"],
}
AGED_COLS = ["inv-age-181-to-270-days", "inv-age-271-to-365-days", "inv-age-366-to-455-days", "inv-age-456-plus-days",
             "inventory-age-181-to-270-days", "inventory-age-271-to-365-days", "inventory-age-365-plus-days"]
NUMERIC = ["avail", "inb", "inb_ship", "unf", "s7", "s30", "s90", "price", "sale_price", "featured", "amz"]
FILLED_ZERO = ["avail", "inb", "inb_ship", "unf", "s7", "s30", "s90"]   # blank in the export = 0 units

# ---- 3. base code = the leading LickiMat product code; everything after it is a label/marketplace suffix.
# 'LM3001GN-DR-FBA-UK' -> 'LM3001GN'; 'LM-BTT-FBA-UK' -> 'LM-BTT'; 'LMS-CB-FBM-UK' -> 'LMS-CB'. Anything else is flagged.
BASE = re.compile(r"^(LM[A-Z]*-[A-Z0-9]+|LM[A-Z]*\d[A-Z0-9]*)", re.I)   # second form also covers pack codes (LMDB2, LMC1)


def base_code(sku):
    s = str(sku).strip().upper()
    hit = BASE.match(s)
    return (hit.group(1), True) if hit else (s, False)


def to_date(v):
    t = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(t) else t.date()


# ---------------------------------------------------------------- 1. load + 2. harmonise
def load_inventory(path, m, qa):
    raw = pd.read_excel(path, f"{m} RAW DATA")
    qa.append({"market": m, "step": "Amazon inventory export: source rows", "rows": len(raw)})
    out = pd.DataFrame()
    for k, cands in SCHEMA.items():
        col = next((c for c in cands if c in raw.columns), None)
        out[k] = raw[col] if col else None
    aged = [c for c in AGED_COLS if c in raw.columns]
    out["aged"] = raw[aged].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
    for k in NUMERIC:
        out[k] = pd.to_numeric(out[k], errors="coerce")
    nulls = int(out["avail"].isna().sum())
    if nulls:
        qa.append({"market": m, "step": "Available was blank, set to 0", "rows": nulls})
    out[FILLED_ZERO] = out[FILLED_ZERO].fillna(0)
    out["snap"] = out["snap"].map(to_date)
    out["m"] = m
    out["name"] = out["name"].fillna("(no name in export)")
    dup = int(out.duplicated(["snap", "sku"]).sum())
    qa.append({"market": m, "step": "Duplicate snapshot + SKU rows dropped", "rows": dup})
    out = out.drop_duplicates(["snap", "sku"])
    snaps = sorted(out["snap"].unique())
    out["sr"] = out["snap"].map({d: len(snaps) - 1 - i for i, d in enumerate(snaps)})   # 0 = latest
    qa.append({"market": m, "step": f"Snapshots found: {', '.join(d.isoformat() for d in snaps)}", "rows": len(snaps)})
    return out


def load_mich(path, m, snaps, qa):
    """Mich's dated reco log. Dates that match no snapshot are retried with day and month swapped."""
    r = pd.read_excel(path, f"{m} RECO", header=1)
    qcol = "Recommendation" if "Recommendation" in r.columns else r.columns[10]   # by name; position 10 (column K) as fallback
    r = r.rename(columns={qcol: "mich"})
    r["mich"] = pd.to_numeric(r["mich"], errors="coerce")
    r["d"] = r["Date"].map(to_date)
    snapset, fixed = set(snaps), 0

    def match(d):
        nonlocal fixed
        if d is None or d in snapset:
            return d
        try:
            sw = dt.date(d.year, d.day, d.month)
        except ValueError:
            return None
        if sw in snapset:
            fixed += 1
            return sw
        return None
    r["snap"] = r["d"].map(match)
    qa.append({"market": m, "step": "Mich reco rows: source", "rows": len(r)})
    qa.append({"market": m, "step": "Mich reco rows: date fixed (day/month swapped)", "rows": fixed})
    bad = r["snap"].isna() | r["SKU"].isna() | r["mich"].isna()
    qa.append({"market": m, "step": "Mich reco rows: dropped (no date, SKU or quantity)", "rows": int(bad.sum())})
    r = r[~bad].groupby(["snap", "SKU"], as_index=False)["mich"].sum().rename(columns={"SKU": "sku"})
    return r


def load_econ(path, m):
    e = pd.read_excel(path, f"{m} Report")
    e.columns = [c.lower() for c in e.columns]
    keep = {"sku": "sku", "asin": "asin", "net sales revenue": "rev", "net proceed total": "np",
            "net margin %": "margin", "net units sold": "units"}
    e = e[list(keep)].rename(columns=keep)
    for c in ["rev", "np", "margin", "units"]:
        e[c] = pd.to_numeric(e[c], errors="coerce")
    e["m"], e["cur"], e["months"] = m, CURRENCY[m], ECON_MONTHS[m]
    return e


# ---------------------------------------------------------------- 4. joins, 5. rules, flags
def join_econ(inv, econ, m, qa):
    cols = ["np", "margin", "rev", "eunits"]
    econ = econ.rename(columns={"units": "eunits"})
    by_sku = econ.set_index("sku")[cols]
    uniq_asin = econ[~econ["asin"].duplicated(keep=False)].set_index("asin")[cols]
    inv = inv.join(by_sku, on="sku")
    inv["econ"] = inv["np"].notna().map({True: "SKU", False: None})
    miss = inv["np"].isna()
    fb = inv.loc[miss, ["asin"]].join(uniq_asin, on="asin")
    for c in cols:
        inv.loc[miss, c] = fb[c]
    inv.loc[miss & inv["np"].notna(), "econ"] = "ASIN"
    latest = inv[inv["sr"] == 0]
    selling = latest[latest["s90"] > 0]
    for how in ["SKU", "ASIN"]:
        qa.append({"market": m, "step": f"Economics matched by {how} (latest snapshot, SKUs with 90-day sales)",
                   "rows": int((selling["econ"] == how).sum())})
    qa.append({"market": m, "step": "Economics not matched (latest snapshot, SKUs with 90-day sales)",
               "rows": int(selling["econ"].isna().sum())})
    return inv


def add_rules_and_flags(inv, m):
    inv = inv.sort_values(["sku", "snap"]).copy()
    g = inv.groupby("sku")
    inv["prev_inb"] = g["inb"].shift(1)
    inv["prev_ship"] = g["inb_ship"].shift(1)
    inv["prev_snap"] = g["snap"].shift(1)
    inv["sent"] = (inv["inb"] - inv["prev_inb"]).clip(lower=0)

    # several SKUs on one ASIN, each with stock or sales, in the same snapshot
    active = inv[(inv["avail"] + inv["inb"] + inv["s90"]) > 0]
    multi = active.groupby(["snap", "asin"])["sku"].transform("nunique")
    multi_keys = set(zip(active.loc[multi > 1, "snap"], active.loc[multi > 1, "sku"]))

    out = []
    for r in inv.itertuples(index=False):
        dem, cover, status, reco, why = rules.assess(m, r.avail, r.inb, r.s30, r.s90)
        if status == "Out of stock" and r.inb > 0:
            why += f" {r.inb:.0f} units inbound."
        flags = []
        if status == "Out of stock":
            flags.append("Out of stock")
        if r.unf > 0:
            flags.append("Unfulfillable units")
        if r.aged > 0:
            flags.append("Aged stock")
        if pd.notna(r.featured) and r.price and r.price > 0 and r.featured < r.price and not (r.sale_price and r.sale_price > 0):
            flags.append("Price check")
        if pd.notna(r.np) and r.np < 0 and reco > 0:
            flags.append("Losing money")
        if (r.snap, r.sku) in multi_keys:
            flags.append("Several SKUs on one ASIN")
        if (r.inb_ship > 0 and pd.notna(r.prev_ship) and r.inb_ship == r.prev_ship
                and (r.snap - r.prev_snap).days >= 10):
            flags.append("Inbound not moving")
        if isinstance(r.alert, str) and r.alert.strip():
            flags.append("Amazon alert")
        out.append({"dem": dem, "cover": cover, "status": status, "reco": reco, "why": why, "flags": flags})
    return pd.concat([inv.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def add_profit(inv, econ, m, qa):
    """Profit per unit and weekly profit at stake, used to order SKUs within a status (rules.RULES, "Priority number")."""
    ok = econ["units"] > 0
    median = (econ.loc[ok, "np"] / econ.loc[ok, "units"]).median()
    inv["ppu"] = (inv["np"] / inv["eunits"]).where(inv["eunits"] > 0)
    inv["ppu_est"] = inv["ppu"].isna()
    inv.loc[inv["ppu_est"], "ppu"] = median
    inv["pw"] = inv["dem"] * inv["ppu"]
    inv["pw_gbp"] = inv["pw"] * rules.FX_TO_GBP[m]
    inv["loss"] = inv["np"].notna() & (inv["np"] < 0)   # same test as the Losing money flag
    act = inv[(inv["sr"] == 0) & inv["status"].isin(rules.ACTION_STATUSES)]
    qa.append({"market": m, "step": f"Profit per unit: market median used (no economics or 0 units sold), latest snapshot, SKUs needing action. Median = {median:.2f} {CURRENCY[m]}",
               "rows": int(act["ppu_est"].sum())})
    qa.append({"market": m, "step": "Net proceeds negative: still restocked, flagged Losing money (latest snapshot, SKUs needing action)",
               "rows": int(act["loss"].sum())})
    return inv


# ---------------------------------------------------------------- 7. write
def clean(v):
    if v is None:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 2)
    if isinstance(v, (dt.date,)):
        return v.isoformat()
    if hasattr(v, "item"):
        return clean(v.item())
    return v


def main(src, out_dir):
    inv_path, econ_path = os.path.join(src, INV_FILE), os.path.join(src, ECON_FILE)
    qa, frames, econ_all, snaps, unmapped = [], [], [], {}, []
    for m in ["UK", "US", "AU", "DE"]:
        econ_all.append(load_econ(econ_path, m))
    econ_all = pd.concat(econ_all, ignore_index=True)

    for m in rules.MARKETS:
        inv = load_inventory(inv_path, m, qa)
        snaps[m] = sorted(d.isoformat() for d in inv["snap"].unique())
        b = inv["sku"].map(base_code)
        inv["base"], inv["base_ok"] = b.str[0], b.str[1]
        qa.append({"market": m, "step": "SKUs whose base code does not fit the LM pattern (kept, flagged)",
                   "rows": int(inv.loc[~inv["base_ok"], "sku"].nunique())})
        unmapped += [{"m": m, "sku": k} for k in sorted(inv.loc[~inv["base_ok"], "sku"].unique())]
        inv = join_econ(inv, econ_all[econ_all["m"] == m], m, qa)
        mich = load_mich(inv_path, m, set(inv["snap"]), qa)
        keys = set(zip(inv["snap"], inv["sku"]))
        lost = mich[[k not in keys for k in zip(mich["snap"], mich["sku"])]]
        inv = inv.merge(mich, on=["snap", "sku"], how="left")
        qa.append({"market": m, "step": "Mich reco rows matched to an inventory row", "rows": int(inv["mich"].notna().sum())})
        qa.append({"market": m, "step": f"Mich reco rows whose SKU is not in that day's export (dropped, {lost['mich'].sum():.0f} units)",
                   "rows": len(lost)})
        unmapped += [{"m": m, "sku": f"{s} (Mich reco, {d.isoformat()})"} for d, s in zip(lost["snap"], lost["sku"])]
        inv = add_rules_and_flags(inv, m)
        inv = add_profit(inv, econ_all[econ_all["m"] == m], m, qa)
        qa.append({"market": m, "step": "Rows in the dashboard (all snapshots)", "rows": len(inv)})
        frames.append(inv)

    df = pd.concat(frames, ignore_index=True)
    cols = ["m", "snap", "sr", "sku", "base", "base_ok", "asin", "name", "avail", "inb", "unf", "aged", "s7", "s30", "s90",
            "dem", "cover", "status", "reco", "amz", "mich", "sent", "price", "featured", "np", "margin", "econ", "eunits", "ppu", "ppu_est", "pw", "pw_gbp", "loss", "flags", "why"]
    rows = [{k: clean(v) for k, v in r.items()} for r in df[cols].to_dict("records")]

    econ_rows = [{k: clean(v) for k, v in r.items()}
                 for r in econ_all[["m", "cur", "months", "sku", "asin", "rev", "np", "margin", "units"]].to_dict("records")]
    latest = max(d for v in snaps.values() for d in v)
    data = {
        "meta": {"title": "Lickimat Replenishment", "subtitle": "Amazon FBA restock mock · UK, US, AU",
                 "source": "Amazon FBA inventory exports", "extract": latest,
                 "generated": dt.datetime.now().isoformat(timespec="seconds"), "snapshots": snaps,
                 "currency": CURRENCY, "econ_months": ECON_MONTHS},
        "settings": {"lead": rules.LEAD_TIME_WEEKS, "buffer": rules.BUFFER_WEEKS, "cap": rules.MAX_COVER_WEEKS,
                     "slow": rules.SLOW_SELLER_PER_WEEK, "slow_min": rules.SLOW_MIN_UNITS, "slow_topup": rules.SLOW_TOPUP_UNITS,
                     "fx": rules.FX_TO_GBP, "action": rules.ACTION_STATUSES, "keep_alive": rules.KEEP_ALIVE_UNITS},
        "reqs": [dict(zip(["req", "what", "from", "status"], q)) for q in rules.REQUIREMENTS],
        "rules": [dict(zip(["rule", "how", "source"], r)) for r in rules.RULES],
        "statuses": [dict(zip(["status", "meaning"], s)) for s in rules.STATUSES],
        "flags": [dict(zip(["flag", "meaning"], f)) for f in rules.FLAGS],
        "confirm": [dict(zip(["item", "assumed", "who"], c)) for c in rules.TO_CONFIRM],
        "de_assumptions": DE_ASSUMPTIONS,
        "qa": qa, "unmapped": unmapped, "rows": rows, "econ": econ_rows,
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "lickimat_replenishment.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    print(f"Wrote {path}: {len(rows)} rows, {len(econ_rows)} economics rows")
    return path


DE_ASSUMPTIONS = [
    "Source files are read in place from the Desktop project folder and never copied into the repo; the JSON and HTML are written to a Dashboards folder beside them.",
    "Each market's raw sheet stacks several Amazon exports; 'snapshot-date' separates them. One row per market × snapshot × SKU (no duplicates were found).",
    "Column names differ by market (e.g. units-shipped-t30 vs units-shipped-last-30-days, marketplace vs store). They are mapped to one schema; nothing is computed from market-only columns.",
    "Blank stock and sales cells mean 0 units (AU has 148 blank 'available' cells, mostly inactive listings, which the keep-listing-alive rule tops up to 2).",
    "Inbound = Amazon's inbound-quantity, which equals working + shipped + receiving in every row.",
    "Aged stock = all units over 180 days in Amazon's age buckets (bucket edges differ by market).",
    "Amazon's recommendation = 'Recommended ship-in quantity' (UK, US) or 'recommended-order-quantity' (AU).",
    "Mich's recommendation = the quantity in the '<market> RECO' sheet, matched on SKU and date. Dates that match no snapshot are retried with day and month swapped (UK 2026-10-09 → 10 Sep).",
    "Economics come from '<market> Report' in LICKIMAT TABLE: matched on SKU first, then on ASIN when the ASIN appears once in the report. Windows: 12 months (UK, AU, DE), 15 months (US).",
    "Base code = the leading LickiMat product code; everything after it is treated as a label or marketplace suffix (LM3001GN-DR-FBA-UK → LM3001GN, LM-BTT-FBA-UK → LM-BTT). SKUs that do not start with an LM code (bundles, test listings) are kept and listed on the QA page.",
    "The US export also holds Canada SKUs (suffix -CA). They stay under US because they share the North American export; split them out if Ramin runs Canada separately.",
    "'What Ramin actually restocked' ≈ the rise in inbound units since the previous snapshot ('New inbound'). It misses shipments created and received between two snapshots.",
    "Money is shown in each market's own currency. Only two places convert to GBP at fixed, rounded rates (1 USD = 0.8, 1 AUD = 0.5): ordering the list when several markets are shown, and the profit charts when all markets are selected.",
    "Weekly demand comes from units shipped in the last 30 (or 90) days. A SKU that was out of stock for part of that window looks slower than it is, so its demand is understated.",
    "Canada SKUs (-CA) in the US export may be priced in CAD (not checked). Only 2 of them appear in the US economics report; the rest use the US median profit per unit (USD).",
    "Mich's working sheets (UK, US, AU, AU1) are not used: the dated RECO sheets hold the same recommendations with dates.",
]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=os.path.join(DEFAULT_SRC, "Dashboards"))
    a = ap.parse_args()
    main(a.src, a.out)
