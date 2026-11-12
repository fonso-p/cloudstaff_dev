"""Step 1: load the raw files and clean them (types, blanks, IDs, dates). No joins here."""
import pickle

import pandas as pd

import config


# ---------------------------------------------------------------- type helpers (used by every step)
def clean_id(s):
    """Trimmed text; blanks -> NA; '12345.0' -> '12345' (IDs read as numbers in one file)."""
    s = s.astype("string").str.strip().replace("", pd.NA)
    return s.str.replace(r"\.0+$", "", regex=True)

def clean_text(s):
    """Trimmed text; blanks -> NA."""
    return s.astype("string").str.strip().replace("", pd.NA)

def clean_date(s, fill=None):
    """datetime64[ns] with the time stripped, so both sides of a join are plain calendar dates."""
    d = pd.to_datetime(s, errors="coerce").dt.normalize()
    if fill is not None:
        d = d.fillna(fill)
    return d.astype("datetime64[ns]")


# ---------------------------------------------------------------- loading (with a cache outside the repo)
def load_raw(name: str) -> pd.DataFrame:
    """Read one raw file listed in config.RAW_FILES. Cached as a pickle until the file changes."""
    file, sheet, cols = config.RAW_FILES[name]
    path = config.DATA_DIR / file
    if not path.exists():
        raise FileNotFoundError(f"Raw file not found: {path}\nSet config.DATA_DIR or the MIA_DATA_DIR environment variable.")
    stamp = (path.stat().st_mtime, path.stat().st_size, sheet, tuple(cols or ()))
    cache = config.CACHE_DIR / f"{name}.pkl" if config.CACHE_DIR else None
    if cache and cache.exists():
        saved = pickle.loads(cache.read_bytes())
        if saved["stamp"] == stamp:
            return saved["df"]
    df = pd.read_excel(path, sheet_name=sheet, usecols=cols)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps({"stamp": stamp, "df": df}))
    return df


# ---------------------------------------------------------------- formatting, one function per file
def format_engagement(raw, today):
    """One row per placement (staffer x client)."""
    df = raw.copy()
    df["Shortcode"]          = clean_id(df["Shortcode"])
    df["Engagement ID"]      = clean_id(df["Engagement ID"])
    df["Username"]           = clean_text(df["Username"])
    df["engagement_date"]    = clean_date(df["Engagement Date"])
    df["disengagement_date"] = clean_date(df["Disengagement Date"], fill=today)
    return df

def format_seat_churn(raw, today):
    """Exit reasons per placement. Columns get a _seat_churn suffix so the join can't clash."""
    df = raw.copy().add_suffix("_seat_churn")
    df["Shortcode_seat_churn"]          = clean_id(df["Shortcode_seat_churn"])
    df["Engagement ID_seat_churn"]      = clean_id(df["Engagement ID_seat_churn"])
    df["Username_seat_churn"]           = clean_text(df["Username_seat_churn"])
    df["engagement_date_seat_churn"]    = clean_date(df["Engagement Date_seat_churn"])
    df["disengagement_date_seat_churn"] = clean_date(df["Disengagement Date_seat_churn"], fill=today)
    return df.drop_duplicates()   # after cleaning, so 123 vs " 123 " collapse too

def format_mystaff(raw):
    """One row per client account. The sheet has ~1M blank rows; they are dropped."""
    df = raw.copy()
    df["Shortcode"] = clean_id(df["Shortcode"])
    # CRM Company ID = the HubSpot company Record ID (the dashboard's primary join key to HubSpot)
    df["crm_company_id"] = pd.to_numeric(df["CRM Company ID"], errors="coerce").astype("Int64")
    return df[df["Shortcode"].notna()].reset_index(drop=True)

def format_staffcentral(raw):
    """One row per staffer with their CURRENT department (StaffCentral is a snapshot)."""
    df = raw.copy()
    df["CSID"]          = clean_id(df["CSID"])
    df["Engagement ID"] = clean_id(df["Engagement ID"])
    df["department"]    = clean_text(df["Department (All)"])
    df["jp_category"]   = clean_text(df["JP Category (All)"])
    df["designation"]   = clean_text(df["Designation (All)"])
    df["_eng_date"]     = clean_date(df["Engagement Date"])          # '0000-00-00' -> NaT
    df["_engaged"]      = clean_text(df["Engagement Status (All)"]).str.lower().eq("engage").fillna(False).astype(bool)
    df = df[df["CSID"].notna()]
    n_dupe_rows = int(df["CSID"].duplicated().sum())
    # A few CSIDs appear more than once: keep the currently engaged row, then the latest engagement
    df = (df.sort_values(["CSID", "_engaged", "_eng_date"], ascending=[True, False, False], na_position="last")
            .drop_duplicates("CSID"))
    return df, n_dupe_rows


def run(today, log=print):
    raw = {name: load_raw(name) for name in config.RAW_FILES}
    staff, n_dupe = format_staffcentral(raw["staffcentral"])
    out = {
        "engagement": format_engagement(raw["engagement"], today),
        "seat_churn": format_seat_churn(raw["seat_churn"], today),
        "mystaff":    format_mystaff(raw["mystaff"]),
        "staff":      staff,
    }
    log(f"[1 format] engagement rows {len(out['engagement'])} | seat churn rows {len(out['seat_churn'])} | "
        f"MyStaff accounts {len(out['mystaff'])} | StaffCentral staffers {len(staff)} ({n_dupe} duplicate CSID rows dropped)")
    return out
