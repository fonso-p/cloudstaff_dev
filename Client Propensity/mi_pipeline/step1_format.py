"""Step 1: load the raw files and clean them (types, blanks, IDs, dates). No joins here."""
import pickle
from pathlib import Path

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
    df["jp_title"]      = clean_text(df["JP Title (All)"])
    df["designation"]   = clean_text(df["Designation (All)"])
    df["_eng_date"]     = clean_date(df["Engagement Date"])          # '0000-00-00' -> NaT
    df["_engaged"]      = clean_text(df["Engagement Status (All)"]).str.lower().eq("engage").fillna(False).astype(bool)
    df = df[df["CSID"].notna()]
    n_dupe_rows = int(df["CSID"].duplicated().sum())
    # A few CSIDs appear more than once: keep the currently engaged row, then the latest engagement
    df = (df.sort_values(["CSID", "_engaged", "_eng_date"], ascending=[True, False, False], na_position="last")
            .drop_duplicates("CSID"))
    return df, n_dupe_rows


def load_dashboard_seats(log=print):
    """Current seats per client from the dashboard's processed data: cs_staff_current (MyStaff Total Staff) on the
    priority_list sheet of the newest config.DASHBOARD_DATA_GLOB file. Returns (Series shortcode -> seats, file name),
    or (None, None) when CURRENT_SEATS_SOURCE isn't "dashboard" or no file is found."""
    if config.CURRENT_SEATS_SOURCE != "dashboard" or config.DASHBOARD_FEED_DIR is None:
        return None, None
    files = sorted(Path(config.DASHBOARD_FEED_DIR).glob(config.DASHBOARD_DATA_GLOB), key=lambda p: p.stat().st_mtime)
    if not files:
        log(f"[1 format] WARNING: no {config.DASHBOARD_DATA_GLOB} in {config.DASHBOARD_FEED_DIR}; current seats come from the engagement list")
        return None, None
    df = pd.read_excel(files[-1], sheet_name="priority_list", usecols=["shortcode", "cs_staff_current"], dtype={"shortcode": str})
    df["shortcode"] = clean_id(df["shortcode"])
    df = df.dropna(subset=["shortcode"]).drop_duplicates("shortcode")
    seats = pd.to_numeric(df["cs_staff_current"], errors="coerce").set_axis(df["shortcode"].astype(str)).dropna()
    return seats, files[-1].name

def run(today, log=print):
    raw = {name: load_raw(name) for name in config.RAW_FILES}
    staff, n_dupe = format_staffcentral(raw["staffcentral"])
    out = {
        "engagement": format_engagement(raw["engagement"], today),
        "mystaff":    format_mystaff(raw["mystaff"]),
        "staff":      staff,
    }
    out["current_seats"], out["current_seats_file"] = load_dashboard_seats(log)
    log(f"[1 format] engagement rows {len(out['engagement'])} | "
        f"MyStaff accounts {len(out['mystaff'])} | StaffCentral staffers {len(staff)} ({n_dupe} duplicate CSID rows dropped) | "
        + (f"current seats: {len(out['current_seats'])} clients from {out['current_seats_file']}" if out["current_seats"] is not None
           else "current seats: engagement list"))
    return out
