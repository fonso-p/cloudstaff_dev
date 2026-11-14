"""Settings for the Client Propensity pipeline.

Change settings here, not in the step files. Every step reads from this module.
"""
import os
from pathlib import Path

import pandas as pd

# ============================================================ Paths
PROJECT_DIR = Path(__file__).resolve().parent

# The raw files are confidential and stay OUTSIDE the repo. To use another folder, set the
# MIA_DATA_DIR environment variable instead of editing this line.
DATA_DIR = Path(os.environ.get(
    "MIA_DATA_DIR",
    r"C:\Users\Alfonso(FonsoP)Panli\Desktop\Projects\Client Propensity\Data"))

# file name, sheet, columns to read (None = all). Reading only the needed columns keeps personal
# data (addresses, birthdays, etc.) out of memory and makes loading much faster.
RAW_FILES = {
    "engagement": ("SC Engagement List2026-10-07 07_48_09.xlsx", 0, None),
    "mystaff": ("CONFIDENTIAL Mystaff 10052026.xlsx", "MyStaff",
                ["Shortcode", "Client", "Active", "CRM Company ID", "Industry Roll Up", "Industry Hubspot",
                 "Office Address State", "Office Address Country", "Internal (Yes / No)"]),
    "staffcentral": ("StaffCentral 09142026.xlsx", 0,
                     ["CSID", "Department (All)", "JP Category (All)", "JP Title (All)", "Designation (All)",
                      "Engagement ID", "Engagement Status (All)", "Engagement Date"]),
}

# Loaded raw files are cached as pickles next to the data (outside the repo) and refreshed
# automatically when a source file changes. Set to None to always read the Excel files.
CACHE_DIR = DATA_DIR / "_pipeline_cache"

# Outputs list client names and scores, so they're saved next to the raw data, outside the repo.
# Override with the MIA_OUTPUT_DIR environment variable.
OUTPUT_DIR = Path(os.environ.get("MIA_OUTPUT_DIR", DATA_DIR))   # local data folder, outside the repo

# "Today" for every calculation. None = the day the pipeline runs. Set a date to reproduce a run.
AS_OF_DATE = None

def as_of() -> pd.Timestamp:
    return pd.Timestamp(AS_OF_DATE or pd.Timestamp.today()).normalize()

# ============================================================ Step 2: merging
# Department (role_group) = StaffCentral 'JP Category (All)'. 'Department (All)' is deprecated and used only to
# impute a blank category. Blank categories are imputed in this order, each step learned from staff whose category
# is known; a value is used only if at least min_staff staff share the key and at least min_share of them share
# one category. Imputed rows are flagged (role_group_source, role_group_imputed). Still blank = Unknown (left out of
# the department history). Held-out accuracy (2026-11-12): JP Title 96%, Designation 91%, Department 92%.
#   (label,         staff column,      min_staff, min_share)
JP_IMPUTE_STEPS = [
    ("JP Title",    "jp_title",        1,         0.0),
    ("Designation", "designation_key", 5,         0.6),
    ("Department",  "department",      10,        0.8),   # only departments that map cleanly to one category
]
# Tiny or duplicate JP Categories merged before anything else (None = treat as blank)
JP_CATEGORY_MAP = {"Design & Multimedia": "Creative, Design & Multimedia",
                   "Technical Support Services": "IT Network Systems/Support",
                   "Ecommerce IT": "Ecommerce",
                   "Coworker": None}
ROLE_GROUP_MAP = {}                     # optional merges after imputation, e.g. {"BPO Voice (Sales) Specialist": "BPO Voice"}
GENERIC_DESIGNATIONS = {"executive services specialist", "executive service specialist", "for executive services",
                        "team leader", "ess"}   # say nothing about the work: never used to impute
# Words removed from a designation before it is matched (regex fragments): seniority and training status
# ("Associate Accountant OJT" -> "accountant"). Roman numerals and "Level N" are always removed.
DESIGNATION_DROP_WORDS = [r"senior", r"sr\.?", r"junior", r"jr\.?", r"associate", r"lead",
                          r"ojt", r"trainee", r"intern", r"apprentice"]

# The department groupings (merges, imputation rules and the lookups learned on each run) are written to this
# folder in the repo, as documentation (no client or staff data: category, title, designation and department names).
DEPARTMENT_REFERENCE_DIR = PROJECT_DIR.parent / "references" / "staffcentral_jp_category"

# ============================================================ Step 3: data engineering
LAUNCH_DAYS         = 30     # hires within this window = the launch team
HEADCOUNT_MILESTONES = (5, 10, 20)
MILESTONE_HOLD_DAYS = 30     # a seat milestone counts only if held at least this long
CHURN_GRACE_DAYS    = 30     # zero-headcount gaps longer than this are churn (shorter = backfill)
ACTIVE_FILL_DATE    = None   # date the extract puts in disengagement_date for active staff (None = today)
ACTIVE_STATUSES     = []     # Employment Status values that always mean "still active"

# Client accounts only (branching + propensity): never-client accounts and internal teams
NON_CLIENT_SHORTCODES = ["CSTREENGAGE", "CLOUDSTAFF"]
HUB_SHARE_EXCLUDE     = 0.5   # also exclude accounts where at least this share of rows are Category 'Hub'
BRANCH_MIN_HIRES      = 1     # a department counts as entered at its Nth hire (2 = ignore one-off hires)

