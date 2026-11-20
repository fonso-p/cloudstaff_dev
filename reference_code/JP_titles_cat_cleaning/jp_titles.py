"""
JP Title / JP Category cleanup and backfill for Staff Central role data.

What it does
------------
Staff Central role fields are messy in two ways:

1. **Noisy titles.** The same role appears as "Senior Tax Accountant Level 2",
   "Tax Accountant II", "Jr. Tax Accountant", plus a few typos
   ("Speclialist", "Fullstack"). `strip_title` reduces these to one
   *title base* ("Tax Accountant") so counts aren't split across seniority levels.
2. **Missing JP fields.** Many staff have a `Designation (All)` but a blank
   `JP Title (All)` and/or `JP Category (All)`. `backfill_jp` fills those
   blanks from other rows where the same designation / title *is* mapped.

When to use it
--------------
- Any analysis that counts, ranks or groups staff/roles by JP Title or JP
  Category (top roles, role mix by vertical/industry/client, hiring trends).
- Any time you join a Staff Central "Staff Report with Details" export onto
  engagements or staff lists and find a large share of blank JP fields.
- When you need one consistent role label across levels (e.g. comparing
  "Accountant" demand regardless of Level 1/2/3).

When NOT to use it
------------------
- When seniority matters (salary bands, level progression): `strip_title`
  removes Senior/Junior/Level/roman numerals on purpose. Use the original
  `JP Title (All)` instead.
- As a source of truth for a single person's role. Backfilled values are
  inferred from other rows; check `title_source` / `category_source` before
  quoting an individual record.

Where it's been used
--------------------
- `Adhoc/Top roles APAC/top_roles_APAC.ipynb` (top JP titles/categories by
  vertical for roles engaged in the last 12 months).

Input expected
--------------
A DataFrame with three Staff Central columns (names are configurable):

    Designation (All)   e.g. "Paraplanner Level 2"
    JP Title (All)      e.g. "Paraplanner Level 2"   (may be blank)
    JP Category (All)   e.g. "Accounting"            (may be blank)

How the backfill decides (strict cascade)
-----------------------------------------
The most specific evidence wins. Lookups are built only from rows that were
originally populated. If a key points to more than one value it is
"ambiguous" and the row is left blank rather than guessed.

JP Title Base, in order:
    manual            your `manual_title` overrides (by lowercase designation)
    designation_exact same designation text -> title base
    designation_base  same designation after stripping levels -> title base
    designation_is_jp_title  stripped designation is itself a known title base

JP Category, in order:
    manual            your `manual_cat` overrides (by lowercase title base)
    jp_title_exact    same original JP Title -> category
    jp_title_base     same (filled) title base -> category
    designation_exact same designation text -> category

Usage
-----
    # make the repo's shared/ folder importable (see shared/README.md)
    import sys
    from pathlib import Path
    REPO_ROOT = next(p for p in [Path.cwd().resolve(), *Path.cwd().resolve().parents] if (p / "shared").is_dir())
    sys.path.insert(0, str(REPO_ROOT / "shared"))

    from jp_titles import backfill_jp, strip_title

    filled, reports = backfill_jp(df)                 # df is not modified
    filled["JP Title Base (Filled)"].value_counts()
    filled["JP Category (Filled)"].value_counts()

    # review what was filled and what's still open
    reports["title_source_counts"]       # how each title was obtained
    reports["category_source_counts"]    # how each category was obtained
    reports["title_conflicts"]           # designations mapping to several title bases
    reports["category_conflicts"]        # title bases split across categories
    reports["unfilled_rows"]             # rows left blank: fix these by hand

    # fix recurring gaps with overrides, then re-run
    filled, reports = backfill_jp(
        df,
        manual_title={"sr accountant": "Accountant"},   # lowercase designation -> title base
        manual_cat={"accountant": "Accounting"},        # lowercase title base -> category
    )

Output columns added
--------------------
    JP Title Base           stripped original JP Title (no backfill)
    JP Title Base (Filled)  title base after the cascade
    JP Category (Filled)    category after the cascade
    title_source            "original", the step that filled it,
    category_source         "blocked: <step> ambiguous|low_support", or "no_match"

Notes
-----
- Rows blocked as ambiguous are the main source of remaining blanks. Look at
  `reports["title_conflicts"]` / `["category_conflicts"]` and add overrides
  rather than lowering standards.
- `min_support=2` (or more) ignores keys seen only once, if one-off rows are
  causing bad fills.
- To add a new typo fix, add it to `TYPO_FIXES`; it applies everywhere.
"""

