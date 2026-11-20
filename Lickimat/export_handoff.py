"""Export the processed dashboard data as plain CSV files for a handoff.

Reads the JSON written by prep.py and writes one CSV per table (see HANDOFF.md, section 14, for the data dictionary).
Client data: the output goes beside the JSON on the Desktop, never into the repo.

Usage:  .venv/Scripts/python.exe Lickimat/export_handoff.py [JSON_DIR] [DEST_DIR]
        JSON_DIR = folder with lickimat_replenishment.json; DEST_DIR defaults to JSON_DIR/handoff_data
"""
import json
import os
import sys

import pandas as pd

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(r"~/Desktop/Projects/Client/Lickimat/Dashboards")
D = json.load(open(os.path.join(OUT, "lickimat_replenishment.json"), encoding="utf-8"))
dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(OUT, "handoff_data")
os.makedirs(dst, exist_ok=True)


def write(name, df):
    df.to_csv(os.path.join(dst, name), index=False, encoding="utf-8-sig")
    print(f"{name}: {len(df)} rows")


rows = pd.DataFrame(D["rows"])
rows["flags"] = rows["flags"].map(lambda f: "|".join(f))
write("replenishment_rows.csv", rows)                                   # every market x snapshot x SKU
write("replenishment_latest.csv", rows[rows["sr"] == 0])                # what the list shows
write("economics.csv", pd.DataFrame(D["econ"]))
write("qa_counts.csv", pd.DataFrame(D["qa"]))
write("unmapped_skus.csv", pd.DataFrame(D["unmapped"]))

S = D["settings"]
settings = [{"setting": f"{k}_{m}", "value": v} for k in ["lead", "buffer", "fx"] for m, v in S[k].items()]
settings += [{"setting": k, "value": S[k]} for k in ["cap", "slow", "slow_min", "slow_topup", "keep_alive"]]
settings += [{"setting": "action_statuses", "value": "|".join(S["action"])}]
settings += [{"setting": f"currency_{m}", "value": c} for m, c in D["meta"]["currency"].items()]
settings += [{"setting": f"econ_months_{m}", "value": c} for m, c in D["meta"]["econ_months"].items()]
settings += [{"setting": f"snapshots_{m}", "value": "|".join(v)} for m, v in D["meta"]["snapshots"].items()]
write("settings.csv", pd.DataFrame(settings))

# text shown on the Rules page, one table each
for key, name in [("reqs", "requirements"), ("rules", "rules"), ("statuses", "statuses"), ("flags", "flags"), ("confirm", "to_confirm")]:
    write(f"page_{name}.csv", pd.DataFrame(D[key]))
write("page_data_assumptions.csv", pd.DataFrame({"assumption": D["de_assumptions"]}))
