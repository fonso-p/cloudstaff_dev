"""Where everything lives: the ONE place that knows the folder layout. Every pipeline imports its paths from here.

Two roots, both outside the repo (the repo holds code and docs only):

  PROJECTS  OneDrive "Desktop/Projects": what people open and share (inputs, outputs, dashboards). Synced and backed up.
            Override: CS_PROJECTS_DIR.
  LOCAL     ~/cloudstaff_data: big or busy files that must NOT sync (public register downloads, SQLite databases,
            model caches). Override: CS_LOCAL_DIR.

  PROJECTS/
    Data/                                   shared internal exports (MyStaff, Staff Central, HubSpot); other projects read it too
    Marketing Intelligence Priority/        MI
      inputs/      written by people or other projects (Apollo exports, HubSpot reports, Client Propensity extract)
      outputs/     written only by MI code (lead grades, collected signals, Priority Score data, industry trends)
      dashboards/  built HTML pages, one folder per dashboard, dated file names
      archive/     experiments and mock files kept for reference; nothing reads them
    Client Propensity/Data/                 Client Propensity's raw files and outputs
  LOCAL/
    cache/registers/   Companies House, PSC, CQC, Find a Tender, charity downloads (re-downloadable)
    cache/models/      the event classifier cache, trained models
    work/signals/      the general scraper database (segments, sample runs) and its scratch output
    work/lead_lists/<list>/   one lead list's scraper database, company list and API caches
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _projects() -> Path:
    if os.environ.get("CS_PROJECTS_DIR"):
        return Path(os.environ["CS_PROJECTS_DIR"])
    home = Path.home()
    options = [home / "OneDrive - Cloudstaff Pty Ltd" / "Desktop" / "Projects", home / "Desktop" / "Projects"]
    return next((p for p in options if p.exists()), options[0])


PROJECTS = _projects()
LOCAL = Path(os.environ.get("CS_LOCAL_DIR", Path.home() / "cloudstaff_data"))

# ---------------------------------------------------------------- shared
SHARED_DATA = PROJECTS / "Data"                                  # MyStaff, Staff Central, HubSpot exports
STAFF_REPORT_GLOB = "**/Staff Report with Details*.xlsx"          # under SHARED_DATA; JP titles only
CACHE = LOCAL / "cache"
REGISTERS = CACHE / "registers"
MODELS = CACHE / "models"
WORK = LOCAL / "work"
SIGNALS_WORK = WORK / "signals"
COMPETITOR_MAP = PROJECTS / "Competitor Analysis (client scrape)" / "data" / "competitor_clients.csv"

# ---------------------------------------------------------------- Marketing Intelligence
MI = PROJECTS / "Marketing Intelligence Priority"
MI_INPUTS = MI / "inputs"
MI_OUTPUTS = MI / "outputs"
MI_DASHBOARDS = MI / "dashboards"
MI_ARCHIVE = MI / "archive"
APOLLO_INPUTS = MI_INPUTS / "apollo"
HUBSPOT_INPUTS = MI_INPUTS / "hubspot"
MYSTAFF_INPUTS = MI_INPUTS / "mystaff"
PROPENSITY_INPUTS = MI_INPUTS / "propensity"                      # Client Propensity copies its extract here
ACCOUNT_PRIORITY_OUT = MI_OUTPUTS / "account_priority"            # priority_company_info_combined*.xlsx + dashboard JSON
SEGMENTS_OUT = MI_OUTPUTS / "segments"                            # scraper segment mode: industry_trend.csv and friends
INDUSTRY_TRENDS_OUT = MI_OUTPUTS / "industry_trends"

# ---------------------------------------------------------------- Client Propensity
CLIENT_PROPENSITY = PROJECTS / "Client Propensity"
CLIENT_PROPENSITY_DATA = CLIENT_PROPENSITY / "Data"
YOGA_INPUTS = CLIENT_PROPENSITY_DATA / "Yoga"                     # AMER / APAC growth-opportunity research files
CLIENT_SIZE_OUT = CLIENT_PROPENSITY_DATA / "client_size"


def lead_list(name: str) -> dict:
    """Every folder one lead list uses (its settings: Marketing Intelligence/lead_lists/<name>/list.toml)."""
    return {"inputs": APOLLO_INPUTS / name.removeprefix("apollo_"),
            "work": WORK / "lead_lists" / name,                   # news.db, adzuna.db, companies.csv, API caches
            "collected": MI_OUTPUTS / "collected" / name,         # scraper + register outputs grading reads
            "grades": MI_OUTPUTS / "lead_grades" / name}          # lead_grades_<name>.xlsx/.json, owners_to_find_<date>.csv


def add_list_args(ap, out=True):
    """--list NAME (default apollo_emea) plus --companies / --db / --out, which default to that list's folders."""
    ap.add_argument("--list", default="apollo_emea", help="lead list whose folders are the defaults (paths.lead_list)")
    ap.add_argument("--companies", help="default: <work>/companies.csv")
    ap.add_argument("--db", help="default: <work>/news.db")
    if out:
        ap.add_argument("--out", help="default: the list's collected folder")


def resolve_list_args(a):
    """Fill the defaults add_list_args left blank; also sets a.work (the list's work folder). Returns a."""
    L = lead_list(a.list)
    a.work = str(L["work"])
    a.companies = a.companies or str(L["work"] / "companies.csv")
    a.db = a.db or str(L["work"] / "news.db")
    if hasattr(a, "out"):
        a.out = a.out or str(L["collected"])
    return a


def newest(folder, pattern: str, exclude: tuple = ()) -> Path | None:
    """The newest file matching pattern in folder, by name (file names start or end with a date). Names containing any
    `exclude` string are skipped. None when there is none."""
    files = sorted(p for p in Path(folder).glob(pattern) if not any(x in p.name for x in exclude))
    return files[-1] if files else None


def staff_report() -> Path | None:
    """The newest Staff Central 'Staff Report with Details' anywhere under SHARED_DATA (by modified time: the names
    carry the date as dd-Mon-yyyy, which doesn't sort)."""
    files = sorted(SHARED_DATA.glob(STAFF_REPORT_GLOB), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def ensure(*folders: Path) -> None:
    for f in folders:
        Path(f).mkdir(parents=True, exist_ok=True)
