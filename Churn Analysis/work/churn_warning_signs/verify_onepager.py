"""Check the one-pager data before building: numbers tie out and every code on the page traces to the dictionary.

Usage (from the repo root):
    .venv/Scripts/python.exe "Churn Analysis/work/churn_warning_signs/verify_onepager.py"
Ends with OVERALL: PASS or OVERALL: FAIL.
"""
import json
import pathlib
import sys

DATA = pathlib.Path(__file__).resolve().parents[2] / "data" / "churn_warning_signs.json"
d = json.loads(DATA.read_text(encoding="utf-8"))
fails = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        fails.append(what)


ids = {r["id"] for r in d["indicators"]}
features = {r["feature"] for r in d["features"]}
tl_cols = {r["field"] for r in d["timeline"]}

print("Traceability")
check({s["id"] for s in d["signs"]} <= ids, "every bar on the ranked charts has an indicator row")
check({c[k] for c in d["combos"] for k in ("id1", "id2")} <= ids, "every sign in the two-signs charts has an indicator row")
check({r["feature"] for r in d["indicators"]} <= features, "every indicator points to a feature row")
missing = {c for f in d["features"] for c in f["built_from"] if not c.startswith("(")} - tl_cols
check(not missing, f"every timeline column a feature uses has a timeline row {sorted(missing) if missing else ''}")
check(all(r["shown_in"] or r["id"] in {"A8", "P3", "L5"} for r in d["indicators"]), "indicators not on a chart are only the dictionary-only ones")

print("Numbers")
for s in d["signs"]:
    if s["x"] is not None and s["churn_without"]:
        if abs(s["x"] - s["churn_with"] / s["churn_without"]) > 1e-3:
            check(False, f"{s['id']} {s['band']}: times as likely = churn with / churn without")
check(True, "times as likely = churn with / churn without, for every sign")
check(all(s["clear"] == (s["lo"] is not None and (s["lo"] > 1 or s["hi"] < 1)) for s in d["signs"]), "clear signal = 95% range does not cross 1")
for b in d["bands"]:
    check(abs(b["base_rate"] - b["churned_months"] / b["client_months"]) < 1e-6, f"{b['band']}: churn rate = churned / client-months")
for c in d["combos"]:
    check(c["both"] > max(c["only1"], c["only2"]) and c["lift_lo"] > 1, f"{c['band']} {c['id1']}+{c['id2']}: both together clearly above either alone")
    prev = {r["id"]: r["prevalence"][c["band"]] for r in d["indicators"]}
    check(max(prev[c["id1"]], prev[c["id2"]]) <= d["meta"]["max_prevalence"], f"{c['band']} {c['id1']}+{c['id2']}: neither sign is the normal state")
q = [r["rows"] for r in d["qa"]]
check(q[0] == sum(q[1:5]), "exits in the window = record-only + replaced + business reasons + counted as churn")
check(sum(b["client_months"] for b in d["bands"]) == sum(r["rows"] for r in d["qa"] if r["step"].startswith("Client-months")), "client-months tie to the QA table")
check(json.dumps(d).find("Shortcode\":") == -1, "no client shortcodes in the export")

print("OVERALL:", "PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