# ============================================================ Step 4a: branching analysis
MIN_GROUP_N        = 20     # groups with fewer accounts are left out of tables and charts
TOP_N_DEPTS        = 12     # rows / columns in the heatmaps
MIN_TRANSITION_N   = 5
BRANCH_DAYS        = (180, 365, 730)
KM_SHOW            = 6
MIN_AT_RISK_BRANCH = 10
XMAX_BRANCH        = 1095
RELATED_MULTI_DEPT_ONLY = True
MIN_PAIR_N         = 10
LANDMARK_DAY       = 365
FOLLOW_DAYS        = 365
SENS_MIN_N         = 10

# ============================================================ Step 4b: propensity scorecards
PS_TRAIN_YEARS     = 5      # learn from clients that started in the last N years
PS_GROWTH_SEATS    = 5      # growth = reach and hold this many seats ...
PS_GROWTH_DAYS     = 365    # ... within this many days of the first hire
PS_BRANCH_DAYS     = 365    # new-department window
# Existing clients' department models: a department first staffed within this many days of the client's first hire is
# part of a staggered LAUNCH, not an added department, so it never counts as the outcome. Check of 2026-11-13: with 30 days,
# one-department clients 3-6 months old "added" a second department 18.8% of the time, 12.8% without these launch entries
# (as for 1-2 year clients); the model's AUC stayed 0.70. Set to 0 to count every entry (the earlier behaviour).
ORG_DEPT_LAUNCH_DAYS = 180
PS_SNAP_STEP       = 90     # existing clients: one snapshot every N days of account age
PS_MIN_SNAP_AGE    = 90
PS_MIN_LEVEL_N     = 15     # category levels with fewer training rows are pooled together
PS_C               = 0.5    # logistic regularisation (smaller = more cautious)
PS_TOP_START_DEPTS = 12
PS_BANDS           = ["Low", "Medium", "High"]
PS_RANDOM_STATE    = 7
PS_MIN_PROFILE_CLIENTS = 1
PS_MILESTONES      = [(10, 730), (20, 1095)]   # extra new-client milestones: (seats, within days) on top of 5 in 365
PS_MIN_POSITIVES   = 15     # a milestone model is only fitted if at least this many training clients reached it
PS_SEAT_GROWTH_DAYS = 365   # existing clients: the seat window (milestones below, and "more seats" in the workbook)
# Existing clients, seat milestones: each client is scored for its NEXT milestone only (1-4 seats -> 5+, 5-9 -> 10+,
# 10-19 -> 20+): the chance of reaching it and holding it for MILESTONE_HOLD_DAYS, within PS_SEAT_GROWTH_DAYS. Clients
# already at the largest milestone are out of scope. A milestone is modelled only if at least PS_MIN_POSITIVES training
# snapshots reached it.
ORG_SEAT_MILESTONES = [5, 10, 20]
PS_LIFT_MIN_SHARE  = 0.03   # likely_next_dept_by_lift only lists departments with at least this share
PS_SEAT_BANDS      = [0, 2, 4, 9, 29, float("inf")]
PS_SEAT_LABELS     = ["1-2 seats", "3-4 seats", "5-9 seats", "10-29 seats", "30+ seats"]

# Industry groups (dashboard taxonomy, mappings.py) with fewer client accounts than this are modelled at
# sector level instead (the dashboard's own advice for small groups). The extract still shows the group.
INDUSTRY_SECTOR_FALLBACK_N = 30

# ============================================================ Step 5b: extract for the Account Priority Dashboard
# A separate output from the workbook: one row per active MyStaff client keyed like the dashboard
# (account_id = "MS-" + shortcode), plus a profile lookup for New Logo prospects.
MODEL_VERSION        = "propensity-v1.2 (dashboard 18-group taxonomy; second-department bands; 180-day department launch)"
TEST_ACCOUNT_PATTERN = r"^test|\bqa\b"     # MyStaff client names treated as test / QA accounts (dashboard rule)
EXTRACT_SOURCE_DATES = {                   # extract date of each raw file (step 1: recorded, not yet aligned)
    "engagement": "2026-10-07", "mystaff": "2026-10-05", "staffcentral": "2026-09-14"}

# The extract (xlsx + 2 CSVs) is also copied here, so the Account Priority Dashboard reads every input from its own
# local data folder (outside the repo). None = don't copy. Override with the MIA_DASHBOARD_DIR environment variable.
# Current seats when scoring clients TODAY (which seat milestone applies, and the "seats now" model input).
# "dashboard":  the Account Priority Dashboard's cs_staff_current (MyStaff Total Staff), read from the newest
#               DASHBOARD_DATA_GLOB file in DASHBOARD_FEED_DIR; clients it doesn't list fall back to the engagement list.
# "engagement": the engagement list only.
# The history the models learn from always comes from the engagement list (it has every start and end date).
CURRENT_SEATS_SOURCE = "dashboard"
DASHBOARD_DATA_GLOB  = "priority_company_info_combined*.xlsx"

DASHBOARD_FEED_DIR = Path(os.environ.get(
    "MIA_DASHBOARD_DIR",
    r"C:\Users\Alfonso(FonsoP)Panli\Desktop\Projects\Marketing Intelligence Priority\Data"))
