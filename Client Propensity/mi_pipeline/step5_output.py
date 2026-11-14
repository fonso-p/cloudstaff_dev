"""Step 5: outputs.
    write_workbook  one Excel file with the line items, drivers, model checks and branching tables
    plot_*          charts for the notebook
The workbook lists client names and scores: it goes to config.OUTPUT_DIR (the local data folder, outside the repo)."""
import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
PCT_HINTS = ("p_", "pct_", "rate", "actual_", "avg_score")


def _how_to_read(res):
    p = res["propensity"]
    return pd.DataFrame({"Item": [
        "What this is", "New client scorecard", "Organic client list", "Rising (under 10 seats)",
        "Bands", "Growth score", "Seat milestones (new)", "Branching score (new)", "Branching score (existing)",
        "Seat growth (existing)", "vs peers",
        "Likely next department", "Model checks", "Read with care", "Department imputation", "Data as of"], "Explanation": [
        "Propensity line items for Sales / Marketing (new clients) and Account Managers (existing clients).",
        "One row per client profile seen in the last "
        f"{config.PS_TRAIN_YEARS} years (industry, country, starting department, launch size). Filter to the profile "
        "you are selling to and read the line_item column.",
        "One row per active client: chance of having more seats in 12 months, and of adding a department it has never had, "
        "each with vs peers and why, plus the most likely "
        "next department, and the main reasons.",
        "Active clients under 10 seats that score furthest above clients of their size: the less obvious expansion targets.",
        "Low / Medium / High = thirds of historical clients by score. The 'Model checks' sheet shows how often each band "
        "actually happened.",
        f"Reach and hold {config.PS_GROWTH_SEATS}+ seats within {config.PS_GROWTH_DAYS} days of the first hire "
        f"(clients that launched with 1-4 staff). Cross-validated AUC {p['growth_auc']:.2f}. growth_why = the profile traits "
        "raising it most.",
        "Also for new clients: reach and hold " + ", ".join(f"{k.split('reaches ')[1]} (AUC {a:.2f})" for k, (_, a) in p["milestone_checks"].items())
        + ". Columns p_reach_* / band_reach_*.",
        f"Add a department not in the launch team within the first {config.PS_BRANCH_DAYS} days. "
        f"AUC {p['branch_auc']:.2f} (weak: a rough guide only).",
        f"Add a department the client never had within the next {config.PS_BRANCH_DAYS} days. AUC {p['organic_auc']:.2f}.",
        f"More seats {config.PS_SEAT_GROWTH_DAYS} days from now than today (net growth, so backfills don't count). "
        f"AUC {p['seat_auc']:.2f}. Columns p_seat_growth_12m, seat_growth_band, seat_vs_peers, seat_why. Workbook only. "
        "The dashboard uses the seat MILESTONE instead: each client's next step (1-4 seats -> 5+, 5-9 -> 10+, 10-19 -> 20+; "
        f"20+ out of scope) and its chance within {config.PS_SEAT_GROWTH_DAYS} days: columns next_seat_milestone, "
        "p_next_seat_milestone, band_next_seat_milestone (AUC " + ", ".join(
            f"{n}+: {sm['auc']:.2f}" for n, sm in p["seat_milestones"].items()) + ").",
        "Client's score divided by the average for active clients of a similar size (1.5x = 50% more likely than peers).",
        "What clients with the same departments added next, as a share of the departments this client doesn't have yet, "
        "with lift in brackets (share / that department's usual share; 2.0x = twice as common as for clients overall). "
        "likely_next_dept_by_lift lists the departments that stand out most. Additions are spread across many departments, "
        "so treat it as a lead, not a forecast.",
        "AUC: 0.5 = coin flip, 0.7+ = useful. actual_rate = what really happened to past clients in each band.",
        "Patterns, not promises. Departments are StaffCentral JP Categories (current snapshot); a blank category is imputed from JP Title, "
        "Designation or the old Department where possible, otherwise Unknown (left out of department history).",
        "For each old Department, JP Title and Designation: the JP Category most of its staff "
        "have, that share, how many staff it rests on, and whether it is used to fill blanks. The summary rows count staff "
        "by where their department came from.",
        str(res["today"].date())]})