import re

import numpy as np
import pandas as pd

__all__ = ["TYPO_FIXES", "fix_typos", "strip_seniority", "strip_title", "backfill_jp"]

# Typos and inconsistent spellings seen in Staff Central titles (regex -> replacement)
TYPO_FIXES = {
    r"\bSpeclialist\b": "Specialist",
    r"\bSpecialst\b": "Specialist",
    r"\bFullstack\b": "Full Stack",
    r"â€“": "–",
    r"â€”": "—",
}


def fix_typos(s: pd.Series) -> pd.Series:
    """Apply `TYPO_FIXES` to a text Series (returns pandas string dtype)."""
    s = s.astype("string")
    for pattern, repl in TYPO_FIXES.items():
        s = s.str.replace(pattern, repl, regex=True)
    return s


def strip_seniority(s: pd.Series) -> pd.Series:
    """Drop level / seniority / numbering noise from a title (no typo fixes).

    "Senior Tax Accountant Level 2" -> "Tax Accountant"
    "Engineer II" -> "Engineer";  "Coordinator2" -> "Coordinator";  "3D Artist" unchanged.
    Empty results become <NA>.
    """
    return (s.astype("string")
            # "Level 1", "Level2", "Level 10" anywhere
            .str.replace(r"\bLevel\s*\d+\b", "", regex=True, flags=re.I)
            # Seniority words
            .str.replace(r"\b(Senior|Sr\.?|Junior|Jr\.?)(?=\s|$)", "", regex=True, flags=re.I)
            # Trailing roman numerals: "Engineer II", "Associate Software Engineer I"
            .str.replace(r"\s+(I{1,3}|IV)$", "", regex=True)
            # Digits glued to a word: "Coordinator2" -> "Coordinator" (keeps "3D")
            .str.replace(r"(?<=[A-Za-z])\d+\b", "", regex=True)
            # Tidy up: collapse spaces, drop leftover leading/trailing punctuation
            .str.replace(r"\s+", " ", regex=True)
            .str.strip(" ,-–—|")
            .str.strip()
            .replace("", pd.NA))


def strip_title(s: pd.Series) -> pd.Series:
    """Fix typos, then strip seniority: raw title -> title base."""
    return strip_seniority(fix_typos(s))


