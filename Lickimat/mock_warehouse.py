"""Mock warehouse stock and other-channel demand for the Lickimat warehouse-stock change.

MOCK DATA. The client has not shared warehouse stock (Trilanco, Extensiv, AU 3PL) or wholesale / brick-and-mortar
demand, so this script invents both, keyed on the real SKUs in the latest Amazon export of each store.
See CHANGE_warehouse_stock.md for the rules this data is meant to exercise.

Steps:
    1. load      latest Amazon snapshot per store (plus earlier snapshots, for correction C2)
    2. need      today's restock recommendation with corrections C1-C4 = "Amazon need"
    3. item      warehouse item per SKU: base code + variant code (DR, CR, DE, CE, DA, R, E)
    4. mock      warehouse on-hand and other demand per store x item (seeded, repeatable): a per-product
                 Amazon share of total demand, cover independent of Amazon need, three kinds of non-seller,
                 carton rounding; then named test scenarios planted on chosen items
    5. apply     free stock = on hand - other demand, shared across the item's SKUs in list order
    6. write     the two mock input files, the expected results and the test cases

Usage:  .venv/Scripts/python.exe Lickimat/mock_warehouse.py --src <folder with INVENTORY_RECOMMENDATION2.xlsx> --out <folder>
Outputs hold real SKU codes (client data): write them outside the repo.
"""
import argparse
import math
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prep import base_code  # noqa: E402

STORES = ["UK", "US", "AU"]
WAREHOUSE = {"UK": "Trilanco", "US": "Extensiv", "AU": "Wattle 3PL (made up)"}
LEAD, BUFFER, CAP = 4, 4, 26
SLOW, SLOW_MIN, SLOW_TOPUP, KEEP_ALIVE = 1.0, 5, 10, 2
STATUS_ORDER = ["Out of stock", "Urgent", "Below target", "OK", "Excess", "Keep listing alive", "No recent sales"]
SEED = 20261125

# ---- mock assumptions (made up; there is no real other-channel data to calibrate against)
AMZ_SHARE_MIN, AMZ_SHARE_MAX = 0.03, 0.60        # each product's Amazon share of total demand: Beta(2,10), median ~15%
COVER_MEDIAN, COVER_SIGMA = 9, 0.45              # warehouse holds 2-20 weeks of total demand, median 9 (lognormal)
OTHER_HORIZON_WEEKS = 4                          # other demand = other channels' next 4 weeks of orders
NON_SELLER_MIX = [0.45, 0.30, 0.25]              # no Amazon sales: leftover / wholesale only / discontinued
CARTONS = {"UK": [12, 24, 36, 48], "US": [24, 36, 72], "AU": [12, 24]}   # stock counted in full cartons

COLS = {  # target -> candidate source columns (first found wins)
    "snap": ["snapshot-date"], "sku": ["sku"], "name": ["product-name"],
    "avail": ["available"], "inb": ["inbound-quantity"],
    "fct": ["fc-transfer", "FC transfer"], "rfc": ["Reserved FC Processing"],
    "s30": ["units-shipped-t30", "units-shipped-last-30-days"],
    "s90": ["units-shipped-t90", "units-shipped-last-90-days"],
    "price": ["your-price"],
}
# Variant code = the segment right after the base code. Guess (to confirm): D/C = dog/cat, R/E/A = pack version.
# Different packs are different physical items, so each code is its own warehouse item.
VARIANTS = {"DR", "CR", "DE", "CE", "DA", "R", "E"}


# ---------------------------------------------------------------- 1. load
def load(path, m):
    raw = pd.read_excel(path, f"{m} RAW DATA")
    df = pd.DataFrame({k: raw[next(c for c in cands if c in raw.columns)] for k, cands in COLS.items()})
    for k in ["avail", "inb", "fct", "rfc", "s30", "s90", "price"]:
        df[k] = pd.to_numeric(df[k], errors="coerce").fillna(0)
    df["snap"] = pd.to_datetime(df["snap"]).dt.date
    df = df.drop_duplicates(["snap", "sku"])
    df["store"] = m
    return df