def _style(ws, df):
    for c in range(1, df.shape[1] + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        name = str(df.columns[c - 1])
        width = 90 if name in ("line_item", "Explanation") else min(max(len(name), *(len(str(v)) for v in df.iloc[:200, c - 1]), 8) + 2, 45)
        ws.column_dimensions[get_column_letter(c)].width = width
        if any(h in name for h in PCT_HINTS) and pd.api.types.is_numeric_dtype(df.iloc[:, c - 1]):
            for r in range(2, len(df) + 2):
                ws.cell(row=r, column=c).number_format = "0%"
    ws.freeze_panes = "B2" if df.shape[1] > 2 else "A2"
    ws.auto_filter.ref = ws.dimensions


def dept_imputation_table(merged):
    """How a blank JP Category is imputed: every lookup value per step (JP Title, Designation, old Department), the
    category most of its staff have, that share, and whether the step uses it. Plus how many staff each source supplied."""
    parts = []
    for step, m in merged["dept_maps"].items():
        parts.append(m.rename(columns={m.columns[0]: "value"}).assign(step=step))
    t = pd.concat(parts, ignore_index=True)[["step", "value", "category", "share", "staff", "used"]]
    # staff = staff with a known category behind the lookup (summary rows: staff whose department came from that source)
    t = t.rename(columns={"category": "imputed JP Category", "share": "share of its staff in that category",
                          "used": "used for imputation"})
    order = {"Department": 0, "JP Title": 1, "Designation": 2}
    t = t.sort_values(["step", "staff"], key=lambda s: s.map(order) if s.name == "step" else -s)
    src = merged["staff"]["role_group_source"].value_counts().rename_axis("value").rename("staff").reset_index()
    src = src.assign(step="Summary: staff by source")
    return pd.concat([src, t], ignore_index=True)[t.columns.tolist()]


def write_department_reference(res, folder=None):
    """Writes the department groupings to the repo's references folder (config.DEPARTMENT_REFERENCE_DIR), as
    documentation: the JP Category merges, every lookup used to impute a blank category, and where staff departments
    came from. Only names and counts, no staff or client data. Designations are listed only if at least
    DESIGNATION_MIN_LISTED staff share them, so one-off free-text designations stay out of git."""
    folder = folder or config.DEPARTMENT_REFERENCE_DIR
    if folder is None:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    merged = res["merged"]
    merges = pd.DataFrame([(k, v if v is not None else "(blank, then imputed)") for k, v in config.JP_CATEGORY_MAP.items()],
                          columns=["JP Category (as in StaffCentral)", "grouped into"])
    merges.to_csv(folder / "jp_category_merges.csv", index=False, encoding="utf-8")

    min_listed = 5
    rules = {label: (key, n, s) for label, key, n, s in config.JP_IMPUTE_STEPS}
    parts = []
    for order, (label, m) in enumerate(merged["dept_maps"].items(), start=1):
        t = m.rename(columns={m.columns[0]: "value"})
        if label == "Designation":
            t = t[t["staff"] >= min_listed]
        key, n, s = rules[label]
        rule = (f"at least {n} staff and {s:.0%} in one category" if s > 0
                else "the most common category, however few staff")
        parts.append(t.assign(step=f"{order}. {label}", rule=rule))
    look = pd.concat(parts, ignore_index=True)[["step", "value", "category", "share", "staff", "used", "rule"]]
    look = look.rename(columns={"value": "value (normalised for Designation)", "category": "most common JP Category",
                                "share": "share of its staff", "staff": "staff with a known category",
                                "used": "used to impute"})
    look.to_csv(folder / "jp_category_imputation_lookup.csv", index=False, encoding="utf-8")

    staff = merged["staff"]
    src = staff["role_group_source"].value_counts().rename("staff").rename_axis("department source").reset_index()
    src["share"] = (src["staff"] / len(staff)).round(3)
    depts = staff["role_group"].value_counts().rename("staff").rename_axis("department (JP Category, after imputation)").reset_index()
    src.to_csv(folder / "department_sources.csv", index=False, encoding="utf-8")
    depts.to_csv(folder / "departments.csv", index=False, encoding="utf-8")
    (folder / "run_info.txt").write_text(
        f"Generated by Client Propensity/run_pipeline.py on {res['today'].date()} from {config.RAW_FILES['staffcentral'][0]} "
        f"(extract {config.EXTRACT_SOURCE_DATES.get('staffcentral', '?')}).\n"
        f"Staff: {len(staff)} | with a department: {int(staff['role_group'].notna().sum())} | Unknown: {int(staff['role_group'].isna().sum())}\n",
        encoding="utf-8")
    return folder


def write_workbook(res, path=None):
    p, b = res["propensity"], res["branching"]
    path = path or config.OUTPUT_DIR / f"{res['today'].date()}_Client_Propensity_Scorecards.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    models = {"New client reaches 5 seats in 1y": (p["growth_check"], p["growth_auc"]),
              **p["milestone_checks"],
              "New client adds a department in year 1": (p["branch_check"], p["branch_auc"]),
              "Existing client adds a department in 12m": (p["organic_check"], p["organic_auc"]),
              "One-department client adds a second department in 12m (bands among one-department clients)":
                  (p["one_dept_check"], p["one_dept_auc"]),
              "Existing client has more seats in 12m": (p["seat_check"], p["seat_auc"]),
              **{f"Existing client, {sm['seats_from']}-{sm['seats_to']} seats, reaches {n}+ in 12m": (sm["check"], sm["auc"])
                 for n, sm in p["seat_milestones"].items()}}
    checks = pd.concat({k: c for k, (c, _) in models.items()}, names=["model", "band"]).reset_index()
    checks["AUC"] = checks["model"].map({k: a for k, (_, a) in models.items()}).round(2)
    sheets = {
        "How to read":              _how_to_read(res),
        "New client scorecard":     p["new_client_scorecard"],
        "Organic client list":      p["organic_client_list"],
        "Rising (under 10 seats)":  p["organic_rising"],
        "Drivers - new clients":    p["new_factors"],
        "Drivers - existing":       p["organic_factors"],
        "Drivers - seat growth":    p["seat_factors"],
        "Model checks":             checks,
        "Start to next dept":       b["start_dept_summary"].reset_index(),
        "Transitions":              b["transitions"],
        "Branching by industry":    b["branch_by_industry"].reset_index(),
        "Time to branch":           b["time_to_branch"].reset_index(),
        "Related departments":      b["related_pairs"],
        "Department imputation":    dept_imputation_table(res["merged"]),
    }
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df = df.copy()
            for c in df.columns:                      # Excel has no categorical / period types
                if isinstance(df[c].dtype, pd.CategoricalDtype) or str(df[c].dtype).startswith("period"):
                    df[c] = df[c].astype(str).replace("nan", "")
            df.to_excel(xw, sheet_name=name, index=False)
            _style(xw.sheets[name], df)
    return path