def backfill_jp(
    df: pd.DataFrame,
    des_col: str = "Designation (All)",
    title_col: str = "JP Title (All)",
    cat_col: str = "JP Category (All)",
    min_support: int = 1,
    manual_title: dict | None = None,
    manual_cat: dict | None = None,
    use_designation_as_title: bool = True,
    keep_source_cols: bool = True,
):
    """
    Strictly backfill a stripped JP Title and JP Category.

    Rule: the most specific evidence wins; if that evidence is ambiguous
    (one key -> several values), the row is left blank rather than guessed.
    Lookups are built only from originally populated rows. See the module
    docstring for the full cascade.

    Parameters
    ----------
    df : source dataframe (not modified)
    des_col, title_col, cat_col : names of the Designation / JP Title / JP Category columns
    min_support : a key must be seen at least this many times to be trusted
    manual_title : {lowercase designation: title base} overrides, applied first
    manual_cat : {lowercase title base: category} overrides, applied first
    use_designation_as_title : allow the final step where a stripped
        Designation that is itself a known JP Title Base is used as the title
    keep_source_cols : keep 'title_source' / 'category_source' audit columns

    Returns
    -------
    out : dataframe with 'JP Title Base', 'JP Title Base (Filled)',
          'JP Category (Filled)' (+ source columns)
    reports : dict of DataFrames/Series for review
    """
    manual_title = manual_title or {}
    manual_cat = manual_cat or {}

    # ---------- helpers ----------
    def clean(s):
        return (fix_typos(s)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .replace("", pd.NA))

    def build_lookup(keys, values, support=min_support):
        tmp = pd.DataFrame({"k": keys, "v": values}).dropna()
        g = tmp.groupby("k")["v"].agg(n_values="nunique", value="first", support="size")
        g["status"] = np.select(
            [g["n_values"] > 1, g["support"] < support],
            ["ambiguous", "low_support"],
            default="unique",
        )
        return g

    def manual_lookup(mapping):
        return build_lookup(
            pd.Series([k.lower() for k in mapping.keys()], dtype="string"),
            pd.Series(list(mapping.values()), dtype="string"),
            1,
        )

    def cascade(start, steps):
        filled = start.copy()
        src = pd.Series(pd.NA, index=start.index, dtype="object")
        src[filled.notna()] = "original"
        open_ = filled.isna()

        for label, keys, lookup in steps:
            k = keys.where(open_)
            status = k.map(lookup["status"])
            value = k.map(lookup["value"])

            hit = open_ & status.eq("unique")
            filled[hit] = value[hit]
            src[hit] = label

            blocked = open_ & status.isin(["ambiguous", "low_support"])
            src[blocked] = "blocked: " + label + " " + status[blocked]

            open_ = open_ & ~hit & ~blocked

        src[open_] = "no_match"
        return filled, src

    def conflicts(keys, values):
        return (pd.DataFrame({"key": keys, "value": values})
                  .dropna()
                  .groupby("key")["value"]
                  .agg(lambda s: s.value_counts().to_dict())
                  .loc[lambda x: x.map(len) > 1])

    # ---------- prepare ----------
    missing = [c for c in (des_col, title_col, cat_col) if c not in df.columns]
    if missing:
        raise KeyError(f"Missing columns: {missing}")

    out = df.copy()
    des = clean(out[des_col])
    title = clean(out[title_col])
    cat = clean(out[cat_col])

    out["JP Title Base"] = strip_seniority(title)

    des_key = des.str.lower()
    des_base_key = strip_seniority(des).str.lower()
    title_key = title.str.lower()
    base_key = out["JP Title Base"].str.lower()

    # ---------- JP Title Base ----------
    title_steps = []
    if manual_title:
        title_steps.append(("manual", des_key, manual_lookup(manual_title)))
    title_steps += [
        ("designation_exact", des_key, build_lookup(des_key, out["JP Title Base"])),
        ("designation_base", des_base_key, build_lookup(des_base_key, out["JP Title Base"])),
    ]
    if use_designation_as_title:
        title_steps.append(
            ("designation_is_jp_title", des_base_key,
             build_lookup(base_key, out["JP Title Base"], 1))
        )

    out["JP Title Base (Filled)"], out["title_source"] = cascade(out["JP Title Base"], title_steps)

    # ---------- JP Category ----------
    filled_base_key = out["JP Title Base (Filled)"].str.lower()

    cat_steps = []
    if manual_cat:
        cat_steps.append(("manual", filled_base_key, manual_lookup(manual_cat)))
    cat_steps += [
        ("jp_title_exact", title_key, build_lookup(title_key, cat)),
        ("jp_title_base", filled_base_key, build_lookup(base_key, cat)),
        ("designation_exact", des_key, build_lookup(des_key, cat)),
    ]

    out["JP Category (Filled)"], out["category_source"] = cascade(cat, cat_steps)

    # ---------- reports ----------
    reports = {
        "title_source_counts": out["title_source"].value_counts(dropna=False),
        "category_source_counts": out["category_source"].value_counts(dropna=False),
        "title_conflicts": conflicts(des, out["JP Title Base"]),
        "category_conflicts": conflicts(out["JP Title Base"], cat),
        "unfilled_rows": out.loc[
            out["JP Category (Filled)"].isna() | out["JP Title Base (Filled)"].isna(),
            [des_col, title_col, "JP Title Base (Filled)", "JP Category (Filled)",
             "title_source", "category_source"],
        ],
    }

    if not keep_source_cols:
        out = out.drop(columns=["title_source", "category_source"])

    return out, reports
