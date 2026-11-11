"""Re-run the QA gate on an existing workbook (e.g. after someone edited it).

    python qa_check.py outputs/excel/2026-09-25_Client_Churn_Review.xlsx [--qa-json path]

Needs the <stem>_QA.json written at build time (in ../qa/ or next to the workbook) and the
original raw file at its recorded path. Independent expected values come from build time,
so if the data or Include flags changed, G4 will FAIL - that is intended: rebuild instead.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qa                                   # noqa: E402
from recalc import RecalcUnavailable, recalc_copy  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--qa-json")
    a = ap.parse_args()
    stem = os.path.splitext(os.path.basename(a.xlsx))[0]
    cands = [a.qa_json] if a.qa_json else [
        os.path.join(qa._qa_dir(a.xlsx), f"{stem}_QA.json"),
        os.path.join(os.path.dirname(os.path.abspath(a.xlsx)), f"{stem}_QA.json")]
    path = next((p for p in cands if p and os.path.exists(p)), None)
    if not path:
        sys.exit(f"QA manifest not found (looked for {cands}). Rebuild the workbook with its build script.")
    man = json.load(open(path, encoding="utf-8"))["manifest"]
    try:
        calc, engine = recalc_copy(a.xlsx), "re-check recalculation"
    except RecalcUnavailable as e:
        calc, engine = None, f"NONE ({e})"
    res = qa.run_gates(None, calc, engine, manifest=man, formula_path=a.xlsx)
    if calc:
        import openpyxl
        v = openpyxl.load_workbook(calc, data_only=True)
        res["excel_verdict_cell"] = v["QA & Data Quality"]["C6"].value
    res["output"] = os.path.abspath(a.xlsx)
    res["manifest"] = man
    out = os.path.join(os.path.dirname(path), f"{stem}_RECHECK_QA.md")
    lines = [f"# Re-check - {man['title']}", "", f"**Verdict: {res['verdict']}**", ""]
    for g in res["gates"]:
        lines.append(f"## {g['gate']} {g['name']} - {g['status']}")
        lines += [f"- [{c['status']}] {c['check']}" + (f" - {c['detail']}" if c.get("detail") else "") for c in g["checks"]]
        lines.append("")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print(qa.console_summary(res))
    print(f"Report: {out}")
    return 0 if res["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
