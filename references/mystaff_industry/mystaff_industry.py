"""Cloudstaff industry taxonomy: 18 industry groups under 6 sectors.

The single source of truth is ``industry_mapping.csv`` (next to this file); it is described in ``README.md``.
To change the bucketing, edit the CSV; every project that imports this module picks the change up.

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path("<repo root>") / "references" / "mystaff_industry"))
    from mystaff_industry import classify, classify_frame, INDUSTRY_MAP, INDUSTRY_SECTOR

    classify("Computer Software")                      # ('Technology', 'Technology & Media', 'Industry Hubspot')
    classify("-", rollup="Accounting Services")        # ('Accounting', 'Financial & Professional Services', 'Industry Roll Up')
    df = classify_frame(df, hubspot_col="Industry Hubspot", rollup_col="Industry Roll Up")

Standard library only (pandas is needed only for classify_frame).
The constants have the same names and shapes as ``Client Propensity/mi_pipeline/mappings.py`` and the
dashboard notebook's §0b, so either can switch to importing them.
"""
from __future__ import annotations

import csv
from pathlib import Path

MAPPING_FILE = Path(__file__).resolve().parent / "industry_mapping.csv"

HUBSPOT = "Industry Hubspot"   # HubSpot's industry list (HubSpot `Industry`, MyStaff `Industry Hubspot`)
ROLLUP = "Industry Roll Up"    # Cloudstaff's own roll-up (MyStaff only): fallback


def _load(path: Path = MAPPING_FILE) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    for r in rows:
        if r["source_field"] not in (HUBSPOT, ROLLUP):
            raise ValueError(f"{path.name}: unknown source_field {r['source_field']!r}")
        if r["status"] not in ("mapped", "unclassified", "placeholder"):
            raise ValueError(f"{path.name}: unknown status {r['status']!r} for {r['raw_value']!r}")
        if (r["status"] == "mapped") != bool(r["industry_group"]):
            raise ValueError(f"{path.name}: {r['raw_value']!r} must have a group if and only if it is 'mapped'")
    return rows


ROWS = _load()

INDUSTRY_GROUPS: dict[str, list[str]] = {}   # group -> HubSpot industry values, in file order
INDUSTRY_SECTOR: dict[str, str] = {}         # group -> sector
ROLLUP_MAP: dict[str, str] = {}              # Industry Roll Up value -> group (fallback only)
UNCLASSIFIED_INDUSTRY: set[str] = set()      # HubSpot values that mean "unknown"
PLACEHOLDER_ROLLUP: set[str] = set()         # Roll Up values that carry no industry
BORDERLINE: dict[str, str] = {}              # HubSpot value -> alternative group that was considered

for r in ROWS:
    raw, grp = r["raw_value"], r["industry_group"]
    if r["status"] == "mapped":
        if INDUSTRY_SECTOR.setdefault(grp, r["industry_sector"]) != r["industry_sector"]:
            raise ValueError(f"{MAPPING_FILE.name}: group {grp!r} is listed under two sectors")
        if r["source_field"] == HUBSPOT:
            if any(raw in v for v in INDUSTRY_GROUPS.values()):
                raise ValueError(f"{MAPPING_FILE.name}: HubSpot value {raw!r} is in two groups")
            INDUSTRY_GROUPS.setdefault(grp, []).append(raw)
            if r["borderline_alternative"]:
                BORDERLINE[raw] = r["borderline_alternative"]
        else:
            if raw in ROLLUP_MAP:
                raise ValueError(f"{MAPPING_FILE.name}: Roll Up value {raw!r} is listed twice")
            ROLLUP_MAP[raw] = grp
    elif r["source_field"] == HUBSPOT:
        UNCLASSIFIED_INDUSTRY.add(raw)
    else:
        PLACEHOLDER_ROLLUP.add(raw)

INDUSTRY_MAP: dict[str, str] = {raw: g for g, raws in INDUSTRY_GROUPS.items() for raw in raws}   # HubSpot value -> group
GROUPS: list[str] = list(INDUSTRY_GROUPS)
SECTORS: list[str] = list(dict.fromkeys(INDUSTRY_SECTOR.values()))

if set(ROLLUP_MAP.values()) - set(INDUSTRY_GROUPS):
    raise ValueError(f"{MAPPING_FILE.name}: Roll Up values point to groups with no HubSpot values: "
                     f"{set(ROLLUP_MAP.values()) - set(INDUSTRY_GROUPS)}")


def _clean(v) -> str:
    if v is None or v != v:   # None or NaN
        return ""
    return str(v).replace("&amp;", "&").strip()


def classify(hubspot=None, rollup=None) -> tuple[str | None, str | None, str | None]:
    """(industry_group, industry_sector, source_field) for one record.

    HubSpot value first. If it is blank, unclassified or not in the taxonomy, the Roll Up value is used. Placeholder
    roll-ups and unknown values give (None, None, None)."""
    h = _clean(hubspot)
    if h in INDUSTRY_MAP:
        g = INDUSTRY_MAP[h]
        return g, INDUSTRY_SECTOR[g], HUBSPOT
    r = _clean(rollup)
    if r in ROLLUP_MAP:
        g = ROLLUP_MAP[r]
        return g, INDUSTRY_SECTOR[g], ROLLUP
    return None, None, None


def unrecognised(values, source_field: str = HUBSPOT) -> set[str]:
    """Values that aren't in the mapping file at all (new values to add to the CSV)."""
    known = {r["raw_value"] for r in ROWS if r["source_field"] == source_field}
    return {c for c in map(_clean, values) if c and c not in known}


def classify_frame(df, hubspot_col: str = HUBSPOT, rollup_col: str | None = ROLLUP, prefix: str = "industry"):
    """Adds <prefix>_group, <prefix>_sector and <prefix>_source columns to a pandas DataFrame (returns a copy).
    Pass rollup_col=None for sources without a roll-up (e.g. the HubSpot company report)."""
    out = df.copy()
    rollups = out[rollup_col] if rollup_col else [None] * len(out)
    res = [classify(h, r) for h, r in zip(out[hubspot_col], rollups)]
    out[f"{prefix}_group"] = [x[0] for x in res]
    out[f"{prefix}_sector"] = [x[1] for x in res]
    out[f"{prefix}_source"] = [x[2] for x in res]
    return out
