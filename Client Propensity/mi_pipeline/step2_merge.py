"""Step 2: merge the formatted tables.
    - seat churn exit reasons onto each engagement
    - StaffCentral department / role group onto each engagement (joined on CSID)
    - client industry groups onto MyStaff
"""
import re

import numpy as np
import pandas as pd

import config
from mi_pipeline import mappings
from mi_pipeline.step1_format import clean_id, clean_text


# ---------------------------------------------------------------- exit reasons
def merge_seat_churn(engagement, seat_churn, log=print):
    keys_left  = ["Shortcode", "Engagement ID", "Username", "engagement_date", "disengagement_date"]
    keys_right = [f"{k}_seat_churn" for k in ["Shortcode", "Engagement ID", "Username", "engagement_date",
                                              "disengagement_date"]]
    for l, r in zip(keys_left, keys_right):
        assert engagement[l].dtype == seat_churn[r].dtype, f"Type mismatch: {l} vs {r}"
    rows_before = len(engagement)
    out = engagement.merge(seat_churn, how="left", left_on=keys_left, right_on=keys_right)
    extra = len(out) - rows_before
    if extra:
        dupes = seat_churn[seat_churn.duplicated(subset=keys_right, keep=False)]
        log(f"[2 merge] WARNING: seat churn join added {extra} rows ({len(dupes)} duplicate key rows in seat churn)")
    return out


# ---------------------------------------------------------------- departments
def _norm_designation(t):
    """'Senior Customer Service Representative Level 2' -> 'customer service representative'."""
    if pd.isna(t):
        return None
    t = str(t).lower()
    t = re.sub(r"\blevel\s*\d+\b|\b(i{1,3}|iv|v)\b|\b(senior|sr\.?|junior|jr\.?|associate|lead)\b", "", t)
    t = re.sub(r"[^a-z&/ ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return None if not t or t in config.GENERIC_DESIGNATIONS else t

def designation_map(staff):
    """Normalised designation -> JP Category, learned from Executive Services staff whose category is known."""
    ex = staff[staff["department"].eq(config.EXEC_SERVICES).fillna(False)].copy()
    ex["dkey"] = ex["designation"].map(_norm_designation)
    known = ex[ex["jp_category"].notna() & ex["dkey"].notna()]
    stats = (known.groupby("dkey")["jp_category"]
                  .agg(top=lambda s: s.value_counts().index[0],
                       purity=lambda s: s.value_counts().iloc[0] / len(s),
                       n="size"))
    keep = (stats["n"] >= config.DESIGNATION_MIN_STAFF) & (stats["purity"] >= config.DESIGNATION_MIN_PURITY)
    return stats.loc[keep, "top"]

def staff_role_groups(staff, log=print):
    """role_group = department, with Executive Services split by JP Category (inferred from Designation if blank)."""
    staff = staff.copy()
    is_exec = staff["department"].eq(config.EXEC_SERVICES).fillna(False).astype(bool)
    category = staff["jp_category"]
    source = pd.Series(np.where(staff["department"].isna(), pd.NA,
                                np.where(~is_exec, "Department", np.where(category.notna(), "JP Category", "none"))),
                       index=staff.index, dtype="string")
    if config.FILL_EXEC_FROM_DESIGNATION:
        inferred = staff["designation"].map(_norm_designation).map(designation_map(staff))
        fill = is_exec & category.isna() & inferred.notna()
        category = category.where(~fill, inferred)
        source = source.where(~fill, "Designation (inferred)")
        log(f"[2 merge] Exec Services staff with no JP Category: {int((is_exec & staff['jp_category'].isna()).sum())}, "
            f"of which {int(fill.sum())} inferred from Designation")
    staff["role_group"] = staff["department"].where(~is_exec, config.EXEC_PREFIX + category.fillna("Other"))
    staff["role_group"] = staff["role_group"].replace(config.ROLE_GROUP_MAP)
    staff["role_group_source"] = source
    return staff

def join_departments(engagement, staff, log=print):
    """Adds department, jp_category, role_group, role_group_source, dept_certain to every engagement.
    dept_certain = 1 where StaffCentral's current Engagement ID is this engagement."""
    df = engagement.copy()
    key = clean_id(df["CSID"])
    look = staff.set_index("CSID")
    assert key.dtype == look.index.dtype, f"CSID types differ: {key.dtype} vs {look.index.dtype}"
    for c in ["department", "jp_category", "role_group", "role_group_source"]:
        df[c] = key.map(look[c])
    df["dept_certain"] = (key.map(look["Engagement ID"]) == df["Engagement ID"]).fillna(False).astype(int)
    assert len(df) == len(engagement)
    log(f"[2 merge] engagements with a role group: {df['role_group'].notna().mean():.1%} | "
        f"department certain (Engagement ID matches): {df['dept_certain'].mean():.1%} | "
        f"'Exec Services - Other' rows: {int(df['role_group'].eq(config.EXEC_PREFIX + 'Other').sum())}")
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
    staff = staff_role_groups(formatted["staff"], log)
    engagement = merge_seat_churn(formatted["engagement"], formatted["seat_churn"], log)
    engagement = join_departments(engagement, staff, log)
    mystaff = add_region(add_industry_groups(formatted["mystaff"], log), log)
    return {"engagement": engagement, "mystaff": mystaff, "staff": staff}
