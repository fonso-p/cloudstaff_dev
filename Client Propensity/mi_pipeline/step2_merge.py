"""Step 2: merge the formatted tables.
    - StaffCentral department / role group onto each engagement (joined on CSID)
    - client industry groups onto MyStaff
"""
import re

import numpy as np
import pandas as pd

import config
from mi_pipeline import mappings
from mi_pipeline.step1_format import clean_id, clean_text


# ---------------------------------------------------------------- departments
def _norm_designation(t):
    """'Senior Customer Service Representative Level 2' -> 'customer service representative';
    'Associate Accountant OJT' -> 'accountant'. Removes levels, seniority and training words (config.DESIGNATION_DROP_WORDS)."""
    if pd.isna(t):
        return None
    t = str(t).lower()
    t = re.sub(r"\blevel\s*\d+\b|\b(i{1,3}|iv|v)\b", "", t)
    t = re.sub(r"\b(" + "|".join(config.DESIGNATION_DROP_WORDS) + r")\b", "", t)
    t = re.sub(r"[^a-z&/ ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return None if not t or t in config.GENERIC_DESIGNATIONS else t

def category_map(staff, key, min_staff, min_share):
    """key value -> the JP Category most staff with that key have, learned from staff whose category is known.
    Kept only if at least min_staff staff have the key and at least min_share of them share that category.
    Returns a table: key, category, share, staff."""
    known = staff[staff["jp_category"].notna() & staff[key].notna()]
    counts = known.groupby([key, "jp_category"]).size().rename("n").reset_index()
    counts["staff"] = counts.groupby(key)["n"].transform("sum")
    top = counts.sort_values(["n", "jp_category"], ascending=[False, True]).drop_duplicates(key)
    top = top.assign(share=(top["n"] / top["staff"]).round(3)).rename(columns={"jp_category": "category"})
    top["used"] = (top["staff"] >= min_staff) & (top["share"] >= min_share)
    return top[[key, "category", "share", "staff", "used"]].sort_values("staff", ascending=False).reset_index(drop=True)

def staff_role_groups(staff, log=print):
    """role_group = StaffCentral JP Category. A blank category is imputed, in order, from JP Title, Designation and
    the deprecated Department (config.JP_IMPUTE_STEPS); each imputed row is flagged. Still blank = Unknown: role_group
    stays blank, so these staff are left out of the department history.
    Returns (staff, maps): maps holds each step's lookup table, for the workbook."""
    staff = staff.copy()
    staff["jp_category"] = staff["jp_category"].replace(config.JP_CATEGORY_MAP).astype("string")
    staff["designation_key"] = staff["designation"].map(_norm_designation).astype("string")
    category = staff["jp_category"].copy()
    source = pd.Series(np.where(category.notna(), "JP Category", pd.NA), index=staff.index, dtype="string")
    maps, filled = {}, {}
    for label, key, min_staff, min_share in config.JP_IMPUTE_STEPS:
        maps[label] = category_map(staff, key, min_staff, min_share)
        lookup = maps[label][maps[label]["used"]].set_index(key)["category"]
        guess = staff[key].map(lookup)
        fill = category.isna() & guess.notna()
        category = category.where(~fill, guess)
        source = source.where(~fill, f"{label} (imputed)")
        filled[label] = int(fill.sum())
    staff["role_group"] = category.replace(config.ROLE_GROUP_MAP).astype("string")
    staff["role_group_source"] = source.fillna("none (Unknown)")
    staff["role_group_imputed"] = source.str.endswith("(imputed)").fillna(False).astype(int)
    log(f"[2 merge] department = JP Category: {int(staff['jp_category'].notna().sum())} of {len(staff)} staff | imputed from "
        + ", ".join(f"{k} {v}" for k, v in filled.items())
        + f" | Unknown: {int(staff['role_group'].isna().sum())}")
    return staff, maps

def join_departments(engagement, staff, log=print):
    """Adds department, jp_category, role_group, role_group_source, role_group_imputed, dept_certain to every engagement.
    dept_certain = 1 where StaffCentral's current Engagement ID is this engagement."""
    df = engagement.copy()
    key = clean_id(df["CSID"])
    look = staff.set_index("CSID")
    assert key.dtype == look.index.dtype, f"CSID types differ: {key.dtype} vs {look.index.dtype}"
    for c in ["department", "jp_category", "role_group", "role_group_source", "role_group_imputed"]:
        df[c] = key.map(look[c])
    df["dept_certain"] = (key.map(look["Engagement ID"]) == df["Engagement ID"]).fillna(False).astype(int)
    assert len(df) == len(engagement)
    log(f"[2 merge] engagements with a department (JP Category): {df['role_group'].notna().mean():.1%} "
        f"(imputed {df['role_group_imputed'].eq(1).mean():.1%}) | "
        f"department certain (Engagement ID matches): {df['dept_certain'].mean():.1%}")
    return df


# ---------------------------------------------------------------- industry and region (dashboard rules)
def add_industry_groups(mystaff, log=print):
    """Adds industry_group (18 groups), industry_sector (6), industry_source and industry_raw, using the
    Account Priority Dashboard's rule: Industry Hubspot first, Industry Roll Up as fallback."""
    df = mystaff.copy()
    hs, ru = clean_text(df["Industry Hubspot"]), clean_text(df["Industry Roll Up"])
    ind_h = hs.map(mappings.INDUSTRY_MAP)
    ind_r = ru.where(~ru.isin(mappings.PLACEHOLDER_ROLLUP)).map(mappings.ROLLUP_MAP)
    df["industry_group"]  = ind_h.fillna(ind_r).astype("string")
    df["industry_sector"] = df["industry_group"].map(mappings.INDUSTRY_SECTOR).astype("string")
    df["industry_source"] = pd.Series(np.select([ind_h.notna(), ind_r.notna()],
                                                ["MyStaff Industry Hubspot", "MyStaff Industry Roll Up"], ""),
                                      index=df.index).replace("", pd.NA).astype("string")
    df["industry_raw"] = hs.where(hs.ne("-"), ru)
    src = df["industry_source"].value_counts()
    log(f"[2 merge] industry (18 groups): {int(src.get('MyStaff Industry Hubspot', 0))} from Industry Hubspot, "
        f"{int(src.get('MyStaff Industry Roll Up', 0))} from Roll Up, {int(df['industry_group'].isna().sum())} blank")
    return df

def add_region(mystaff, log=print):
    """Adds region (AU-NSW, US, UK, NZ, CA, ... or Other) from the office address, and the country level used by the models."""
    df = mystaff.copy()
    df["region"]  = pd.Series([mappings.region_code(c, s) for c, s in zip(df["Office Address Country"], df["Office Address State"])],
                              index=df.index, dtype="string")
    df["country"] = df["region"].map(mappings.region_to_country).astype(str)
    log(f"[2 merge] region: {int(df['region'].notna().sum())} of {len(df)} accounts | country: {df['country'].value_counts().to_dict()}")
    return df


def run(formatted, log=print):
    staff, dept_maps = staff_role_groups(formatted["staff"], log)
    engagement = join_departments(formatted["engagement"], staff, log)
    mystaff = add_region(add_industry_groups(formatted["mystaff"], log), log)
    return {"engagement": engagement, "mystaff": mystaff, "staff": staff, "dept_maps": dept_maps}