# ---------------------------------------------------------------- 2. Amazon need (rules as built, with C1-C4)
def assess(r):
    stock = r.avail + r.inb + r.fct + r.rfc                                   # C1
    dem = r.s30 * 7 / 30
    if r.avail <= 0 or r.oos_90d:                                             # C2
        dem = max(dem, r.s90 * 7 / 90)
    cover = stock / dem if dem > 0 else None
    target = LEAD + BUFFER
    if r.s90 <= 0 and r.s30 <= 0:
        if r.price <= 0:                                                      # C3
            return dem, stock, cover, "No recent sales", 0
        reco = max(0, math.ceil(KEEP_ALIVE - stock))
        return dem, stock, cover, ("Keep listing alive" if reco else "No recent sales"), reco
    if dem < SLOW:
        reco = max(0, min(SLOW_TOPUP, math.ceil(CAP * dem)) - stock) if stock < SLOW_MIN else 0   # C4
        reco = math.ceil(reco)
        if r.avail <= 0 and r.s90 > 0:
            st = "Out of stock"
        elif stock < SLOW_MIN:
            st = "Below target"
        elif cover is not None and cover > CAP and stock > SLOW_TOPUP:
            st = "Excess"
        else:
            st = "OK"
        return dem, stock, cover, st, reco
    reco = max(0, math.ceil(target * dem - stock))
    st = ("Out of stock" if r.avail <= 0 else "Urgent" if cover < LEAD else "Below target" if cover < target
          else "Excess" if cover > CAP else "OK")
    return dem, stock, cover, st, reco


def amazon_need(df):
    latest = df["snap"].max()
    cur = df[df["snap"] == latest].copy()
    early = df[(df["snap"] < latest) & ((pd.Timestamp(latest) - pd.to_datetime(df["snap"])).dt.days <= 90)]
    oos = set(early.loc[early["avail"] <= 0, "sku"])
    cur["oos_90d"] = cur["sku"].isin(oos)
    cur[["dem", "stock", "cover", "status", "need"]] = pd.DataFrame(
        [assess(r) for r in cur.itertuples(index=False)], index=cur.index)
    return cur


# ---------------------------------------------------------------- 3. warehouse item
def item_of(sku):
    base, ok = base_code(sku)
    if not ok:
        return None                                                           # bundles, test listings: no warehouse item
    rest = [t for t in re.split(r"[-\s]+", str(sku).strip().upper()[len(base):]) if t]
    return base + (f"-{rest[0]}" if rest and rest[0] in VARIANTS else "")


def list_order(df):
    df = df.copy()
    df["_s"] = df["status"].map(STATUS_ORDER.index)
    df["_c"] = df["cover"].fillna(np.inf)
    return df.sort_values(["_s", "_c", "dem", "sku"], ascending=[True, True, False, True]).drop(columns=["_s", "_c"])


# ---------------------------------------------------------------- 4. mock warehouse values
def mock_values(cur, rng):
    """One row per store x item. Amazon is the small channel: other demand is usually several times Amazon's."""
    items = (cur.dropna(subset=["item"]).groupby(["store", "item"])
             .agg(amz_dem=("dem", "sum"), amz_need=("need", "sum"), skus=("sku", "nunique")).reset_index())
    rows = []
    for r in items.itertuples(index=False):
        if r.amz_dem > 0:
            share = float(np.clip(rng.beta(2, 10), AMZ_SHARE_MIN, AMZ_SHARE_MAX))   # this product's Amazon share
            total_wk = r.amz_dem / share
            other_wk = total_wk - r.amz_dem
            kind = "seller"
        else:                                                   # no Amazon sales: three kinds of item
            kind = rng.choice(["leftover", "wholesale only", "discontinued"], p=NON_SELLER_MIX)
            other_wk = {"leftover": rng.uniform(0, 1.5), "wholesale only": rng.lognormal(np.log(8), 0.8),
                        "discontinued": 0.0}[kind]
            total_wk = other_wk
        cover = float(np.clip(rng.lognormal(np.log(COVER_MEDIAN), COVER_SIGMA), 2, 20))   # weeks of total demand held
        on_hand = 0 if kind == "discontinued" else total_wk * cover
        if kind == "leftover":
            on_hand = rng.integers(0, 31)
        carton = int(rng.choice(CARTONS[r.store]))
        on_hand = carton * round(on_hand / carton) if on_hand >= carton else round(on_hand)
        other = other_wk * OTHER_HORIZON_WEEKS
        other = 6 * round(other / 6) if other >= 6 else round(other)          # wholesale orders in cases of 6
        rows.append({"store": r.store, "item": r.item, "on_hand": int(on_hand), "other_demand": int(other),
                     "kind": kind, "scenario": "Generated"})
    return pd.DataFrame(rows), items


