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
    "seat_churn": ("Seats Churn (OPERATIONAL) CALC 10052026 - Copy.xlsx", "Engagement List (Raw)",
                   ["Shortcode", "Engagement ID", "UserName", "Username", "CSID", "Engagement Date",
                    "Disengagement Date", "UBER Ticket", "UBER Vol/Inv", "UBER Type Reason", "UBER Main Reason",
                    "UBER Notes", "Manual Notes"]),
    "mystaff": ("CONFIDENTIAL Mystaff 10052026.xlsx", "MyStaff",
                ["Shortcode", "Client", "Active", "CRM Company ID", "Region", "Industry Roll Up", "Industry Hubspot",
                 "Custom_Division (Hubspot)", "Office Address State", "Office Address Country",
                 "Internal (Yes / No)"]),
    "staffcentral": ("StaffCentral 09142026.xlsx", 0,
                     ["CSID", "Department (All)", "JP Category (All)", "Designation (All)", "Engagement ID",
                      "Engagement Status (All)", "Engagement Date"]),
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
EXEC_SERVICES  = "Executive Services"   # catch-all department, split by JP Category
EXEC_PREFIX    = "Exec Services - "
ROLE_GROUP_MAP = {}                     # optional merges after the split, e.g. {"Legal and Compliance": "Legal"}

# Exec Services staff with no JP Category: infer it from Designation when staff with the same
# (normalised) designation and a known category mostly share one category. Tested on held-out
# staff: ~90% correct, fills ~44% of the blanks. Inferred values are flagged in role_group_source.
FILL_EXEC_FROM_DESIGNATION = True
DESIGNATION_MIN_STAFF      = 5      # designation needs at least this many staff with a known category
DESIGNATION_MIN_PURITY     = 0.6    # ... and this share of them in the same category
GENERIC_DESIGNATIONS = {"executive services specialist", "executive service specialist", "for executive services",
                        "team leader", "ess"}   # say nothing about the work: never used to infer

# ============================================================ Step 3: data engineering
EXIT_STATUSES       = ["Resigned", "AWOL", "Dismissed"]   # attrition exits
LAUNCH_DAYS         = 30     # hires within this window = the launch team
HEADCOUNT_MILESTONES = (5, 10, 20)
MILESTONE_HOLD_DAYS = 30     # a seat milestone counts only if held at least this long
CHURN_GRACE_DAYS    = 30     # zero-headcount gaps longer than this are churn (shorter = backfill)
ACTIVE_FILL_DATE    = None   # date the extract puts in disengagement_date for active staff (None = today)
ACTIVE_STATUSES     = []     # Employment Status values that always mean "still active"
ATTR_WINDOWS        = (60, 120, 180, 365)   # attrition / exit-reason windows (days from start)

# Exit-reason columns from the seat churn join, and the flags built from them
VOL_COL  = "UBER Vol/Inv_seat_churn"
TYPE_COL = "UBER Type Reason_seat_churn"
TYPE_FLAGS = {"Customer Initiated": "customer_initiated_exit",
              "Cloudstaff Initiated": "cloudstaff_initiated_exit",
              "Resignation": "resignation_exit"}

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
PS_SEAT_GROWTH_DAYS = 365   # existing clients: seat growth = more seats this many days later than today (net)
PS_LIFT_MIN_SHARE  = 0.03   # likely_next_dept_by_lift only lists departments with at least this share
PS_SEAT_BANDS      = [0, 2, 4, 9, 29, float("inf")]
PS_SEAT_LABELS     = ["1-2 seats", "3-4 seats", "5-9 seats", "10-29 seats", "30+ seats"]

# Industry groups (dashboard taxonomy, mappings.py) with fewer client accounts than this are modelled at
# sector level instead (the dashboard's own advice for small groups). The extract still shows the group.
INDUSTRY_SECTOR_FALLBACK_N = 30

# ============================================================ Step 5b: extract for the Account Priority Dashboard
# A separate output from the workbook: one row per active MyStaff client keyed like the dashboard
# (account_id = "MS-" + shortcode), plus a profile lookup for New Logo prospects.
MODEL_VERSION        = "propensity-v1 (dashboard 18-group taxonomy)"
TEST_ACCOUNT_PATTERN = r"^test|\bqa\b"     # MyStaff client names treated as test / QA accounts (dashboard rule)
EXTRACT_SOURCE_DATES = {                   # extract date of each raw file (step 1: recorded, not yet aligned)
    "engagement": "2026-10-07", "seat_churn": "2026-10-05", "mystaff": "2026-10-05", "staffcentral": "2026-09-14"}

# The extract (xlsx + 2 CSVs) is also copied here, so the Account Priority Dashboard reads every input from its own
# local data folder (outside the repo). None = don't copy. Override with the MIA_DASHBOARD_DIR environment variable.
DASHBOARD_FEED_DIR = Path(os.environ.get(
    "MIA_DASHBOARD_DIR",
    r"C:\Users\Alfonso(FonsoP)Panli\Desktop\Projects\Marketing Intelligence Priority\Data"))