# ================================================================ charts (notebook)
INK, INK2, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]  # fixed order

def _heatmap(values, annot, title, cmap, norm, row_labels=None, cbar_label=""):
    import matplotlib.pyplot as plt
    v = values.to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(2.5 + 0.8 * v.shape[1], 1.5 + 0.42 * v.shape[0]))
    im = ax.imshow(np.ma.masked_invalid(v), cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(v.shape[1]), values.columns, rotation=40, ha="right", fontsize=8, color=INK2)
    ax.set_yticks(range(v.shape[0]), row_labels if row_labels is not None else values.index, fontsize=8, color=INK2)
    ax.set_xticks(np.arange(-.5, v.shape[1]), minor=True)
    ax.set_yticks(np.arange(-.5, v.shape[0]), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    for (i, j), x in np.ndenumerate(v):
        label = annot.iat[i, j]
        if np.isfinite(x) and label:
            r, g, b, _ = im.cmap(im.norm(x))
            ax.text(j, i, label, ha="center", va="center", fontsize=7,
                    color="white" if 0.299 * r + 0.587 * g + 0.114 * b < 0.5 else INK)
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label(cbar_label, color=INK2, fontsize=8)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7, colors=INK2, length=0)
    fig.patch.set_facecolor(SURFACE)
    plt.tight_layout()
    return fig