def plant(wh, items, cur, rng):
    """Overwrite chosen items with named scenarios so every branch of the rule is exercised in each store."""
    wh = wh.set_index(["store", "item"])
    used = set()
    multi = cur.dropna(subset=["item"]).groupby(["store", "item"])["sku"].nunique()

    def pick(store, cond, n=1, near=None):
        """Items in a store meeting cond, not used by another scenario. near = pick the item whose need is closest
        to it; otherwise a random sample (seeded), so scenarios are not all on the best sellers."""
        c = items[(items["store"] == store) & cond]
        c = c[~c["item"].map(lambda i: (store, i) in used).astype(bool)]
        if near is not None:
            c = c.iloc[(c["amz_need"] - near).abs().argsort()]
        else:
            c = c.sample(frac=1, random_state=int(rng.integers(1e9)))
        out = list(c["item"].head(n))
        used.update((store, i) for i in out)
        return out

    gone = []
    for s in STORES:
        # S0: the example from the brief (need about 50, 100 on hand, 70 for other channels -> send 30)
        for i in pick(s, (items["skus"] == 1) & (items["amz_need"] >= 35), 1, near=50):
            wh.loc[(s, i), ["on_hand", "other_demand", "scenario"]] = [100, 70, "S0 Brief example: 100 on hand, 70 other"]
        # S2: partly short (free stock is about half the need)
        for i in pick(s, (items["skus"] == 1) & (items["amz_need"] >= 10), 3):
            need = int(items.set_index(["store", "item"]).loc[(s, i), "amz_need"])
            other = int(wh.loc[(s, i), "other_demand"])
            wh.loc[(s, i), ["on_hand", "scenario"]] = [other + need // 2, "S2 Partly short"]
        # S3: other channels take everything (on hand below other demand)
        for i in pick(s, (items["skus"] == 1) & (items["amz_need"] > 0), 3):
            other = int(wh.loc[(s, i), "other_demand"]) or 20
            wh.loc[(s, i), ["on_hand", "other_demand", "scenario"]] = [int(other * 0.8), other, "S3 Other channels take it all"]
        # S4: nothing in the warehouse
        for i in pick(s, (items["skus"] == 1) & (items["amz_need"] > 0), 2):
            wh.loc[(s, i), ["on_hand", "scenario"]] = [0, "S4 Warehouse empty"]
        # S5: several Amazon SKUs on one item, free stock covers the first in list order only
        sel = items[(items["store"] == s) & (items["skus"] >= 2)].copy()
        sel["n_need"] = [int((cur[(cur["store"] == s) & (cur["item"] == i)]["need"] > 0).sum()) for i in sel["item"]]
        for i in pick(s, items["item"].isin(sel.loc[sel["n_need"] >= 2, "item"]), 2):
            grp = list_order(cur[(cur["store"] == s) & (cur["item"] == i) & (cur["need"] > 0)])
            first = int(grp["need"].iloc[0])
            other = int(wh.loc[(s, i), "other_demand"])
            wh.loc[(s, i), ["on_hand", "scenario"]] = [other + first + max(1, int(grp["need"].iloc[1]) // 2),
                                                       "S5 Several SKUs share one item"]
        # S6: keep-alive SKU with no free stock (needs 1-2 units, warehouse can't spare them)
        for i in pick(s, (items["skus"] == 1) & (items["amz_dem"] == 0) & (items["amz_need"] > 0), 1):
            wh.loc[(s, i), ["on_hand", "other_demand", "scenario"]] = [5, 5, "S6 Keep-alive, no free stock"]
        # S7: heavy other demand but Amazon needs nothing: no effect on Amazon
        for i in pick(s, (items["amz_need"] == 0) & (items["amz_dem"] > 1), 1):
            wh.loc[(s, i), ["on_hand", "other_demand", "scenario"]] = [10, 200, "S7 Amazon needs nothing"]
        # S8: item missing from the warehouse files
        gone += [(s, i) for i in pick(s, (items["skus"] == 1) & (items["amz_need"] > 0), 1)]
    for k in gone:
        wh.loc[k, "scenario"] = "S8 Not in warehouse files"
    wh["on_hand"] = wh["on_hand"].astype(int)
    wh["other_demand"] = wh["other_demand"].astype(int)
    return wh.reset_index(), gone



# ---------------------------------------------------------------- 5. apply the new rule
def apply(cur, wh_files):
    """wh_files = the two mock files joined (only items present in the files)."""
    wh = wh_files.set_index(["store", "item"])
    out = []
    for (s, i), grp in list_order(cur).groupby(["store", "item"], sort=False, dropna=False):
        known = isinstance(i, str) and (s, i) in wh.index
        free = max(0, int(wh.loc[(s, i), "on_hand"]) - int(wh.loc[(s, i), "other_demand"])) if known else 0
        left = free
        for r in grp.itertuples():
            send = min(int(r.need), left)
            left -= send
            out.append({"idx": r.Index, "wh_known": known,
                        "on_hand": int(wh.loc[(s, i), "on_hand"]) if known else None,
                        "other_demand": int(wh.loc[(s, i), "other_demand"]) if known else None,
                        "free": free if known else None, "free_before": send + left if known else 0,
                        "can_send": send})
    res = pd.DataFrame(out).set_index("idx")
    cur = cur.join(res)
    cur["short"] = cur["need"] - cur["can_send"]

    def flag(r):
        if r.need <= 0:
            return ""
        if not r.wh_known:
            return "No warehouse record"
        return "Short at warehouse" if r.short > 0 else ""
    cur["wh_flag"] = cur.apply(flag, axis=1)
    return cur


def why(r):
    if r.need <= 0:
        return ""
    if not r.wh_known:
        return "No warehouse record for this item, so nothing can be sent." if isinstance(r.item, str) else \
            "Not a warehouse item (bundle or test listing), so nothing can be sent."
    on, oth, fr, left, send, need = (int(v) for v in (r.on_hand, r.other_demand, r.free, r.free_before, r.can_send, r.need))
    head = f"{WAREHOUSE[r.store]}: {on} on hand, {oth} set aside for other channels, {fr} free"
    if left < fr:
        head += f" ({left} left after other SKUs on this item)"
    return head + (f". Send {send}." if send >= need else f". Send {send} of the {need} needed.")


# ---------------------------------------------------------------- 6. write
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rng = np.random.default_rng(SEED)
    cur = pd.concat([amazon_need(load(os.path.join(a.src, "INVENTORY_RECOMMENDATION2.xlsx"), m)) for m in STORES],
                    ignore_index=True)
    cur["item"] = cur["sku"].map(item_of)

    wh, items = mock_values(cur, rng)
    wh, gone = plant(wh, items, cur, rng)
    asof = cur.groupby("store")["snap"].max()
    wh["as_of"] = wh["store"].map(asof)
    wh["warehouse"] = wh["store"].map(WAREHOUSE)
    in_files = wh[[(s, i) not in set(gone) for s, i in zip(wh["store"], wh["item"])]]

    res = apply(cur, in_files)
    res["wh_why"] = res.apply(why, axis=1)
    res = res.merge(wh[["store", "item", "scenario", "kind"]], on=["store", "item"], how="left")
    res.loc[res["item"].isna(), "scenario"] = "S9 Not a warehouse item"

    os.makedirs(a.out, exist_ok=True)
    stock = in_files[["as_of", "warehouse", "store", "item", "on_hand"]].sort_values(["store", "item"])
    dem = in_files[["as_of", "warehouse", "store", "item", "other_demand"]].sort_values(["store", "item"])
    stock.to_csv(os.path.join(a.out, "warehouse_stock.csv"), index=False, encoding="utf-8-sig")
    dem.to_csv(os.path.join(a.out, "other_demand.csv"), index=False, encoding="utf-8-sig")

    exp = list_order(res)[["store", "snap", "sku", "item", "status", "dem", "cover", "stock", "need", "on_hand",
                           "other_demand", "free", "free_before", "can_send", "short", "wh_flag", "wh_why", "scenario", "kind"]]
    exp = exp.rename(columns={"snap": "amazon_snapshot", "dem": "weekly_demand", "stock": "amazon_stock",
                              "need": "amazon_need", "free": "free_stock", "free_before": "free_left_for_sku",
                              "wh_flag": "flag", "wh_why": "why_warehouse", "kind": "item_kind"})
    exp["weekly_demand"] = exp["weekly_demand"].round(2)
    exp["cover"] = exp["cover"].round(2)
    exp.to_csv(os.path.join(a.out, "expected_results.csv"), index=False, encoding="utf-8-sig")
    tc = exp[exp["scenario"].str.match(r"S[0-8] ") & ((exp["amazon_need"] > 0) | exp["scenario"].str.startswith("S7"))]
    tc.sort_values(["scenario", "store"]).to_csv(os.path.join(a.out, "test_cases.csv"), index=False, encoding="utf-8-sig")

    # checks (see CHANGE_warehouse_stock.md, section 6)
    assert (exp["can_send"] <= exp["amazon_need"]).all() and (exp["can_send"] >= 0).all()
    sent = exp.dropna(subset=["free_stock"]).groupby(["store", "item"]).agg(s=("can_send", "sum"), f=("free_stock", "first"))
    assert (sent["s"] <= sent["f"]).all(), "an item sent more than its free stock"
    assert ((exp["cover"] < LEAD) <= (exp["amazon_need"] > 0)).all(), "R1: cover under 4 weeks needs an Amazon need"
    assert ((exp["can_send"] < exp["amazon_need"]) == exp["flag"].isin(["Short at warehouse", "No warehouse record"])).all()
    print("checks: PASS")

    # summary for the spec
    print("rows", len(exp), "items in files", len(in_files))
    print(exp.groupby("store").agg(skus=("sku", "size"), need=("amazon_need", "sum"), send=("can_send", "sum"),
                                   short_skus=("flag", lambda f: (f == "Short at warehouse").sum()),
                                   norec=("flag", lambda f: (f == "No warehouse record").sum())))
    print("tot need", exp["amazon_need"].sum(), "send", exp["can_send"].sum())
    print(exp.groupby("scenario").size())
    print("files:", len(stock), len(dem))


if __name__ == "__main__":
    main()
