"""Check the outlook data before building. Ends with OVERALL: PASS or OVERALL: FAIL.

Usage (from the repo root):
    .venv/Scripts/python.exe "Churn Analysis/work/churn_outlook/verify_outlook.py"
"""
import json
import pathlib
import sys

# the dashboard data lives in the local dashboards folder (next to the MI data), never in the repo
DATA = pathlib.Path.home() / "Desktop" / "Projects" / "Churn Analysis" / "Dashboards" / "data" / "churn_outlook.json"
d = json.loads(DATA.read_text(encoding="utf-8"))
fails = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        fails.append(what)


band = [r for r in d["risk_now"] if r["breakdown"] == "size band"]
check(abs(sum(r["seats_at_risk"] for r in band) - d["now"]["seats_at_risk"]) < 0.5, "size bands add up to the seats at risk today")
check(abs(sum(r["seats"] for r in band) - d["now"]["seats"]) < 0.5, "size bands add up to today's seats")
for b in {r["breakdown"] for r in d["risk_now"]}:
    rows = [r for r in d["risk_now"] if r["breakdown"] == b]
    check(abs(sum(r["seats_at_risk"] for r in rows) - d["now"]["seats_at_risk"]) < 0.5, f"{b}: groups add up to the total seats at risk")
for scope in ("All clients", "5+ staff", "1–4 staff"):
    m = [r for r in d["backtest"] if r["scope"] == scope]
    a = next(r for r in d["accuracy"] if r["scope"] == scope)
    check(abs(sum(r["actual"] for r in m) - a["actual"]) < 0.5 and abs(sum(r["predicted"] for r in m) - a["predicted"]) < 0.5, f"{scope}: monthly backtest ties to the accuracy table")
    c = sorted([r for r in d["capacity"] if r["scope"] == scope], key=lambda r: r["n"])
    check(all(x["seats_caught"] <= y["seats_caught"] + 1e-9 for x, y in zip(c, c[1:])), f"{scope}: capacity curve never falls as more clients are reviewed")
    check(all(r["seats_caught"] >= r["random"] for r in c), f"{scope}: the ranked list always beats reviewing at random")
for b in ("5+ staff", "1–4 staff"):
    check(abs(sum(r["share"] for r in d["drivers_group"] if r["band"] == b) - 1) < 1e-6, f"{b}: driver groups add up to 100%")
    check(abs(sum(r["share"] for r in d["drivers_factor"] if r["band"] == b) - 1) < 1e-4, f"{b}: driver factors add up to 100%")
check(json.dumps(d).find("Shortcode\":") == -1, "no client shortcodes in the export")

# client scores (three models)
import re
from collections import Counter
S = d["scores"]
rows, MODELS = S["rows"], S["models"]
nf = len(S["features"])
check(len(S["groups"]) == nf and all(len(r["t"]) == nf and set(r["m"]) == set(MODELS) and all(len(r["m"][k]["c"]) == nf for k in MODELS) for r in rows),
      "every client row has every model, with one contribution and one value per factor")
for k in MODELS:
    worst = max(abs(sum(r["m"][k]["c"]) - (r["m"][k]["s"] - r["m"][k]["s0"])) for r in rows)
    check(worst < 5e-4, f"{k}: contributions add up to score minus starting point (worst gap {worst * 100:.3f} pts)")
    check(all(0 <= r["m"][k]["s"] <= 1 for r in rows), f"{k}: scores are shares between 0 and 1")
    per = Counter((r["month"], r["band"]) for r in rows if r["m"][k]["r"] <= S["top_n"])
    check(max(per.values()) <= S["top_n"], f"{k}: at most {S['top_n']} listed clients per band per month")
    ok = True
    for key in per:
        g = sorted([r for r in rows if (r["month"], r["band"]) == key and r["m"][k]["r"] <= S["top_n"]], key=lambda r: r["m"][k]["r"])
        ok &= [r["m"][k]["r"] for r in g] == list(range(1, len(g) + 1)) and all(a["m"][k]["s"] >= b["m"][k]["s"] for a, b in zip(g, g[1:]))
    check(ok, f"{k}: listed ranks run 1..N in each band and month, following the score")
check(all(any(r["m"][k]["r"] <= S["top_n"] for k in MODELS) for r in rows), "every exported row is listed by at least one model")
check(all(re.fullmatch(r"C-[0-9A-F]{6}", r["id"]) for r in rows), "client IDs are anonymised (C-XXXXXX)")
check(len({(r["id"], r["month"]) for r in rows}) == len(rows), "one row per client per month")
check(all(r["today"] == (r["month"] == S["today"]) for r in rows), "only today's month is marked as today")
check(all((r["actual"] is None) == r["today"] and (r["churned"] is None) == r["today"] for r in rows), "holdout rows have outcomes, today's rows do not")
check(all(S["holdout_from"] <= r["month"] <= S["holdout_to"] for r in rows if not r["today"]), "holdout rows fall in the holdout window")
check(S["train_to"] < S["holdout_from"], "the holdout models were trained on months before the holdout")
for p in S["perf"]:
    check(0.5 < p["auc"] < 1 and p["rate_top10"] >= p["rate_all"], f"{p['model']}, {p['band']}: AUC above a coin flip and the top 10% churn more than average")
for k in MODELS:
    for b in ("5+ staff", "1–4 staff"):
        check(abs(sum(r["share"] for r in S["reasons"] if r["band"] == b and r["model"] == k) - 1) < 1e-4, f"{k}, {b}: main-reason shares add up to 100%")
        g = sorted([r for r in S["gains"] if r["band"] == b and r["model"] == k], key=lambda r: r["reviewed"])
        for key in ("churners_caught", "seats_caught"):
            v = [r[key] for r in g]
            check(v[0] == 0 and abs(v[-1] - 1) < 1e-9 and all(x <= y + 1e-12 for x, y in zip(v, v[1:])), f"{k}, {b}: gains curve ({key}) runs 0 to 100% and never falls")
        am = [r for r in S["auc_month"] if r["band"] == b and r["model"] == k]
        check(sum(r["client_months"] for r in am) == next(p["client_months"] for p in S["perf"] if p["band"] == b and p["model"] == k), f"{k}, {b}: monthly AUC covers every holdout client-month")
print("OVERALL:", "PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