def plot_transitions(b):
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    seq = LinearSegmentedColormap.from_list("seq_blue", ["#fcfcfb", "#cde2fb", "#86b6ef", "#2a78d6", "#104281"])
    pct, n = b["transition_heat"]["pct"], b["transition_heat"]["row_n"]
    return _heatmap(pct, pct.map(lambda x: f"{x:.0f}%" if x >= 0.5 else ""),
                    "First new department, by starting department (% of branching accounts in each row)",
                    seq, Normalize(0, max(pct.to_numpy().max(), 1)),
                    row_labels=[f"{r}  (n={n[r]})" for r in pct.index], cbar_label="% of row")

def plot_related(b):
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    div = LinearSegmentedColormap.from_list("div_blue_red", ["#2a78d6", "#f0efec", "#e34948"])
    L = b["lift_matrix"]
    log_l = np.log2(L.where(L > 0)).clip(-2, 2)
    annot = L.map(lambda x: f"{x:.1f}" if np.isfinite(x) and x > 0 else "")
    return _heatmap(log_l, annot, f"Departments that go together (lift; red = more often than chance; "
                    f"{b['related_n_clients']} multi-department clients)", div, TwoSlopeNorm(vmin=-2, vcenter=0, vmax=2),
                    row_labels=[f"{d}  (n={int(b['lift_n'][d])})" for d in L.index],
                    cbar_label="log2(lift): +1 = twice as often, -1 = half as often")

def plot_time_to_branch(b):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for i, (name, cum) in enumerate(b["km_curves"].items()):
        style = dict(ls="--", color=INK2) if name == "All" else dict(color=SERIES[(i - 1) % len(SERIES)])
        ax.step(cum.index, cum.values, where="post", lw=2, label=f"{name} (n={b['km_n'][name]})", **style)
    ax.set_xlim(0, config.XMAX_BRANCH)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Days since the client's first hire", color=INK2)
    ax.set_ylabel("% that have added a new department", color=INK2)
    ax.set_title("Time to first new department, by starting department", loc="left", color=INK)
    ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
    ax.tick_params(colors=INK2, length=0)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.patch.set_facecolor(SURFACE)
    plt.tight_layout()
    return fig


# ================================================================ executive charts (notebook, section 5)
POS, NEG, GRID = "#2a78d6", "#e34948", "#e6e5e0"

def _short(dept):
    return str(dept).replace(" Services", "")

def _exec_axes(ax, title, subtitle):
    ax.set_title(title, loc="left", fontsize=13, color=INK, pad=14 + 13 * (subtitle.count("\n") + 1), fontweight="bold")
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0)

def plot_exec_expansion_paths(feat, top_industries=10, min_expanders=10):
    """Per industry: share of clients that expanded into a new department, where they usually start, and what
    they most often add first. Staff with an Unknown department are left out."""
    import matplotlib.pyplot as plt
    other = EXEC_OTHER
    b = feat["branch"]
    b = b[b["start_dept"].notna() & b["industry_group"].notna()]
    rows = []
    for ind in b["industry_group"].value_counts().index:
        d = b[b["industry_group"] == ind]
        e = d[d["branched"] == 1]
        if len(e) < min_expanders:
            continue
        st = d.loc[d["start_dept"] != other, "start_dept"].value_counts(normalize=True)
        # first additions other than the usual starting department (a client can't "add" the department it started in)
        nx = e.loc[~e["first_branch_dept"].isin([other, st.index[0]]), "first_branch_dept"].value_counts()
        rows.append({"industry": ind, "clients": len(d), "expanded": d["branched"].mean(),
                     "start": st.index[0], "start_share": st.iloc[0],
                     "next": nx.index[0], "next_share": nx.iloc[0] / len(e)})
        if len(rows) == top_industries:
            break
    t = pd.DataFrame(rows).sort_values("expanded")
    fig, ax = plt.subplots(figsize=(13, 0.62 * len(t) + 1.9))
    ax.barh(t["industry"], t["expanded"] * 100, color=POS, height=0.55)
    for i, r in enumerate(t.itertuples()):
        ax.text(r.expanded * 100 + 1, i, f"{r.expanded:.0%}", va="center", fontsize=10, color=INK, fontweight="bold")
        ax.text(r.expanded * 100 + 7, i,
                f"usually starts in {_short(r.start)} ({r.start_share:.0%})  \u2192  most often adds {_short(r.next)} first "
                f"({r.next_share:.0%})", va="center", fontsize=9, color=INK2)
    ax.set_xlim(0, t["expanded"].max() * 100 + 125)          # room for the label to the right of the longest bar
    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=10, labelcolor=INK)
    ax.set_yticks(range(len(t)), [f"{i}  ({n})" for i, n in zip(t["industry"], t["clients"])])
    _exec_axes(ax, "How clients expand into new departments, by industry",
               "Bar = share of clients that have added a new department  \u2022  label = most common starting department and "
               "most common first addition\n(%) = share of the industry's clients / of those that expanded  \u2022  (n) = clients  "
               "\u2022  Unknown departments left out")
    fig.patch.set_facecolor(SURFACE)
    plt.tight_layout()
    return fig

