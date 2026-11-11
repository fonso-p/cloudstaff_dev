"""Load a raw file losslessly, profile it, and flag row-level data quality issues.

CLI:
    python profile_data.py <raw_file> [--sheet NAME] [--header-row N] [--out DIR]
Writes <out>/<stem>_profile.json and <stem>_profile.md and prints the markdown.

Library:
    from profile_data import load_source, profile, row_issues
    df, meta = load_source(path)
    prof = profile(df, meta)
    issues = row_issues(df, required=[...], numeric=[...], dates=[...], ids=[...],
                        allowed={col: [...]}, ranges={col: (lo, hi)})

Principle: the loader never "fixes" anything. Values are kept exactly as received,
except conversions that are provably lossless (text "125" -> number 125, text
"2026-01-31" -> date). Anything ambiguous ("1,200", "$50", "N/A", "31/01/26")
stays as text and is reported, so a human decides how to treat it.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys

import pandas as pd

PLACEHOLDERS = {"n/a", "na", "null", "none", "nil", "-", "--", "?", "#n/a", "tbc", "tbd",
                "unknown", "not available", "blank", "0000-00-00", "#ref!", "#value!"}
INT_RE = re.compile(r"^-?(0|[1-9]\d*)$")
DEC_RE = re.compile(r"^-?(0|[1-9]\d*)\.\d+$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
LOOSE_NUM_RE = re.compile(r"^\(?-?[$₱€£]?\s?-?[\d,]+(\.\d+)?\)?%?$")
LOOSE_DATE_RE = re.compile(r"^\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}$")


# --------------------------------------------------------------------------- loading
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _lossless(v):
    """Convert a text cell only when the conversion loses nothing."""
    if not isinstance(v, str):
        return v
    s = v
    if s == "":
        return None
    if INT_RE.match(s) and len(s) <= 15:
        return int(s)
    if DEC_RE.match(s) and len(s) <= 16:
        return float(s)
    if ISO_DATE_RE.match(s):
        try:
            return dt.datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return v
    if ISO_DT_RE.match(s):
        try:
            return dt.datetime.fromisoformat(s.replace("T", " "))
        except ValueError:
            return v
    return v


def _clean_excel_value(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            return v.item()
        except Exception:
            return v
    return v


def load_source(path, sheet=None, header_row=0):
    """Return (df, meta). df has object dtype and original column order/names."""
    ext = os.path.splitext(path)[1].lower()
    meta = {"path": os.path.abspath(path), "file": os.path.basename(path),
            "sha256": sha256(path), "bytes": os.path.getsize(path),
            "loaded_at": dt.datetime.now().isoformat(timespec="seconds"),
            "sheet": None, "header_row": header_row}
    if ext in (".csv", ".tsv", ".txt"):
        sep = "\t" if ext == ".tsv" else None
        last_err = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                df = pd.read_csv(path, dtype=str, keep_default_na=False, sep=sep,
                                 engine="python", encoding=enc, header=header_row)
                meta["encoding"] = enc
                break
            except UnicodeDecodeError as e:
                last_err = e
        else:
            raise last_err
        df = df.astype(object).apply(lambda col: col.map(_lossless))
    elif ext in (".xlsx", ".xlsm", ".xls"):
        xls = pd.ExcelFile(path)
        meta["sheets_in_file"] = xls.sheet_names
        use = sheet if sheet is not None else xls.sheet_names[0]
        meta["sheet"] = use
        df = pd.read_excel(path, sheet_name=use, dtype=object, header=header_row)
        df = df.apply(lambda col: col.map(_clean_excel_value))
        df = df.apply(lambda col: col.map(lambda v: _lossless(v) if isinstance(v, str) else v))
    elif ext == ".json":
        df = pd.json_normalize(json.load(open(path, encoding="utf-8")))
        df = df.astype(object).apply(lambda col: col.map(_clean_excel_value))
    elif ext == ".parquet":
        df = pd.read_parquet(path).astype(object).apply(lambda col: col.map(_clean_excel_value))
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    df = df.astype(object).where(pd.notna(df), None)
    meta["rows"], meta["cols"] = int(df.shape[0]), int(df.shape[1])
    meta["columns"] = [str(c) for c in df.columns]
    # control totals, computed straight from the source (used by QA Gate 1)
    totals = {}
    for c in df.columns:
        nums = [v for v in df[c] if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if nums and len(nums) >= 0.5 * max(1, sum(v is not None for v in df[c])):
            totals[str(c)] = {"sum": float(sum(nums)), "count": len(nums)}
    meta["control_totals"] = totals
    return df, meta


# --------------------------------------------------------------------------- profiling
def _kind(v):
    if v is None:
        return "blank"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, (dt.datetime, dt.date)):
        return "date"
    return "text"


def _is_placeholder(v):
    return isinstance(v, str) and v.strip().lower() in PLACEHOLDERS


def profile(df, meta=None):
    meta = meta or {}
    n = len(df)
    cols = []
    for c in df.columns:
        s = df[c]
        kinds = s.map(_kind).value_counts().to_dict()
        texts = [v for v in s if isinstance(v, str)]
        nums = [float(v) for v in s if _kind(v) == "number"]
        dates = [v for v in s if _kind(v) == "date"]
        blanks = int(kinds.get("blank", 0))
        ws_only = sum(1 for v in texts if v.strip() == "")
        placeholders = sum(1 for v in texts if _is_placeholder(v))
        padded = sum(1 for v in texts if v != v.strip() and v.strip() != "")
        loose_nums = sum(1 for v in texts if LOOSE_NUM_RE.match(v.strip()) and not _is_placeholder(v))
        loose_dates = sum(1 for v in texts if LOOSE_DATE_RE.match(v.strip()))
        non_blank = [v for v in s if v is not None]
        info = {
            "column": str(c), "non_blank": n - blanks, "blank": blanks,
            "blank_pct": round(blanks / n, 4) if n else 0,
            "whitespace_only": ws_only, "placeholder_values": placeholders,
            "effective_missing": blanks + ws_only + placeholders,
            "types": {k: int(v) for k, v in kinds.items()},
            "distinct": int(pd.Series([str(v) for v in non_blank]).nunique()) if non_blank else 0,
            "padded_text": padded,
        }
        info["effective_missing_pct"] = round(info["effective_missing"] / n, 4) if n else 0
        real_types = [k for k in kinds if k != "blank"]
        info["mixed_types"] = len(real_types) > 1
        if loose_nums:
            info["numbers_stored_as_text"] = loose_nums
        if loose_dates:
            info["ambiguous_date_text"] = loose_dates
        if nums:
            ser = pd.Series(nums)
            q1, q3 = ser.quantile(0.25), ser.quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            info["numeric"] = {
                "count": len(nums), "sum": float(ser.sum()), "min": float(ser.min()),
                "max": float(ser.max()), "mean": float(ser.mean()), "median": float(ser.median()),
                "std": float(ser.std()) if len(nums) > 1 else 0.0,
                "negatives": int((ser < 0).sum()), "zeros": int((ser == 0).sum()),
                "iqr_outliers": int(((ser < lo) | (ser > hi)).sum()) if iqr > 0 else 0,
                "outlier_bounds": [float(lo), float(hi)],
            }
        if dates:
            ds = pd.Series(pd.to_datetime(dates))
            today = pd.Timestamp.today().normalize()
            info["dates"] = {"count": len(dates), "min": str(ds.min().date()), "max": str(ds.max().date()),
                             "future": int((ds > today).sum()), "before_1990": int((ds.dt.year < 1990).sum())}
        if texts and info["distinct"] <= 50:
            vc = pd.Series([v for v in texts]).value_counts()
            info["top_values"] = {str(k): int(v) for k, v in vc.head(15).items()}
            norm = {}
            for v in vc.index:
                norm.setdefault(re.sub(r"\s+", " ", str(v)).strip().lower(), []).append(str(v))
            variants = {k: v for k, v in norm.items() if len(v) > 1}
            if variants:
                info["spelling_or_case_variants"] = variants
        name = str(c).lower()
        if re.search(r"(^|_|\s)(id|code|no|number|ref|key)($|_|\s)", name) or name.endswith("id"):
            keyvals = [str(v).strip() for v in s if v is not None]
            dup = pd.Series(keyvals).duplicated(keep=False).sum() if keyvals else 0
            info["looks_like_id"] = True
            info["duplicate_ids"] = int(dup)
        cols.append(info)

    header_issues = []
    for c in df.columns:
        sc = str(c)
        if sc.startswith("Unnamed") or sc.strip() == "":
            header_issues.append(f"Column with no header: '{sc}' (possible title rows above the header?)")
        if sc != sc.strip():
            header_issues.append(f"Header has leading/trailing spaces: '{sc}'")
    dups = [c for c in pd.Series([str(c) for c in df.columns]).loc[lambda s: s.duplicated()]]
    if dups:
        header_issues.append(f"Duplicate header names: {dups}")

    as_str = df.astype(str)
    dup_rows = int(as_str.duplicated(keep=False).sum())
    empty_rows = int(df.isna().all(axis=1).sum())
    return {
        "source": {k: meta.get(k) for k in ("file", "sha256", "rows", "cols", "sheet", "sheets_in_file", "encoding")},
        "rows": n, "cols": int(df.shape[1]),
        "exact_duplicate_rows": dup_rows, "fully_empty_rows": empty_rows,
        "header_issues": header_issues, "columns": cols,
        "control_totals": meta.get("control_totals", {}),
        "excel_row_limit_ok": n <= 1_048_000,
    }


def profile_markdown(p):
    out = [f"# Data profile - {p['source'].get('file')}", "",
           f"- Rows: **{p['rows']:,}**  |  Columns: **{p['cols']}**"
           + (f"  |  Sheet: {p['source']['sheet']} (file has: {p['source'].get('sheets_in_file')})" if p['source'].get('sheet') else ""),
           f"- SHA-256: `{p['source'].get('sha256', '')[:16]}...`",
           f"- Exact duplicate rows: **{p['exact_duplicate_rows']}**  |  Fully empty rows: **{p['fully_empty_rows']}**"]
    if not p["excel_row_limit_ok"]:
        out.append("- **STOP: more rows than Excel allows. Aggregate or split before building.**")
    for h in p["header_issues"]:
        out.append(f"- Header issue: {h}")
    out += ["", "| Column | Types | Missing* | Missing % | Distinct | Flags |", "|---|---|---|---|---|---|"]
    for c in p["columns"]:
        flags = []
        if c["mixed_types"]:
            flags.append("mixed types")
        if c.get("numbers_stored_as_text"):
            flags.append(f"{c['numbers_stored_as_text']} numbers stored as text")
        if c.get("ambiguous_date_text"):
            flags.append(f"{c['ambiguous_date_text']} ambiguous date text")
        if c["padded_text"]:
            flags.append(f"{c['padded_text']} leading/trailing spaces")
        if c["placeholder_values"]:
            flags.append(f"{c['placeholder_values']} placeholders (N/A, -, ...)")
        if c.get("spelling_or_case_variants"):
            flags.append("variants: " + "; ".join(" / ".join(v) for v in list(c["spelling_or_case_variants"].values())[:3]))
        if c.get("duplicate_ids"):
            flags.append(f"{c['duplicate_ids']} rows share a duplicate ID")
        nm = c.get("numeric")
        if nm:
            if nm["negatives"]:
                flags.append(f"{nm['negatives']} negative")
            if nm["iqr_outliers"]:
                flags.append(f"{nm['iqr_outliers']} outliers (IQR)")
        d = c.get("dates")
        if d:
            flags.append(f"range {d['min']} to {d['max']}")
            if d["future"]:
                flags.append(f"{d['future']} future dates")
            if d["before_1990"]:
                flags.append(f"{d['before_1990']} dates before 1990")
        types = ", ".join(f"{k}:{v}" for k, v in c["types"].items() if k != "blank")
        out.append(f"| {c['column']} | {types} | {c['effective_missing']} | {c['effective_missing_pct']:.1%} | {c['distinct']} | {'; '.join(flags)} |")
    out += ["", "*Missing = blank + whitespace-only + placeholder values."]
    if p["control_totals"]:
        out += ["", "Control totals (from the source file):", ""]
        for k, v in p["control_totals"].items():
            out.append(f"- {k}: sum {v['sum']:,.4f} over {v['count']:,} numeric cells")
    return "\n".join(out)


# --------------------------------------------------------------------------- row flags
def row_issues(df, required=(), numeric=(), dates=(), ids=(), allowed=None, ranges=None,
               no_future=(), custom=None):
    """Return one string per row listing its data quality issues ('' = clean).

    required  : columns that must not be missing
    numeric   : columns that must be numbers
    dates     : columns that must be real dates
    ids       : columns that must be unique
    allowed   : {col: [valid values]}  (compared after trimming, case-insensitive)
    ranges    : {col: (min, max)}      (None = open bound)
    no_future : date columns that cannot be after today
    custom    : [(label, fn(row)->bool is_problem)]
    """
    allowed = allowed or {}
    ranges = ranges or {}
    custom = custom or []
    today = dt.datetime.now()
    dup_masks = {}
    for c in ids:
        key = df[c].map(lambda v: None if v is None else str(v).strip())
        dup_masks[c] = key.notna() & key.duplicated(keep=False)
    as_str = df.astype(str)
    dup_row = as_str.duplicated(keep="first")
    out = []
    for i, row in df.iterrows():
        issues = []
        if dup_row.loc[i]:
            issues.append("Exact duplicate of an earlier row")
        for c in required:
            v = row[c]
            if v is None or (isinstance(v, str) and (v.strip() == "" or _is_placeholder(v))):
                issues.append(f"Missing {c}")
        for c in numeric:
            v = row[c]
            if v is not None and _kind(v) != "number" and not _is_placeholder(v):
                issues.append(f"{c} not a number ('{v}')")
        for c in dates:
            v = row[c]
            if v is not None and _kind(v) != "date" and not _is_placeholder(v):
                issues.append(f"{c} not a valid date ('{v}')")
        for c in no_future:
            v = row[c]
            if _kind(v) == "date" and v > today:
                issues.append(f"{c} is in the future")
        for c, mask in dup_masks.items():
            if mask.loc[i]:
                issues.append(f"Duplicate {c}")
        for c, vals in allowed.items():
            v = row[c]
            ok = {str(x).strip().lower() for x in vals}
            if v is not None and str(v).strip().lower() not in ok and not _is_placeholder(v):
                issues.append(f"{c} unexpected value ('{v}')")
            elif isinstance(v, str) and v != v.strip():
                issues.append(f"{c} has extra spaces")
        for c, (lo, hi) in ranges.items():
            v = row[c]
            if _kind(v) == "number" and ((lo is not None and v < lo) or (hi is not None and v > hi)):
                issues.append(f"{c} out of range ({v})")
        for label, fn in custom:
            try:
                if fn(row):
                    issues.append(label)
            except Exception:
                issues.append(f"Check failed: {label}")
        out.append("; ".join(dict.fromkeys(issues)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--sheet")
    ap.add_argument("--header-row", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    df, meta = load_source(a.path, a.sheet, a.header_row)
    p = profile(df, meta)
    md = profile_markdown(p)
    out = a.out or os.path.dirname(os.path.abspath(a.path))
    os.makedirs(out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.path))[0]
    json.dump(p, open(os.path.join(out, f"{stem}_profile.json"), "w"), indent=2, default=str)
    open(os.path.join(out, f"{stem}_profile.md"), "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    sys.exit(main())
