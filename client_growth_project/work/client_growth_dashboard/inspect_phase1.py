"""Phase 1: read-only inspection of the staff and client files. Writes phase1_profile.md next to this script."""
import pandas as pd, warnings
warnings.filterwarnings("ignore")
STAFF = "data/Organic rate/SC Engagement List2026-09-29 11_25_26.xlsx"
CLIENT = "data/Organic rate/mystaff 10.9.xlsx"
OUT = "work/client_growth_dashboard/phase1_profile.md"

def kind(s):
    """Rough data type of a column from its non-blank values."""
    v = s.dropna()
    v = v[v.astype(str).str.strip() != ""]
    if v.empty: return "empty"
    if pd.api.types.is_datetime64_any_dtype(s): return "date"
    if pd.to_numeric(v, errors="coerce").notna().mean() > 0.95: return "number"
    if pd.to_datetime(v, errors="coerce").notna().mean() > 0.95: return "date (as text)"
    return "text"

lines = []
for name, path in [("STAFF", STAFF), ("CLIENT", CLIENT)]:
    df = pd.read_excel(path, sheet_name=0, dtype=object)
    raw_rows = len(df)
    df = df.dropna(how="all")                      # drop fully blank formatted rows
    lines += [f"## {name}: {path}", f"Rows with data: {len(df):,} (sheet reports {raw_rows:,} incl. blank rows); columns: {df.shape[1]}", "",
              "| # | Column | Type | Non-blank | Blank | Distinct | 5 samples |", "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(df.columns, 1):
        s = df[c]
        nb = s.dropna(); nb = nb[nb.astype(str).str.strip() != ""]
        samp = "; ".join(str(x)[:25] for x in nb.head(5))
        lines.append(f"| {i} | {c} | {kind(s)} | {len(nb):,} | {len(df)-len(nb):,} | {nb.astype(str).nunique():,} | {samp} |")
    lines.append("")
    df.to_pickle(f"/private/tmp/claude-502/-Users-jobso-Documents-DATA-WS/5d3b381f-2e06-4d10-9860-171823845023/scratchpad/{name}.pkl")
open(OUT, "w").write("\n".join(lines))
print("written", OUT)