def plot_exec_growth_heatmap(prop, countries=("Australia", "United States", "United Kingdom", "New Zealand", "Canada")):
    """Chance a brand-new client (1-2 staff) reaches 5+ seats within a year, by industry x country."""
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    pp = prop["prospect_profiles"]
    m = (pp[pp["industry"].ne("Unknown") & pp["country"].isin(countries)]
         .pivot(index="industry", columns="country", values="fit_growth_p")[list(countries)] * 100)
    m = m.loc[m.mean(axis=1).sort_values(ascending=False).index]
    base = prop["growth_train"]["y"].mean() * 100
    seq = LinearSegmentedColormap.from_list("seq_blue", ["#fcfcfb", "#cde2fb", "#86b6ef", "#2a78d6", "#104281"])
    fig = _heatmap(m, m.map(lambda x: f"{x:.0f}%"), "", seq, Normalize(0, max(m.to_numpy().max(), base * 2)),
                   cbar_label="% chance")
    ax = fig.axes[0]
    ax.set_xticks(range(m.shape[1]), m.columns, rotation=0, ha="center", fontsize=9, color=INK)
    ax.set_title("Brand-new client starting with 1-2 staff  \u2022  darker = more likely  \u2022  sorted by average",
                 loc="left", fontsize=9, color=INK2)
    fig.set_size_inches(9.5, 0.42 * m.shape[0] + 2.2)
    fig.suptitle(f"Which new clients grow to 5+ seats within a year  (average new client: {base:.0f}%)",
                 x=0.02, ha="left", fontsize=13, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig

def plot_exec_growth_drivers(prop, top=6):
    """What raises / lowers a new client's chance of growing from 1-4 seats to 5+ within a year."""
    import matplotlib.pyplot as plt
    f = prop["new_factors"]
    label = {"industry_fit": "Industry", "country": "Country", "start_dept_grp": "Starts in"}
    d = f[f["factor"].isin(label) & ~f["level"].isin(["Other", "Unknown"])
          & (f["rows_growth"] >= 15)].copy()
    lvl = [(_short(v) if f == "start_dept_grp" else v) for f, v in zip(d["factor"], d["level"])]   # shorten departments only
    d["name"] = d["factor"].map(label) + ": " + pd.Series(lvl, index=d.index)
    d = pd.concat([d.nlargest(top, "growth_vs_avg_pts"), d.nsmallest(top, "growth_vs_avg_pts")])
    d = d.drop_duplicates("name").sort_values("growth_vs_avg_pts")
    launch = f[(f["factor"] == "launch_bucket") & (f["level"] == "3-4")]["growth_vs_avg_pts"]
    base = prop["growth_train"]["y"].mean() * 100
    fig, ax = plt.subplots(figsize=(10, 0.42 * len(d) + 1.8))
    colors = [POS if v > 0 else NEG for v in d["growth_vs_avg_pts"]]
    ax.barh(d["name"], d["growth_vs_avg_pts"], color=colors, height=0.6)
    for i, v in enumerate(d["growth_vs_avg_pts"]):
        ax.text(v + (0.25 if v >= 0 else -0.25), i, f"{v:+.1f} pts", va="center", ha="left" if v >= 0 else "right",
                fontsize=9, color=INK)
    lim = d["growth_vs_avg_pts"].abs().max() * 1.35
    ax.set_xlim(-lim, lim)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_xlabel("Change in chance vs an average new client (percentage points)", color=INK2, fontsize=9)
    ax.tick_params(axis="y", labelsize=9.5, labelcolor=INK)
    sub = (f"Average new client: {base:.0f}% reach 5 seats within a year (blue = raises the chance, red = lowers it)"
           + (f"\nBiggest single factor is launch size: starting with 3-4 staff adds {launch.iat[0]:+.0f} pts (not shown)"
              if len(launch) else ""))
    _exec_axes(ax, "What makes a new client more likely to grow past 4 seats", sub)
    ax.spines["bottom"].set_visible(True)
    fig.patch.set_facecolor(SURFACE)
    plt.tight_layout()
    return fig


# ---------------------------------------------------------------- executive charts: splits by department and industry x country
EXEC_OTHER = "Unknown"   # department not recorded or imputable: never shown as a label
SEAT_WINDOW_DAYS = 730                   # seat-growth charts: milestones reached within this many days of the first hire

def _exec_frame(feat):
    """Client accounts with industry, country, starting department, department history and seat milestones."""
    acc = feat["accounts"]
    b = feat["branch"][["first_branch_dept", "branched", "n_depts_ever"]]
    d = acc.join(b).copy()
    d["profile"] = d["industry"] + " · " + d["country"]
    return d[d["start_dept"].notna()]

def _exec_rate_chart(t, rate_col, label_col, n_col, title, subtitle, avg, avg_label, short_rows=False):
    """Horizontal bars of a rate (0-1) per row, bold value, grey explanation label, dashed average line."""
    import matplotlib.pyplot as plt
    t = t.sort_values(rate_col)
    fig, ax = plt.subplots(figsize=(13, 0.58 * len(t) + 2.0))
    ax.barh(range(len(t)), t[rate_col] * 100, color=POS, height=0.55)
    xmax = t[rate_col].max() * 100 + 120
    for i, r in enumerate(t.itertuples()):
        v = getattr(r, rate_col) * 100
        ax.text(v + xmax * 0.006, i, f"{v:.0f}%", va="center", fontsize=10, color=INK, fontweight="bold")
        ax.text(v + xmax * 0.05, i, getattr(r, label_col), va="center", fontsize=9, color=INK2)
    ax.axvline(avg * 100, color=INK2, linestyle="--", linewidth=1)
    ax.text(avg * 100, len(t) - 0.35, f" {avg_label}: {avg:.0%}", fontsize=8.5, color=INK2, va="bottom")
    ax.set_yticks(range(len(t)), [f"{_short(i) if short_rows else i}  ({n})" for i, n in zip(t.index, t[n_col])])
    ax.set_xlim(0, xmax)
    ax.set_ylim(-0.6, len(t) + 0.2)
    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=10, labelcolor=INK)
    _exec_axes(ax, title, subtitle)
    fig.patch.set_facecolor(SURFACE)
    plt.tight_layout()
    return fig

