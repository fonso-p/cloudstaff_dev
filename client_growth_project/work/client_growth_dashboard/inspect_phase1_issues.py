"""Phase 1: data-quality checks and join coverage (read-only)."""
import re, pandas as pd, warnings
warnings.filterwarnings("ignore")
SP = "/private/tmp/claude-502/-Users-jobso-Documents-DATA-WS/5d3b381f-2e06-4d10-9860-171823845023/scratchpad/"
S = pd.read_pickle(SP + "STAFF.pkl"); C = pd.read_pickle(SP + "CLIENT.pkl")
EXTRACT = pd.Timestamp("2026-09-29")
S["sc"] = S["Shortcode"].fillna("").astype(str).str.strip()
S["ed"] = pd.to_datetime(S["Engagement Date"], errors="coerce"); S["dd"] = pd.to_datetime(S["Disengagement Date"], errors="coerce")
C["sc"] = C["Shortcode"].astype(str).str.strip()

print("== STAFF grain")
print("rows", len(S), "| distinct CSID", S.CSID.nunique(), "| CSIDs with >1 row", (S.CSID.value_counts() > 1).sum())
print("same CSID + same shortcode more than once:", S.duplicated(["CSID", "sc"]).sum(), "rows")
print("exact duplicate rows:", S.astype(str).duplicated().sum(), "| duplicate Engagement ID:", S["Engagement ID"].duplicated().sum())
for c in ["User Status", "Employment Status", "Category", "Engagement Status"]: print(c, S[c].value_counts().to_dict())
print("blank shortcode:", (S.sc == "").sum())
print("end before start:", (S.dd < S.ed).sum())
print("engagement date after extract:", (S.ed > EXTRACT).sum(), "| disengagement date after extract:", (S.dd > EXTRACT).sum(),
      "| max dates", S.ed.max().date(), S.dd.max().date())
print("engagement before 2013:", (S.ed < "2013-01-01").sum(), "| min", S.ed.min().date())
print("open stint but status disengage:", ((S.dd.isna()) & (S["Engagement Status"] == "disengage")).sum(),
      "| end date but status engage:", ((S.dd.notna()) & (S["Engagement Status"] == "engage")).sum())

print("\n== CLIENT file")
print("rows", len(C), "| distinct shortcodes", C.sc.nunique(), "| Active", C.Active.value_counts().to_dict(), "| Source", C.Source.value_counts().to_dict())
print("Date range", pd.to_datetime(C.Date).min().date(), "to", pd.to_datetime(C.Date).max().date())
print("duplicate client names:", C[C.Client.duplicated(keep=False)][["Client", "sc"]].values.tolist())
norm = lambda x: re.sub(r"\b(pty|ltd|llc|inc|limited|co|corp|corporation|the|group|holdings|pte|plc)\b", "", re.sub(r"[^a-z0-9 ]", " ", str(x).lower())).split()
C["nk"] = C.Client.map(lambda x: " ".join(norm(x)))
g = C.groupby("nk").sc.agg(list); g = g[g.map(len) > 1]
print("client names that look the same after cleaning (different shortcodes):", len(g)); print(g.head(15).to_string())
print("Timezone values:", C.Timezone.value_counts(dropna=False).head(30).to_dict())

print("\n== JOIN staff -> client on Shortcode")
ssc = set(S.sc[S.sc != ""]); csc = set(C.sc)
print("staff shortcodes", len(ssc), "| found in client file", len(ssc & csc), "| missing", len(ssc - csc))
miss = S[S.sc.isin(ssc - csc)]
print("staff rows on missing shortcodes", len(miss)); print(miss.groupby(["sc", "Client Name"]).size().sort_values(ascending=False).head(15).to_string())
print("client shortcodes with no staff ever:", len(csc - ssc))
nm = S[S.sc != ""].groupby("sc")["Client Name"].nunique(); print("shortcodes with >1 client name in staff file:", (nm > 1).sum())
x = S[S.sc != ""].drop_duplicates("sc").merge(C[["sc", "Client"]], on="sc")
print("staff 'Client Name' differs from client-file 'Client' (same shortcode):", (x["Client Name"].str.strip().str.lower() != x["Client"].str.strip().str.lower()).sum(), "of", len(x))
print(x[x["Client Name"].str.strip().str.lower() != x["Client"].str.strip().str.lower()][["sc", "Client Name", "Client"]].head(8).to_string())

print("\n== Internal / non-client candidates")
hub = S.Category.eq("Hub").groupby(S.sc).mean()
intl = C[C.Client.str.contains(r"(?i)cloudstaff|ready ?to ?go|\btest\b|^cs |opti ?bpo internal|disengaged staff", regex=True) | C.sc.str.match(r"^(CS|RTG|CIB)")]
print("client-file rows matching internal patterns:", len(intl)); print(intl[["sc", "Client"]].head(25).to_string())
print("shortcodes with >=50% Hub rows:", (hub >= 0.5).sum(), "| CSTREENGAGE rows:", (S.sc == "CSTREENGAGE").sum())

print("\n== Region from the older MyStaff list (27 Sep, has Region)")
O = pd.read_excel("data/raw/manager_movements/mystaff client list.xlsx", sheet_name="MyStaff", dtype=str).fillna("")
print("older list rows", len(O), "| new-file shortcodes found in older list", len(csc & set(O.Shortcode)), "of", len(csc),
      "| staff shortcodes found in older list", len(ssc & set(O.Shortcode)))
print("older Region values:", O.Region.value_counts().to_dict())
