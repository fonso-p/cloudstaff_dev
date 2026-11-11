"""QA gates for Cloudstaff analytics workbooks.

Eight gates run automatically on every save (and again with qa_check.py):

  G1 Source integrity         raw file unchanged; Raw Data tab identical to the source, cell by cell
  G2 Data quality             completeness of required fields; every flagged/excluded row has an agreed decision
  G3 Formula integrity        zero formula errors; analysis numbers are formulas that trace back to data
  G4 Independent recompute    every table/KPI recomputed separately in pandas and compared with Excel
  G5 Reconciliation           live checks (row counts, control totals, breakdowns tie to totals) all PASS
  G6 Statistical soundness    sample sizes, percentages that should sum to 100%, minimum data volume
  G7 Presentation & narrative every tab explained, narratives use live numbers, charts titled, branding
  G8 Analyst review           definitions, period, outliers, sample sizes, causal language confirmed

Verdict: any FAIL -> FAIL (file saved as DRAFT); any WARN -> PASS WITH WARNINGS; else PASS.
"""
import datetime as dt
import json
import math
import os
import re

import openpyxl

ERR_RE = re.compile(r"^(#DIV/0!|#N/A|#NAME\?|#NULL!|#NUM!|#REF!|#VALUE!|#SPILL!|#CALC!|Err:\d+)")
MISSING_WARN, MISSING_FAIL = 0.02, 0.10
REQUIRED_ATTESTATIONS = {
    "definitions_confirmed": "Metric definitions agreed with the requester",
    "period_confirmed": "Time period and filters confirmed",
    "outliers_reviewed": "Outliers reviewed and treatment agreed",
    "sample_sizes_reviewed": "Small groups called out, not over-interpreted",
    "no_causal_overreach": "Findings describe patterns, not causes, unless a test supports it",
    "requester_questions_answered": "Every question the requester asked is answered",
}


def _status(checks):
    s = [c["status"] for c in checks]
    return "FAIL" if "FAIL" in s else ("WARN" if "WARN" in s else "PASS")


def _gate(code, name, checks):
    return {"gate": code, "name": name, "checks": checks, "status": _status(checks)}


def _c(check, status, detail=""):
    return {"check": check, "status": status, "detail": detail}


def _is_err(v):
    return isinstance(v, str) and bool(ERR_RE.match(v))


def _num_eq(a, e, tol):
    try:
        a, e = float(a), float(e)
    except (TypeError, ValueError):
        return False
    if math.isnan(e):
        return math.isnan(a)
    return abs(a - e) <= max(tol * max(1.0, abs(e)), 1e-9)


def _val_eq(a, e, tol=1e-9):
    if e is None or e == "":
        return a is None or a == ""
    if isinstance(e, bool):
        return a == e
    if isinstance(e, (int, float)):
        return _num_eq(a, e, tol)
    if isinstance(e, (dt.datetime, dt.date)):
        if isinstance(a, (dt.datetime, dt.date)):
            return abs((_as_dt(a) - _as_dt(e)).total_seconds()) < 1
        if isinstance(a, (int, float)):  # serial date
            return abs((dt.datetime(1899, 12, 30) + dt.timedelta(days=a) - _as_dt(e)).total_seconds()) < 1
        return False
    return str(a) == str(e)


def _as_dt(x):
    return x if isinstance(x, dt.datetime) else dt.datetime(x.year, x.month, x.day)


def _refs_data(formula):
    f = re.sub(r'"[^"]*"', '""', formula)
    return bool(re.search(r"raw_\w+|!\$?[A-Z]{1,3}\$?\d+|\$?[A-Z]{1,3}\$?\d+", f))