def _top_share(s, exclude=(), k=1):
    vc = s[~s.isin([EXEC_OTHER, *exclude])].value_counts()
    return [(n, c / len(s)) for n, c in vc.head(k).items()]

def plot_exec_dept_paths(feat, top=10, min_expanders=10):
    """Department level: for each starting department, the share that expanded and what they add first / second."""
    d = _exec_frame(feat)
    rows = {}
    for dept, g in d[d["start_dept"] != EXEC_OTHER].groupby("start_dept"):
        e = g[g["branched"] == 1]
        if len(e) < min_expanders:
            continue
        nxt = _top_share(e["first_branch_dept"], k=2)
        rows[dept] = {"clients": len(g), "rate": g["branched"].mean(),
                      "label": "most often adds " + "  •  then ".join(f"{_short(n)} ({p:.0%})" for n, p in nxt)}
    t = pd.DataFrame(rows).T.astype({"clients": int, "rate": float})
    t = t.sort_values("clients", ascending=False).head(top)
    return _exec_rate_chart(t, "rate", "label", "clients",
                            "Department expansion: what clients add after their first department",
                            "Bar = share of clients starting in that department that have added another one  •  label = most "
                            "common first additions (% of those that expanded)\n(n) = clients  •  Unknown departments "
                            "left out", d["branched"].mean(), "all clients", short_rows=True)

