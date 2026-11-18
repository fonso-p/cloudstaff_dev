"""Build a LOCAL copy of the Churn outlook dashboard that shows real client shortcodes.

The repo dashboard identifies clients only by anonymised IDs (C-XXXXXX). This script adds each ID's shortcode, read
from the key files the notebook (section 2.13) writes to the local MI data folder, and builds the page there.
Nothing it writes goes into the repo. Keep the output local: do not share or commit it.

Usage (from the repo root, after the notebook run and verify_outlook.py; build_dashboards.py runs it for you):
    .venv/Scripts/python.exe "Churn Analysis/work/churn_outlook/add_shortcodes.py"
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[3]
MI = pathlib.Path.home() / "Desktop" / "Projects" / "Churn Analysis"
DATA_JSON = MI / "Dashboards" / "data" / "churn_outlook.json"
KEYS = [MI / "Data" / "client_scores_holdout.csv", MI / "Data" / "client_scores_today.csv"]
OUT_DIR = MI / "Dashboards"

key = pd.concat([pd.read_csv(k, usecols=["client_id", "Shortcode"]) for k in KEYS]).drop_duplicates()
assert key["client_id"].is_unique, "one ID maps to more than one shortcode: rerun the notebook"
code_of = dict(zip(key["client_id"], key["Shortcode"].astype(str)))

d = json.loads(DATA_JSON.read_text(encoding="utf-8"))
missing = 0
for r in d["scores"]["rows"]:
    r["code"] = code_of.get(r["id"])
    missing += r["code"] is None
assert missing == 0, f"{missing} client rows have no shortcode in the key files: rerun the notebook"
d["meta"]["title"] = d["meta"]["title"] + " (with shortcodes)"

(OUT_DIR / "data").mkdir(parents=True, exist_ok=True)
local_json = OUT_DIR / "data" / "churn_outlook_with_shortcodes.json"
local_json.write_text(json.dumps(d, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
out = OUT_DIR / f"{dt.date.today():%Y-%m-%d}_Churn_Outlook_with_shortcodes.html"
subprocess.run([sys.executable, str(REPO / ".claude" / "skills" / "cs-dashboard" / "scripts" / "build_dashboard.py"),
                "--template", str(REPO / "Churn Analysis" / "work" / "churn_outlook" / "dashboard_template.html"),
                "--data", str(local_json), "--out", str(out)], check=True)
print(f"local copy with shortcodes: {out}")