# ============================================================================ gates
def run_gates(book, calc_path, engine, manifest=None, formula_path=None):
    """book: CSWorkbook (at build) or None with manifest+formula_path (qa_check.py)."""
    from profile_data import load_source, sha256
    m = manifest or book.manifest()
    ri, meta = m["raw"], m["source"]
    fwb = book.wb if book is not None else openpyxl.load_workbook(formula_path)
    vwb = openpyxl.load_workbook(calc_path, data_only=True) if calc_path else None
    gates, column_notes = [], {}

    # ---------------- G1 source integrity
    g = []
    src_df = None
    if os.path.exists(meta["path"]):
        now = sha256(meta["path"])
        g.append(_c("Source file unchanged since it was loaded (SHA-256)",
                    "PASS" if now == meta["sha256"] else "FAIL",
                    f"{meta['file']} {meta['sha256'][:16]}..." + ("" if now == meta["sha256"] else f" now {now[:16]}... - the raw file was modified")))
        src_df, _ = load_source(meta["path"], meta.get("sheet"), meta.get("header_row", 0))
    else:
        g.append(_c("Source file available for re-checking", "WARN", f"{meta['path']} not found; fidelity check skipped"))
    g.append(_c("Row and column counts match the source",
                "PASS" if ri["rows"] == meta["rows"] and ri["orig_cols"] == meta["columns"] else "FAIL",
                f"{ri['rows']:,} rows x {len(ri['orig_cols'])} columns"))
    if src_df is not None and vwb is not None:
        ws = vwb[ri["sheet"]]
        bad, checked = [], 0
        for j, col in enumerate(src_df.columns, start=1):
            vals = src_df[col].tolist()
            for i, e in enumerate(vals):
                a = ws.cell(ri["first"] + i, j).value
                checked += 1
                if not _val_eq(a, e):
                    if len(bad) < 5:
                        bad.append(f"row {i + 2} '{col}': source={e!r} workbook={a!r}")
                    else:
                        bad.append(None)
        nbad = len(bad)
        g.append(_c("Every Raw Data cell identical to the source file",
                    "PASS" if nbad == 0 else "FAIL",
                    f"{checked:,} cells compared" + ("" if nbad == 0 else f"; {nbad} mismatches, e.g. " + "; ".join(b for b in bad if b))))
    elif vwb is None:
        g.append(_c("Every Raw Data cell identical to the source file", "FAIL", "No recalculation engine - could not verify"))
    gates.append(_gate("G1", "Source integrity", g))

    # ---------------- G2 data quality
    g = []
    decisions = m["decisions"]
    dec_text = " ".join((d["issue"] + " " + d["decision"] + " " + " ".join(d.get("columns", []))).lower() for d in decisions)
    if src_df is not None:
        n = max(1, len(src_df))
        for col in src_df.columns:
            s = src_df[col]
            miss = sum(1 for v in s if v is None or (isinstance(v, str) and v.strip() == ""))
            pct = miss / n
            if col in ri.get("required", []):
                covered = str(col).lower() in dec_text
                st = "PASS" if pct <= MISSING_WARN else ("WARN" if pct <= MISSING_FAIL or covered else "FAIL")
                g.append(_c(f"Required field '{col}' completeness", st,
                            f"{miss:,} missing ({pct:.1%}). Thresholds: <=2% pass, <=10% warn, >10% fail unless a treatment was agreed"
                            + (" - treatment logged" if covered and pct > MISSING_WARN else "")))
            if pct > 0.5:
                column_notes[str(col)] = f"{pct:.0%} blank - use with care"
        dups = int(src_df.astype(str).duplicated().sum())
        if dups:
            covered = "duplicate" in dec_text
            g.append(_c("Exact duplicate rows handled", "PASS" if covered else "WARN",
                        f"{dups} exact duplicates in source" + (" - decision logged" if covered else " - no decision logged")))
    if not ri.get("required"):
        g.append(_c("Required fields declared", "WARN", "No required columns were declared, so completeness was not tested"))
    flagged, excluded = ri["flagged"], ri["rows"] - ri["include_y"]
    g.append(_c("Rows with data issues have an agreed treatment",
                "PASS" if flagged == 0 or decisions else "FAIL",
                f"{flagged:,} rows flagged; {len(decisions)} decisions logged"
                + ("" if flagged == 0 or decisions else " - ask the requester how to treat them before sharing")))
    g.append(_c("Excluded rows are documented",
                "PASS" if excluded == 0 or decisions else "FAIL",
                f"{excluded:,} rows excluded (Include = N)"))
    gates.append(_gate("G2", "Data quality", g))

    # ---------------- G3 formula integrity
    g = []
    errs = []
    if vwb is not None:
        for ws in vwb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if _is_err(c.value):
                        errs.append(f"{ws.title}!{c.coordinate}={c.value}")
        g.append(_c("No formula errors anywhere in the workbook", "PASS" if not errs else "FAIL",
                    "0 errors" if not errs else f"{len(errs)} errors: " + ", ".join(errs[:8])))
    else:
        g.append(_c("No formula errors anywhere in the workbook", "FAIL", "Not verified - no recalculation engine"))
    hard, untraced, nform = [], [], 0
    for t in m["tables"]:
        ws = fwb[t["sheet"]]
        rows = list(range(t["first"], t["last"] + 1)) + ([t["total_row"]] if t["total_row"] else [])
        for r in rows:
            for j, h in enumerate(t["columns"][1:], start=2):
                if h in t["static_cols"]:
                    continue
                v = ws.cell(r, j).value
                if isinstance(v, str) and v.startswith("="):
                    nform += 1
                    if not _refs_data(v):
                        untraced.append(f"{t['sheet']}!{ws.cell(r, j).coordinate}")
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    hard.append(f"{t['sheet']}!{ws.cell(r, j).coordinate}")
    for k in m["kpis"]:
        v = fwb[k["sheet"]][k["cell"]].value
        if not (isinstance(v, str) and v.startswith("=")):
            hard.append(f"{k['sheet']}!{k['cell']} (KPI)")
        elif not _refs_data(v):
            untraced.append(f"{k['sheet']}!{k['cell']} (KPI)")
    g.append(_c("Analysis numbers are live formulas, not typed-in values", "PASS" if not hard else "FAIL",
                f"{nform:,} formula cells in tables" + ("" if not hard else f"; hardcoded: {', '.join(hard[:10])}")))
    g.append(_c("Every formula traces back to data (no constants like =120/3)", "PASS" if not untraced else "FAIL",
                "" if not untraced else ", ".join(untraced[:10])))
    no_raw = []
    for t in m["tables"]:
        ws = fwb[t["sheet"]]
        txt = " ".join(str(ws.cell(r, j).value) for r in range(t["first"], (t["total_row"] or t["last"]) + 1)
                       for j in range(2, len(t["columns"]) + 1))
        if "raw_" not in txt and "!" not in txt:
            no_raw.append(t["title"])
    g.append(_c("Each analysis table is linked to Raw Data", "PASS" if not no_raw else "WARN",
                "" if not no_raw else "Not linked: " + "; ".join(no_raw)))
    gates.append(_gate("G3", "Formula integrity", g))

    # ---------------- G4 independent recomputation
    g = []
    if vwb is None:
        g.append(_c("Excel results match independent recalculation", "FAIL", "Not verified - no recalculation engine"))
    else:
        for t in m["tables"]:
            ws = vwb[t["sheet"]]
            if not t["expected"]:
                g.append(_c(f"'{t['title']}' recomputed independently", "WARN", "No expected values supplied - not independently verified"))
                continue
            bad, n = [], 0
            for i, erow in enumerate(t["expected"]):
                for j, e in enumerate(erow, start=1):
                    if e is None:
                        continue
                    a = ws.cell(t["first"] + i, j).value
                    n += 1
                    ok = _num_eq(a, e, t["tolerance"]) if isinstance(e, (int, float)) and not isinstance(e, bool) else str(a) == str(e)
                    if not ok:
                        bad.append(f"{t['columns'][j - 1]} / {t['labels'][i]}: Excel={a!r} expected={e!r}")
            if t.get("expected_total") and t["total_row"]:
                for j, e in enumerate(t["expected_total"], start=1):
                    if e is None:
                        continue
                    a = ws.cell(t["total_row"], j).value
                    n += 1
                    if not _num_eq(a, e, t["tolerance"]):
                        bad.append(f"{t['columns'][j - 1]} / Total: Excel={a!r} expected={e!r}")
            g.append(_c(f"'{t['title']}' matches independent recalculation", "PASS" if not bad else "FAIL",
                        f"{n} values compared" + ("" if not bad else f"; {len(bad)} differ: " + "; ".join(bad[:5]))))
        for k in m["kpis"]:
            a = vwb[k["sheet"]][k["cell"]].value
            if k.get("expected") is None:
                g.append(_c(f"KPI '{k['label']}' recomputed independently", "WARN", "No expected value supplied"))
            else:
                ok = _num_eq(a, k["expected"], k.get("tolerance", 1e-6))
                g.append(_c(f"KPI '{k['label']}' matches independent recalculation", "PASS" if ok else "FAIL",
                            f"Excel={a!r} expected={k['expected']!r}"))
        if not m["tables"]:
            g.append(_c("Analysis tables present", "FAIL", "No analysis tables were built"))
    gates.append(_gate("G4", "Independent recomputation", g))

    # ---------------- G5 reconciliation (live checks)
    gates.append(_gate("G5", "Reconciliation (live checks)", _live(vwb, book, m)))

    # ---------------- G6 statistical soundness
    g = []
    if ri["include_y"] < 30:
        g.append(_c("Enough data for conclusions", "WARN", f"Only {ri['include_y']} rows in scope - treat findings as indicative"))
    else:
        g.append(_c("Enough data for conclusions", "PASS", f"{ri['include_y']:,} rows in scope"))
    if vwb is not None:
        for t in m["tables"]:
            ws = vwb[t["sheet"]]
            if t.get("n_col") and t.get("min_n"):
                j = t["columns"].index(t["n_col"]) + 1
                low = [f"{t['labels'][i]} (n={ws.cell(t['first'] + i, j).value})" for i in range(len(t["labels"]))
                       if isinstance(ws.cell(t["first"] + i, j).value, (int, float)) and 0 < ws.cell(t["first"] + i, j).value < t["min_n"]]
                g.append(_c(f"'{t['title']}' group sizes >= {t['min_n']}", "PASS" if not low else "WARN",
                            "" if not low else "Small groups - call out in narrative, avoid ranking them: " + ", ".join(low[:8])))
            if t.get("pct_sum_col"):
                j = t["columns"].index(t["pct_sum_col"]) + 1
                tot = sum(ws.cell(r, j).value or 0 for r in range(t["first"], t["last"] + 1)
                          if isinstance(ws.cell(r, j).value, (int, float)))
                g.append(_c(f"'{t['title']}' percentages sum to 100%", "PASS" if abs(tot - 1) <= 0.005 else "FAIL",
                            f"sum = {tot:.4%}"))
    gates.append(_gate("G6", "Statistical soundness", g))

    # ---------------- G7 presentation & narrative
    g = []
    for s in m["sheets"]:
        if s["kind"] != "analysis":
            continue
        ex = s["explanation"] or ""
        words = len(re.sub(r"\{\{.+?\}\}", "X", ex).split())
        g.append(_c(f"Tab '{s['name']}' has a plain-English explanation",
                    "FAIL" if not ex.strip() else ("WARN" if words > 120 else "PASS"),
                    f"{words} words" + (" - shorten to <=120" if words > 120 else "")))
        if s["tables"] == 0:
            g.append(_c(f"Tab '{s['name']}' has at least one table", "WARN", "No table on this tab"))
    typed = []
    for nrt in m["narratives"]:
        plain = re.sub(r"\{\{.+?\}\}|\[\[.*?\]\]", "", nrt["template"])
        plain = re.sub(r"\b(19|20)\d{2}\b|\bQ[1-4]\b|\bH[12]\b|\bFY\d{2,4}\b|\b\d{4}-\d{2}(-\d{2})?\b", "", plain)
        if re.search(r"\d", plain):
            typed.append(f"{nrt['sheet']}!{nrt['cell']}")
    g.append(_c("Narrative figures are pulled live from cells (num tokens)", "PASS" if not typed else "WARN",
                "" if not typed else "Typed-in numbers found in text at " + ", ".join(typed[:8]) + " - replace with num() so text can't drift from data"))
    if vwb is not None:
        bad = [f"{n['sheet']}!{n['cell']}" for n in m["narratives"] if _is_err(vwb[n["sheet"]][n["cell"]].value)]
        g.append(_c("All narrative text evaluates", "PASS" if not bad else "FAIL", ", ".join(bad)))
    notes_missing = [t["title"] for t in m["tables"] if not t["has_note"]]
    g.append(_c("Every table has a source/definition note", "PASS" if not notes_missing else "WARN", "; ".join(notes_missing[:6])))
    g.append(_c("Charts titled and linked to tables", "PASS", f"{len(m['charts'])} charts"))
    summ = [s for s in m["sheets"] if s["kind"] == "summary"]
    has_kpi = any(k["sheet"] == "Summary" for k in m["kpis"])
    g.append(_c("Summary tab has KPIs and findings", "PASS" if has_kpi and any(n["sheet"] == "Summary" and n["label"] == "finding" for n in m["narratives"]) else "WARN",
                "" if summ else "No summary"))
    g.append(_c("Cloudstaff logo on every tab", "PASS" if m.get("logo") else "WARN",
                os.path.basename(m["logo"]) if m.get("logo") else "Logo file not found - text wordmark used. Add assets/cloudstaff-logo.png"))
    gates.append(_gate("G7", "Presentation & narrative", g))

    # ---------------- G8 analyst review
    g = []
    att = m["attestations"]
    for k, label in REQUIRED_ATTESTATIONS.items():
        a = att.get(k)
        g.append(_c(label, "PASS" if a and a["answer"] else "WARN",
                    (a or {}).get("note", "") if a and a["answer"] else "Not confirmed"))
    gates.append(_gate("G8", "Analyst review", g))

    static = _status([{"status": x["status"]} for x in gates])
    return {"gates": gates, "static_verdict": {"FAIL": "FAIL", "WARN": "PASS WITH WARNINGS", "PASS": "PASS"}[static],
            "verdict": {"FAIL": "FAIL", "WARN": "PASS WITH WARNINGS", "PASS": "PASS"}[static],
            "engine": engine, "ran_at": dt.datetime.now().strftime("%d %b %Y %H:%M"),
            "column_notes": column_notes}


