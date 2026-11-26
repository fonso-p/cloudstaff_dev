"""Small helpers shared by the grading steps."""

import math
import re

import pandas as pd

from cloudstaff_dev.common.industry import INDUSTRY_GROUPS

from .rules import BAND_EDGES


# ---------------------------------------------------------------- helpers
def domain(u):
    if not isinstance(u, str) or not u.strip():
        return ""
    u = re.sub(r"^[a-z]+://", "", u.strip().lower())
    return re.sub(r"^www\.", "", u.split("/")[0].split("?")[0].split(":")[0])


_norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower().replace("&", "and"))   # 'nonprofit' = 'Non-Profit', '&' = 'and'
_INDUSTRY = {_norm(v): g for g, vs in INDUSTRY_GROUPS.items() for v in vs}


def industry_group(apollo_industry):
    """Apollo uses LinkedIn's lower-case names ('hospital & health care'); HubSpot's are 'Hospital & Health Care'."""
    return _INDUSTRY.get(_norm(apollo_industry)) if isinstance(apollo_industry, str) else None


def band(n):
    return None if pd.isna(n) or n <= 0 else next(lbl for hi, lbl in BAND_EDGES if n <= hi)


def blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or v == ""


def jsonable(v):
    if blank(v) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if hasattr(v, "item"):
        return v.item()
    return v
