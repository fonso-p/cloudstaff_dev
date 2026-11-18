"""Tie the dashboard JSON back to the raw Excel, independently of prep.py.

Checks: row counts per market and snapshot, unit totals (available, inbound, sold 30d) for every snapshot,
Mich's unit totals, and a recomputation of the recommendation for every row with the rules written out again here.
Prints PASS/FAIL per check and exits 1 on any failure.

Usage:  .venv/Scripts/python.exe Lickimat/verify.py
"""
import json
import math
import os
import sys

import pandas as pd

SRC = os.path.expanduser(r"~/Desktop/Projects/Client/Lickimat")
D = json.load(open(os.path.join(SRC, "Dashboards", "lickimat_replenishment.json"), encoding="utf-8"))
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
    if dem == 0 and stock == 0:
        exp = 0
    elif dem < S["slow"]:
        exp = max(0, S["slow_topup"] - stock) if stock < S["slow_min"] else 0
    else:
        exp = max(0, math.ceil(target * dem - stock))
    bad += exp != r.reco
check("Recommended quantity recomputed for every row", bad == 0, f"{bad} mismatches of {len(rows)}")

au = rows[(rows.m == "AU")].groupby("snap").apply(lambda g: (g.status != "No activity").sum())
print("AU SKUs with activity by snapshot:", au.to_dict())
sys.exit(1 if fails else 0)