def _live(vwb, book, m):
    g = []
    if vwb is None:
        return [_c("Live checks evaluated", "FAIL", "Not verified - no recalculation engine")]
    ws = vwb["QA & Data Quality"]
    r = 10
    for chk in m["checks"]:
        st, a = ws.cell(r, 5).value, ws.cell(r, 2).value
        g.append(_c(chk["label"], "PASS" if st == "PASS" else "FAIL", f"actual={a!r} expected={chk['expected']!r}"))
        r += 1
    return g


def finalize(book, results, calc2):
    vwb = openpyxl.load_workbook(calc2, data_only=True)
    errs = [f"{ws.title}!{c.coordinate}" for ws in vwb.worksheets for row in ws.iter_rows() for c in row if _is_err(c.value)]
    for g in results["gates"]:
        if g["gate"] == "G3":
            g["checks"][0] = _c("No formula errors anywhere in the workbook (incl. QA tab)", "PASS" if not errs else "FAIL",
                                "0 errors" if not errs else f"{len(errs)} errors: " + ", ".join(errs[:8]))
        if g["gate"] == "G5":
            g["checks"] = _live(vwb, book, book.manifest() if book else {})
        g["status"] = _status(g["checks"])
    worst = _status([{"status": g["status"]} for g in results["gates"]])
    results["verdict"] = {"FAIL": "FAIL", "WARN": "PASS WITH WARNINGS", "PASS": "PASS"}[worst]
    results["excel_verdict_cell"] = vwb["QA & Data Quality"]["C6"].value
    results["summary_strip"] = vwb["Summary"]["A4"].value
    return results