def plot_exec_profile_paths(feat, top=12, min_clients=40, min_expanders=10):
    """Industry x country: share that expanded, usual starting department and most common first addition."""
    d = _exec_frame(feat)
    d = d[d["industry"].ne("Unknown") & d["country"].ne("Unknown")]
    rows = {}
    for prof, g in d.groupby("profile"):
        e = g[g["branched"] == 1]
        if len(g) < min_clients or len(e) < min_expanders:
            continue
        (start, sp), = _top_share(g["start_dept"])
        (nxt, npct), = _top_share(e["first_branch_dept"], exclude=(start,)) or [("-", 0)]
        rows[prof] = {"clients": len(g), "rate": g["branched"].mean(),
                      "label": f"usually starts in {_short(start)} ({sp:.0%})  →  most often adds {_short(nxt)} first ({npct:.0%})"}
    t = pd.DataFrame(rows).T.astype({"clients": int, "rate": float}).sort_values("clients", ascending=False).head(top)
    return _exec_rate_chart(t, "rate", "label", "clients",
                            "Department expansion by industry and country",
                            f"Bar = share of clients that have added a new department  •  label = most common starting department "
                            f"and first addition\nIndustry · country groups with {min_clients}+ clients  •  (n) = clients  "
                            "•  Unknown departments left out", d["branched"].mean(), "all clients")

def _seat_frame(feat):
    """Clients that launched with 1-4 staff and have been observed long enough for the 2-year milestones."""
    d = _exec_frame(feat)
    d = d[d["launch_size"].between(1, 4) & (d["days_observed"] >= SEAT_WINDOW_DAYS + 30)].copy()
    d5, d10 = d["days_till_5_headcount"].astype(float), d["days_till_10_headcount"].astype(float)
    d["reach5"] = (d5 <= SEAT_WINDOW_DAYS).astype(int)
    d["reach10"] = (d10 <= SEAT_WINDOW_DAYS).astype(int)
    d["months_to_5"] = (d5 / 30.4).where(d["reach5"] == 1)
    return d

def _seat_label(g):
    m = g["months_to_5"].median()
    return f"reach 10+: {g['reach10'].mean():.0%}" + (f"  •  typical time to 5: {m:.0f} months" if pd.notna(m) else "")

def plot_exec_dept_seat_growth(feat, top=10, min_clients=30):
    """Seat growth by starting department: share of 1-4 seat launches that reach 5+ (and 10+) within 2 years."""
    d = _seat_frame(feat)
    rows = {}
    for dept, g in d[d["start_dept"] != EXEC_OTHER].groupby("start_dept"):
        if len(g) >= min_clients:
            rows[dept] = {"clients": len(g), "rate": g["reach5"].mean(), "label": _seat_label(g)}
    t = pd.DataFrame(rows).T.astype({"clients": int, "rate": float}).sort_values("clients", ascending=False).head(top)
    return _exec_rate_chart(t, "rate", "label", "clients",
                            "Seat growth by starting department: who grows past 4 seats",
                            "Bar = share of clients launching with 1-4 staff that reached (and held) 5+ seats within 2 years  "
                            "•  label = share reaching 10+, and typical months to 5\n(n) = clients observed 2+ years  •  "
                            "Unknown departments left out", d["reach5"].mean(), "all clients", short_rows=True)

def plot_exec_profile_seat_growth(feat, top=12, min_clients=30):
    """Seat growth by industry x country, same measure."""
    d = _seat_frame(feat)
    d = d[d["industry"].ne("Unknown") & d["country"].ne("Unknown")]
    rows = {}
    for prof, g in d.groupby("profile"):
        if len(g) >= min_clients:
            (start, sp), = _top_share(g["start_dept"]) or [("-", 0)]
            rows[prof] = {"clients": len(g), "rate": g["reach5"].mean(),
                          "label": f"{_seat_label(g)}  •  usually starts in {_short(start)}"}
    t = pd.DataFrame(rows).T.astype({"clients": int, "rate": float}).sort_values("clients", ascending=False).head(top)
    return _exec_rate_chart(t, "rate", "label", "clients",
                            "Seat growth by industry and country: who grows past 4 seats",
                            f"Bar = share of 1-4 staff launches that reached (and held) 5+ seats within 2 years\n"
                            f"Label = share reaching 10+, typical months to 5, usual starting department  •  groups with "
                            f"{min_clients}+ clients observed 2+ years  •  (n) = clients", d["reach5"].mean(), "all clients")
