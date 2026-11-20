"""Tie the dashboard JSON back to the raw Excel, independently of prep.py.

Checks: row counts per market and snapshot, unit totals (available, inbound, sold 30d) for every snapshot,
Mich's unit totals, and a recomputation of the recommendation for every row with the rules written out again here.
Prints PASS/FAIL per check and exits 1 on any failure.

Usage:  .venv/Scripts/python.exe Lickimat/verify.py [SRC_DIR] [OUT_DIR]
"""
import json
import math
import os
import sys

import pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(r"~/Desktop/Projects/Client/Lickimat")   # folder with the two workbooks
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SRC, "Dashboards")                            # folder with the JSON
D = json.load(open(os.path.join(OUT, "lickimat_replenishment.json"), encoding="utf-8"))
rows = pd.DataFrame(D["rows"])
S = D["settings"]
fails = 0


def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")


T30 = {"UK": "units-shipped-t30", "US": "units-shipped-t30", "AU": "units-shipped-last-30-days"}
for m in ["UK", "US", "AU"]:
    raw = pd.read_excel(os.path.join(SRC, "INVENTORY_RECOMMENDATION2.xlsx"), f"{m} RAW DATA")
    raw["snap"] = pd.to_datetime(raw["snapshot-date"]).dt.date.astype(str)
    j = rows[rows.m == m]
    check(f"{m} row count", len(raw) == len(j), f"raw {len(raw)} vs json {len(j)}")
    for snap, g in raw.groupby("snap"):
        jj = j[j.snap == snap]
        for col, k in [("available", "avail"), ("inbound-quantity", "inb"), (T30[m], "s30")]:
            a, b = pd.to_numeric(g[col], errors="coerce").fillna(0).sum(), jj[k].sum()
            check(f"{m} {snap} total {k}", abs(a - b) < 0.5, f"raw {a:,.0f} vs json {b:,.0f}")
    reco = pd.read_excel(os.path.join(SRC, "INVENTORY_RECOMMENDATION2.xlsx"), f"{m} RECO", header=1)
    q = pd.to_numeric(reco.iloc[:, 10], errors="coerce")
    a = q[reco["SKU"].notna() & reco["Date"].notna()].sum()
    lost = sum(float(x["step"].split(", ")[1].split(" units")[0]) for x in D["qa"]
               if x["market"] == m and x["step"].startswith("Mich reco rows whose SKU"))
    b = j["mich"].fillna(0).sum()
    check(f"{m} Mich units = matched + dropped (QA page)", abs(a - b - lost) < 0.5, f"raw {a:,.0f} vs json {b:,.0f} + dropped {lost:,.0f}")

# independent recomputation of the rules
bad = 0
for r in rows.itertuples():
    lead, target = S["lead"][r.m], S["lead"][r.m] + S["buffer"][r.m]
    dem = r.s30 * 7 / 30
    if r.avail <= 0:
        dem = max(dem, r.s90 * 7 / 90)
    stock = r.avail + r.inb
    if r.s90 <= 0 and r.s30 <= 0:   # keep listing alive
        exp = max(0, math.ceil(S["keep_alive"] - stock))
    elif dem < S["slow"]:
        exp = max(0, S["slow_topup"] - stock) if stock < S["slow_min"] else 0
    else:
        exp = max(0, math.ceil(target * dem - stock))
    bad += exp != r.reco
check("Recommended quantity recomputed for every row", bad == 0, f"{bad} mismatches of {len(rows)}")

# Ramin's requirement: every SKU under 4 weeks of cover gets a quantity
low = rows[rows.cover.notna() & (rows.cover < 4)]
check("Ramin: every SKU under 4 weeks of cover has a recommended quantity", (low.reco > 0).all(),
      f"{(low.reco <= 0).sum()} without, of {len(low)} rows")

# profit per unit and profit at stake, recomputed from the raw economics file
for m in ["UK", "US", "AU"]:
    e = pd.read_excel(os.path.join(SRC, "LICKIMAT TABLE .xlsx"), f"{m} Report")
    e.columns = [c.lower() for c in e.columns]
    np_, un = pd.to_numeric(e["net proceed total"], errors="coerce"), pd.to_numeric(e["net units sold"], errors="coerce")
    med = (np_[un > 0] / un[un > 0]).median()
    j = rows[rows.m == m]
    est, act = j[j.ppu_est], j[~j.ppu_est]
    check(f"{m} profit/unit = net proceeds ÷ units where matched", ((act.ppu - act.np / act.eunits).abs() < 0.01).all(), f"{len(act)} rows")
    check(f"{m} profit/unit = market median where not matched", ((est.ppu - med).abs() < 0.01).all(), f"{len(est)} rows, median {med:.2f}")
    check(f"{m} profit at stake = demand × profit/unit, GBP at fixed rate",
          # tolerance = what 2-decimal rounding in the JSON allows (demand and profit/unit are each rounded)
          ((j.pw - j.dem * j.ppu).abs() <= 0.005 * (j.dem.abs() + j.ppu.abs()) + 0.01).all()
          and ((j.pw_gbp - j.pw * S["fx"][m]).abs() <= 0.005 * (1 + j.pw.abs() * 0.01) + 0.01).all())

# expected priority order (latest snapshot, all markets), to compare with the # column on the page
STATUS = ["Out of stock", "Urgent", "Below target"]
a = rows[(rows.sr == 0) & rows.status.isin(STATUS)].copy()
a["si"] = a.status.map(STATUS.index)
a["cv"] = a.cover.fillna(1e9)
a["pw0"] = a.pw_gbp.clip(lower=0)   # a loss counts as 0 when ordering
a = a.sort_values(["si", "pw0", "cv", "dem"], ascending=[True, False, True, False], kind="stable")
print("Expected top 10 of statuses 1-3, all markets, latest:", list(a.sku.head(10)))
print("Expected top 5 of statuses 1-3, UK only, latest:", list(a[a.m == "UK"].sku.head(5)))

ka = rows[(rows.sr == 0) & (rows.status == "Keep listing alive")]
print("Keep listing alive, latest snapshot:", ka.groupby("m").reco.agg(["count", "sum"]).to_dict())
sys.exit(1 if fails else 0)