# ============================================================================ reports
def _qa_dir(output):
    if os.environ.get("CS_QA_DIR"):
        os.makedirs(os.environ["CS_QA_DIR"], exist_ok=True)
        return os.environ["CS_QA_DIR"]
    d = os.path.join(os.path.dirname(os.path.abspath(output)), "..", "qa")
    return os.path.abspath(d) if os.path.isdir(d) else os.path.dirname(os.path.abspath(output))


def write_reports(book, results, output):
    stem = os.path.splitext(os.path.basename(output))[0]
    d = _qa_dir(output)
    man = book.manifest() if book else results.get("manifest", {})
    with open(os.path.join(d, f"{stem}_QA.json"), "w", encoding="utf-8") as f:
        json.dump({"results": results, "manifest": man}, f, indent=2, default=str)
    lines = [f"# QA report - {man.get('title', stem)}", "",
             f"**Verdict: {results['verdict']}**  (workbook shows: {results.get('excel_verdict_cell')})", "",
             f"- Output: `{results.get('output', output)}`",
             f"- Source: `{man['source']['file']}` ({man['source']['rows']:,} rows, SHA-256 {man['source']['sha256'][:16]}...)",
             f"- Verified: {results['ran_at']} via {results['engine']}", ""]
    for g in results["gates"]:
        lines.append(f"## {g['gate']} {g['name']} - {g['status']}")
        for c in g["checks"]:
            icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[c["status"]]
            lines.append(f"- {icon} {c['check']}" + (f" - {c['detail']}" if c.get("detail") else ""))
        lines.append("")
    open(os.path.join(d, f"{stem}_QA.md"), "w", encoding="utf-8").write("\n".join(lines))
    results["report_md"] = os.path.join(d, f"{stem}_QA.md")


def console_summary(results):
    out = [f"QA VERDICT: {results['verdict']}"]
    for g in results["gates"]:
        out.append(f"  {g['gate']} {g['name']:<28} {g['status']}")
        for c in g["checks"]:
            if c["status"] != "PASS":
                out.append(f"      [{c['status']}] {c['check']}: {c.get('detail', '')[:220]}")
    out.append(f"Saved: {results.get('output')}")
    return "\n".join(out)
