"""cs_xl - Cloudstaff-branded, formula-driven Excel builder with a built-in QA gate.

Every workbook it produces has the same shape:
    Summary            short summary, KPI tiles, key charts, QA status strip
    <analysis tabs>    one topic per tab: plain explanation, formula tables, charts
    QA & Data Quality  live reconciliation checks, verification gates, DQ by column,
                       ETL decisions log, definitions, analyst checklist
    Raw Data           the source file exactly as received + added DQ/ETL columns
                       (all analysis formulas point here through named ranges)

Typical use (see example_build.py for a full worked example):

    import sys; sys.path.insert(0, "<skill>/scripts")
    from cs_xl import CSWorkbook, num
    from profile_data import load_source, row_issues

    df, meta = load_source("data/raw/staff.xlsx")
    wb = CSWorkbook("Staff Attrition Review", prepared_by="Jo Bert (Jobs) Olinares")
    wb.add_raw_data(df, meta, issues=row_issues(df, required=["Staff ID"]),
                    include=[...], derived={...})
    sh = wb.add_tab("Attrition by Month", explanation="...")
    t = sh.add_table(key="by_month", title="...", columns=[...], rows=[...],
                     expected=[...], formats=[...], note="Source: Raw Data (Include = Y)")
    sh.add_chart(t, kind="col", cats="Month", values=["Exits"], title="...")
    wb.summary.add_kpis([...]); wb.summary.add_findings([...])
    result = wb.save("outputs/excel/2026-09-25_Staff_Attrition_Review.xlsx")
"""
import datetime as dt
import json
import math
import os
import re
import sys

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference, ScatterChart, Series
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ------------------------------------------------------------------ brand
# Cloudstaff Design System v2.10.2 (.claude/skills/cloudstaff-design/css/tokens.css).
# Excel has no color-mix(), so the oklch mixes are resolved to hex here. Fills that carry
# white text use the AA-safe "-strong" variants. The old key names (navy, lemon, emerald,
# fuchsia, charcoal, light_blue, grey) stay as aliases so existing build scripts keep working.
BRAND = {
    "primary": "007AFF",          # --color-brand-primary
    "primary_strong": "006DE4",   # --color-brand-primary-strong (4.9:1 with white)
    "primary_soft": "DEEDFF",     # --color-brand-primary-soft
    "secondary": "00AB9C",        # --color-brand-secondary
    "secondary_strong": "007369", # --color-brand-secondary-strong (5.7:1 with white)
    "gold": "FFC426",             # --color-feature-02 / warning
    "danger": "D2253C",           # --color-utility-danger, darkened for text on white
    "text": "252938",             # --color-text-base-primary
    "muted": "737C90",            # --color-text-base-muted
    "border": "DCE3EE",           # --color-border-default
    "surface": "F3F5F8",          # --color-surface-page
    "white": "FFFFFF",
}
BRAND.update({
    "navy": BRAND["primary_strong"], "lemon": BRAND["gold"], "emerald": BRAND["secondary_strong"],
    "fuchsia": BRAND["danger"], "charcoal": BRAND["text"], "light_blue": BRAND["primary_soft"],
    "row": BRAND["surface"], "grey": BRAND["muted"],
})
# Feature palette order (feature-06 red is left out so it never reads as an error)
SERIES_COLOURS = ["007AFF", "00AB9C", "FFC426", "E34678", "4121A9",
                  "AA67FD", "F46600", "36D6E7", "87DD7D", "50505C"]
# Arial matches the theme font of the official Cloudstaff slide template and is on every
# machine; Poppins/Manrope are not, so Excel would substitute them for most recipients.
FONT = os.environ.get("CS_FONT", "Arial")
# Full-colour landscape logo on a white header (requester standard). No white/reversed logo.
LOGO_CANDIDATES = ["cloudstaff-logo.png", "logo.png"]

SUMMARY = "Summary"
QA_SHEET = "QA & Data Quality"
RAW_SHEET = "Raw Data"
HEADER_ROW = 5          # header row on Raw Data
MAX_EXPLANATION_WORDS = 120

_thin = Side(style="thin", color=BRAND["border"])
_navy_side = Side(style="medium", color=BRAND["navy"])
_lemon_side = Side(style="thick", color=BRAND["primary"])   # brand underrule


def F(size=10, bold=False, color=None, italic=False):
    return Font(name=FONT, size=size, bold=bold, italic=italic, color=color or BRAND["charcoal"])


def fill(hex_):
    return PatternFill("solid", start_color=hex_, end_color=hex_)


def qs(name):
    """Quote a sheet name for use in a formula."""
    return "'" + name.replace("'", "''") + "'"


def safe_sheet_name(name):
    name = re.sub(r"[\[\]\:\*\?\/\\]", "-", name).strip()
    return name[:31]


def num(ref, fmt="#,##0"):
    """Narrative token: inserts a live cell value. e.g. f"Churn was {num(t.ref('Total','Rate'),'0.0%')}"."""
    return "{{" + ref + "|" + fmt + "}}"


_TOKEN = re.compile(r"\{\{(.+?)\|(.*?)\}\}")


def const(text):
    """Mark a fixed method constant in narrative text (e.g. const('95%'), const('80%')) so QA
    knows it is not a data figure that should have been pulled live."""
    return "[[" + text + "]]"


def _unmark(s):
    return s.replace("[[", "").replace("]]", "")


def narrative_formula(text):
    """Turn text with {{ref|fmt}} tokens into an Excel string formula (or plain text)."""
    parts, pos = [], 0
    if not _TOKEN.search(text):
        return _unmark(text)
    for m in _TOKEN.finditer(text):
        if m.start() > pos:
            parts.append(("lit", text[pos:m.start()]))
        parts.append(("ref", m.group(1), m.group(2)))
        pos = m.end()
    if pos < len(text):
        parts.append(("lit", text[pos:]))
    out = []
    for p in parts:
        if p[0] == "lit":
            s = _unmark(p[1])
            for i in range(0, len(s), 240):          # Excel: max 255 chars per string literal
                out.append('"' + s[i:i + 240].replace('"', '""') + '"')
        else:
            out.append(f'TEXT({p[1]},"{p[2].replace(chr(34), chr(34) * 2)}")')
    return "=" + "&".join(out)


def narrative_plain(text):
    return _unmark(_TOKEN.sub("", text))


def _strip_strings(formula):
    return re.sub(r'"[^"]*"', '""', formula)


def _col_width_for(values, header):
    lens = [len(str(header))] + [len(str(v)) for v in values if v is not None and not str(v).startswith("=")]
    return max(10, min(42, max(lens) + 2))


# ------------------------------------------------------------------ table metadata
class Table:
    def __init__(self, sheet, key, title, columns, title_row, header_row, first, last, total_row):
        self.sheet, self.key, self.title, self.columns = sheet, key, title, list(columns)
        self.title_row, self.header_row, self.first, self.last = title_row, header_row, first, last
        self.total_row = total_row
        self.labels = []

    @property
    def ws(self):
        return self.sheet.ws

    def col(self, header):
        return self.columns.index(header) + 1

    def letter(self, header):
        return get_column_letter(self.col(header))

    def _row_of(self, label):
        if label in ("Total", "__total__") and self.total_row:
            return self.total_row
        for i, lab in enumerate(self.labels):
            if str(lab) == str(label):
                return self.first + i
        raise KeyError(f"Row '{label}' not in table '{self.key}'")

    def ref(self, row_label, header, absolute=True):
        """Cross-sheet reference to one cell, e.g. "'Churn'!$C$9"."""
        r, c = self._row_of(row_label), self.letter(header)
        return f"{qs(self.sheet.name)}!${c}${r}" if absolute else f"{qs(self.sheet.name)}!{c}{r}"

    def local(self, row_label, header):
        return f"{self.letter(header)}{self._row_of(row_label)}"

    def range(self, header):
        c = self.letter(header)
        return f"{qs(self.sheet.name)}!${c}${self.first}:${c}${self.last}"


# ------------------------------------------------------------------ sheet wrapper
class Sheet:
    def __init__(self, book, ws, title, explanation=None, kind="analysis"):
        self.book, self.ws, self.name, self.title, self.kind = book, ws, ws.title, title, kind
        self.cursor = 5
        self.width_cols = 12
        self.explanation = explanation
        self.tables, self.charts, self.narratives = [], [], []
        self._reserved_until = 0
        self._brand_header(title)
        if explanation:
            self.add_explanation(explanation)

    # ---- header band with logo -------------------------------------------------
    def _brand_header(self, title):
        ws = self.ws
        ws.sheet_view.showGridLines = False
        for c in range(1, 27):
            ws.column_dimensions[get_column_letter(c)].width = 14
        ws.row_dimensions[1].height = 44   # white header: colour logo, no blue band
        logo = self.book.logo_path
        if logo:
            try:
                from openpyxl.drawing.image import Image
                from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
                from openpyxl.drawing.xdr import XDRPositiveSize2D
                from openpyxl.utils.units import pixels_to_EMU
                img = Image(logo)
                h = 36
                w = int(img.width * h / img.height)
                img.anchor = OneCellAnchor(
                    _from=AnchorMarker(col=0, row=0, colOff=pixels_to_EMU(6), rowOff=pixels_to_EMU(11)),
                    ext=XDRPositiveSize2D(pixels_to_EMU(w), pixels_to_EMU(h)))
                ws.add_image(img)
            except Exception as e:  # never fail a build over the logo
                print(f"[cs_xl] logo not added: {e}", file=sys.stderr)
                logo = None
        if not logo:
            ws.cell(1, 1, "Cloudstaff").font = Font(name=FONT, size=16, bold=True, color=BRAND["primary"])
            ws.cell(1, 1).alignment = Alignment(vertical="center", indent=1)
        c = ws.cell(1, 4, self.book.title)
        c.font = Font(name=FONT, size=11, bold=True, color=BRAND["muted"])
        c.alignment = Alignment(vertical="center")
        t = ws.cell(2, 1, title)
        t.font = Font(name=FONT, size=18, bold=True, color=BRAND["navy"])
        ws.row_dimensions[2].height = 28
        s = ws.cell(3, 1, self.book.subtitle_line())
        s.font = F(9, italic=True, color=BRAND["grey"])
        for c in range(1, 13):
            ws.cell(3, c).border = Border(bottom=_lemon_side)
        self.book._branded.add(ws.title)

    # ---- text ------------------------------------------------------------------
    def _merged_text(self, row, text, ncols=None, size=10, bold=False, color=None, italic=False, label=None):
        ncols = ncols or max(8, self.width_cols)
        ws = self.ws
        val = narrative_formula(text)
        cell = ws.cell(row, 1, val)
        cell.font = F(size, bold=bold, color=color, italic=italic)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        width_chars = sum((ws.column_dimensions[get_column_letter(c)].width or 14) for c in range(1, ncols + 1)) * 1.05
        est = len(narrative_plain(text)) + 12 * len(_TOKEN.findall(text))
        lines = max(1, math.ceil(est / max(20, width_chars)))
        ws.row_dimensions[row].height = max(16, lines * (size + 5) + 4)
        self.narratives.append({"sheet": self.name, "cell": f"A{row}", "template": text, "label": label})
        return cell

    def add_explanation(self, text, heading="What this shows"):
        """Short, plain-English explanation. Keep it under ~120 words; use num() for figures."""
        self.explanation = text
        self.ws.cell(self.cursor, 1, heading.upper()).font = F(9, bold=True, color=BRAND["emerald"])
        self._merged_text(self.cursor + 1, text, label="explanation")
        self.cursor += 3

    def add_heading(self, text):
        self.ws.cell(self.cursor, 1, text).font = F(12, bold=True, color=BRAND["navy"])
        self.cursor += 1

    def add_text(self, text, italic=False, size=10):
        self._merged_text(self.cursor, text, italic=italic, size=size, label="text")
        self.cursor += 2

    def add_bullets(self, items, heading=None):
        if heading:
            self.add_heading(heading)
        for it in items:
            self._merged_text(self.cursor, "\u25aa  " + it, label="finding")
            self.cursor += 1
        self.cursor += 1

    # ---- tables ----------------------------------------------------------------
    def add_table(self, key, title, columns, rows, formats=None, expected=None, total=None,
                  expected_total=None, note=None, tolerance=1e-6, static_cols=(), n_col=None,
                  min_n=None, pct_sum_col=None, reconcile=None, col_widths=None, chart_room=False):
        """Write a branded table.

        rows      list of rows; cells may be values or formulas. Formula placeholders:
                  {r} this row, {c:Header} column letter, {first}/{last} first/last body row.
        expected  same shape as rows: values computed INDEPENDENTLY in pandas (use None
                  for label cells). QA compares them with Excel's results.
        total     {"label": "Total", "cells": {"Header": "=SUM({c:Header}{first}:{c:Header}{last})"}}
        static_cols   headers whose numbers are allowed to be typed-in (targets etc.) - say why in `note`
        n_col / min_n sample-size column and the minimum n below which a row is flagged
        pct_sum_col   header whose body should sum to 100%
        reconcile {"Header": "=<independent formula for the column total>"} -> live QA check
        """
        ws = self.ws
        formats = formats or [None] * len(columns)
        ncols = len(columns)
        self.width_cols = max(self.width_cols, ncols)
        r0 = max(self.cursor, 1)
        ws.cell(r0, 1, title).font = F(12, bold=True, color=BRAND["navy"])
        hr = r0 + 1
        first, last = hr + 1, hr + len(rows)
        total_row = last + 1 if total else None
        letters = {h: get_column_letter(i + 1) for i, h in enumerate(columns)}

        def sub(v, r):
            if isinstance(v, str) and v.startswith("="):
                v = v.replace("{r}", str(r)).replace("{first}", str(first)).replace("{last}", str(last))
                v = re.sub(r"\{c:(.+?)\}", lambda m: letters[m.group(1)], v)
            return v

        for j, h in enumerate(columns, start=1):
            c = ws.cell(hr, j, h)
            c.font = Font(name=FONT, size=10, bold=True, color=BRAND["white"])
            c.fill = fill(BRAND["navy"])
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = Border(bottom=_lemon_side)
        ws.row_dimensions[hr].height = 30
        t = Table(self, key, title, columns, r0, hr, first, last, total_row)
        for i, row in enumerate(rows):
            r = first + i
            t.labels.append(row[0])
            for j, v in enumerate(row, start=1):
                c = ws.cell(r, j, sub(v, r))
                c.font = F(10)
                c.border = Border(bottom=_thin)
                if i % 2 == 1:
                    c.fill = fill(BRAND["row"])
                fmt = formats[j - 1]
                if fmt:
                    c.number_format = fmt
                c.alignment = Alignment(horizontal="left" if j == 1 else "right", vertical="center")
        if total:
            lab = total.get("label", "Total")
            ws.cell(total_row, 1, lab)
            for h, f in total.get("cells", {}).items():
                ws.cell(total_row, columns.index(h) + 1, sub(f, total_row))
            for j in range(1, ncols + 1):
                c = ws.cell(total_row, j)
                c.font = F(10, bold=True, color=BRAND["navy"])
                c.fill = fill(BRAND["light_blue"])
                c.border = Border(top=_navy_side)
                if formats[j - 1]:
                    c.number_format = formats[j - 1]
                c.alignment = Alignment(horizontal="left" if j == 1 else "right")
        end = total_row or last
        if note:
            n = ws.cell(end + 1, 1, note)
            n.font = F(8.5, italic=True, color=BRAND["grey"])
        for j, h in enumerate(columns, start=1):
            L = get_column_letter(j)
            want = (col_widths or {}).get(h) or _col_width_for([row[j - 1] for row in rows], h if j > 1 else h + "    ")
            if j > 1:
                want = min(want, 18)
            if (ws.column_dimensions[L].width or 0) < want:
                ws.column_dimensions[L].width = want
        self.book.tables.append({
            "key": key, "sheet": self.name, "title": title, "columns": list(columns),
            "first": first, "last": last, "header_row": hr, "total_row": total_row,
            "labels": [str(x) for x in t.labels], "expected": expected, "expected_total": expected_total,
            "tolerance": tolerance, "static_cols": list(static_cols), "n_col": n_col, "min_n": min_n,
            "pct_sum_col": pct_sum_col, "has_note": bool(note),
        })
        if reconcile:
            for h, f in reconcile.items():
                src = f"{qs(self.name)}!{letters[h]}{total_row}" if total_row else \
                    f"SUM({qs(self.name)}!{letters[h]}{first}:{letters[h]}{last})"
                self.book.add_check(f"{title}: '{h}' ties back to raw data", "=" + src.lstrip("="), f, tolerance=max(tolerance, 1e-6))
        self.tables.append(t)
        self.cursor = max(end + (3 if note else 2), self.cursor)
        if chart_room:
            self.cursor = max(self.cursor, self._reserved_until + 1)
        return t

    # ---- charts ----------------------------------------------------------------
    def add_chart(self, table, kind="col", cats=None, values=None, title=None, y_title=None,
                  x_title=None, y_format=None, secondary=None, anchor=None, size=(16, 7.5),
                  labels=False, include_total=False, stacked=False):
        """Native Excel chart linked to a table (so it updates with the data).

        kind: col | bar | line | pie | combo (bars + line on secondary axis) | scatter
        anchor: 'right' (beside the table), 'below', or a cell like 'H6'. Charts added to
        a different sheet (e.g. wb.summary.add_chart(t, ...)) flow down that sheet.
        """
        if not title:
            raise ValueError("Every chart needs a title (QA Gate 7).")
        ws_t = table.ws
        cats = cats or table.columns[0]
        values = values or [table.columns[1]]
        last = table.total_row if (include_total and table.total_row) else table.last
        cat_ref = Reference(ws_t, min_col=table.col(cats), min_row=table.first, max_row=last)

        def val_ref(h):
            return Reference(ws_t, min_col=table.col(h), min_row=table.header_row, max_row=last)

        if kind in ("col", "bar", "combo"):
            ch = BarChart()
            ch.type = "bar" if kind == "bar" else "col"
            if stacked:
                ch.grouping, ch.overlap = "stacked", 100
            for h in values:
                ch.add_data(val_ref(h), titles_from_data=True)
            ch.set_categories(cat_ref)
            ch.gapWidth = 60
        elif kind == "line":
            ch = LineChart()
            for h in values:
                ch.add_data(val_ref(h), titles_from_data=True)
            ch.set_categories(cat_ref)
        elif kind == "pie":
            ch = PieChart()
            ch.add_data(val_ref(values[0]), titles_from_data=True)
            ch.set_categories(cat_ref)
        elif kind == "scatter":
            ch = ScatterChart()
            ch.style = 13
            xref = Reference(ws_t, min_col=table.col(cats), min_row=table.first, max_row=last)
            for h in values:
                s = Series(Reference(ws_t, min_col=table.col(h), min_row=table.first, max_row=last), xref, title=h)
                s.marker.symbol, s.graphicalProperties.line.noFill = "circle", True
                ch.series.append(s)
        else:
            raise ValueError(kind)

        for i, s in enumerate(ch.series):
            col = SERIES_COLOURS[i % len(SERIES_COLOURS)]
            if kind == "line":
                s.graphicalProperties.line.solidFill = col
                s.graphicalProperties.line.width = 28000
                s.smooth = False
            elif kind != "scatter":
                s.graphicalProperties.solidFill = col
                s.graphicalProperties.line.solidFill = col
        if kind == "pie":
            for i in range(table.last - table.first + 1):
                pt = DataPoint(idx=i)
                pt.graphicalProperties.solidFill = SERIES_COLOURS[i % len(SERIES_COLOURS)]
                ch.series[0].dPt.append(pt)
            ch.dataLabels = DataLabelList()
            ch.dataLabels.showPercent = True
        if kind == "combo" and secondary:
            ln = LineChart()
            for h in secondary:
                ln.add_data(val_ref(h), titles_from_data=True)
            for i, s in enumerate(ln.series):
                s.graphicalProperties.line.solidFill = SERIES_COLOURS[(i + 3) % len(SERIES_COLOURS)]
                s.graphicalProperties.line.width = 28000
            ln.y_axis.axId = 200
            ln.y_axis.title = None
            ln.y_axis.crosses = "max"
            ln.y_axis.majorGridlines = None
            ln.y_axis.delete = False
            ln.y_axis.number_format = "0%"
            ch += ln
        if labels and kind != "pie":
            ch.dataLabels = DataLabelList()
            ch.dataLabels.showVal = True
        ch.title = title
        if kind != "pie":
            ch.x_axis.title, ch.y_axis.title = x_title, y_title
            ch.x_axis.delete = False
            ch.y_axis.delete = False
            if y_format:
                ch.y_axis.number_format = y_format
                ch.y_axis.numFmt = None
        if len(ch.series) == 1 and kind not in ("pie",) and not (kind == "combo" and secondary):
            ch.legend = None
        elif ch.legend is not None:
            ch.legend.position = "b"
        ch.width, ch.height = size
        rows_needed = int(size[1] / 0.5) + 1

        if kind == "bar":
            ch.x_axis.scaling.orientation = "maxMin"   # keep table order top-to-bottom
        same_sheet = table.sheet is self
        if self.kind == "summary" and anchor is None:
            slot = getattr(self, "_slot", 0)
            if slot % 2 == 0:
                self._grid_row = self.cursor
                cell = f"A{self._grid_row}"
            else:
                cell = f"H{self._grid_row}"
            self._slot = slot + 1
            self.cursor = self._grid_row + rows_needed + 1
            self.width_cols = max(self.width_cols, 13)
        elif anchor in (None, "right") and same_sheet and len(table.columns) <= 6:
            col = len(table.columns) + 2
            cell = f"{get_column_letter(col)}{table.title_row}"
            self._reserved_until = max(self._reserved_until, table.title_row + rows_needed)
            self.cursor = max(self.cursor, self._reserved_until + 1)
        elif anchor in (None, "right", "below"):
            cell = f"A{self.cursor}"
            self.cursor += rows_needed + 1
        else:
            cell = anchor
        self.ws.add_chart(ch, cell)
        self.book.charts.append({"sheet": self.name, "title": title, "table": table.key, "kind": kind})
        return ch

    # ---- KPI tiles -------------------------------------------------------------
    def add_kpis(self, items, per_row=4):
        """items: [{"label", "formula", "fmt", "expected", "caption"}] - formula must reference data."""
        ws = self.ws
        r = self.cursor
        for i, it in enumerate(items):
            row = r + (i // per_row) * 4
            c1 = 1 + (i % per_row) * 3
            c2 = c1 + 1
            for rr in range(row, row + 3):
                for cc in (c1, c2):
                    ws.cell(rr, cc).fill = fill(BRAND["row"])
            for cc in (c1, c2):
                ws.cell(row, cc).border = Border(top=_lemon_side)
            ws.cell(row, c1, it["label"].upper()).font = F(8.5, bold=True, color=BRAND["grey"])
            ws.merge_cells(start_row=row, start_column=c1, end_row=row, end_column=c2)
            v = ws.cell(row + 1, c1, it["formula"])
            v.font = Font(name=FONT, size=20, bold=True, color=BRAND["navy"])
            v.number_format = it.get("fmt", "#,##0")
            v.alignment = Alignment(horizontal="left", vertical="center")
            ws.merge_cells(start_row=row + 1, start_column=c1, end_row=row + 1, end_column=c2)
            ws.row_dimensions[row + 1].height = 30
            cap = ws.cell(row + 2, c1, narrative_formula(it.get("caption", "")))
            cap.font = F(8.5, italic=True, color=BRAND["grey"])
            cap.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(start_row=row + 2, start_column=c1, end_row=row + 2, end_column=c2)
            ws.row_dimensions[row + 2].height = 26
            self.book.kpis.append({"sheet": self.name, "cell": f"{get_column_letter(c1)}{row + 1}",
                                   "label": it["label"], "expected": it.get("expected"),
                                   "tolerance": it.get("tolerance", 1e-6), "formula": it["formula"]})
        self.width_cols = max(self.width_cols, min(len(items), per_row) * 3 - 1)
        self.cursor = r + math.ceil(len(items) / per_row) * 4 + 1

    def add_findings(self, items, heading="Key findings"):
        self.add_bullets(items, heading)

    def add_recommendations(self, items, heading="Recommended next steps"):
        self.add_bullets(items, heading)


# ------------------------------------------------------------------ workbook
class CSWorkbook:
    def __init__(self, title, prepared_by="Cloudstaff Data & Analytics", requested_by=None,
                 period=None, logo_path=None, assets_dir=None):
        self.title = title
        self.prepared_by, self.requested_by, self.period = prepared_by, requested_by, period
        self.built_at = dt.datetime.now()
        self.logo_path = logo_path or self._find_logo(assets_dir)
        self.wb = Workbook()
        self.tables, self.kpis, self.charts, self.checks = [], [], [], []
        self.decisions, self.definitions, self.attestations = [], [], {}
        self.names, self.raw = {}, None
        self._branded = set()
        self.source_meta = None
        ws = self.wb.active
        ws.title = SUMMARY
        self.summary = Sheet(self, ws, "Summary", kind="summary")
        self.sheets = [self.summary]

    def _find_logo(self, assets_dir):
        dirs = [d for d in (assets_dir, os.environ.get("CS_ASSETS"),
                            os.path.join(HERE, "..", "assets"), os.path.join(os.getcwd(), "assets")) if d]
        for d in dirs:
            for n in LOGO_CANDIDATES:
                p = os.path.join(d, n)
                if os.path.exists(p):
                    return os.path.abspath(p)
        return None

    def subtitle_line(self):
        bits = []   # no "Prepared by" / "for" credit line on the tabs (requester preference)
        if self.period:
            bits.append(f"Period: {self.period}")
        if self.source_meta:
            bits.append(f"Source: {self.source_meta['file']}")
        bits.append(f"Built {self.built_at:%d %b %Y %H:%M}")
        return "  |  ".join(bits)

    # ---- raw data --------------------------------------------------------------
    def add_raw_data(self, df, meta, issues=None, include=None, derived=None, required=()):
        """Write the source data exactly as received, then the added DQ/ETL columns.

        issues   list[str] per row from profile_data.row_issues ('' = clean)
        include  list[bool|'Y'|'N'] per row - rows used by the analysis (default: all).
                 Excluding rows REQUIRES a logged decision (log_decision) or QA fails.
        derived  {"New Col": {"formula": "=IF({Exit Date}=\"\",\"Active\",\"Exited\")", "format": "..."}}
                 or {"New Col": {"values": [...], "rule": "how the values were produced"}}
                 {Column Name} in a formula becomes that column's cell on the same row.
        """
        self.source_meta = meta
        ws = self.wb.create_sheet(RAW_SHEET)
        sh = Sheet(self, ws, "Raw Data", kind="raw")
        self.raw = sh
        n = len(df)
        orig = [str(c) for c in df.columns]
        issues = issues if issues is not None else [""] * n
        if include is None:
            include = ["Y"] * n
        include = ["Y" if (x is True or str(x).upper() in ("Y", "YES", "TRUE", "1")) else "N" for x in include]
        derived = derived or {}
        added = ["Row ID", "DQ Issues", "DQ Status", "Include"] + list(derived.keys())
        allcols = orig + added
        letters = {h: get_column_letter(i + 1) for i, h in enumerate(allcols)}
        first, last = HEADER_ROW + 1, HEADER_ROW + max(n, 1)

        ws.cell(3, 1).value = (f"Source: {meta['file']}  |  {n:,} rows x {len(orig)} columns as received  |  "
                               f"SHA-256 {meta['sha256'][:16]}...  |  Loaded {meta['loaded_at']}")
        ws.cell(4, 1, "Blue headers = original data exactly as received (do not edit).  Teal headers = "
                      "columns added for data quality and ETL. Change Include to Y/N to add or remove a row "
                      "from every analysis, then re-run QA.").font = F(8.5, italic=True, color=BRAND["grey"])
        for j, h in enumerate(allcols, start=1):
            c = ws.cell(HEADER_ROW, j, h)
            c.font = Font(name=FONT, size=10, bold=True, color=BRAND["white"])
            c.fill = fill(BRAND["navy"] if h in orig and j <= len(orig) else BRAND["emerald"])
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[HEADER_ROW].height = 30

        date_cols = set()
        for j, col in enumerate(df.columns, start=1):
            vals = df[col].tolist()
            for i, v in enumerate(vals):
                c = ws.cell(first + i, j, v)
                if isinstance(v, str) and v.startswith("="):
                    c.data_type = "s"    # never let raw text execute as a formula
                if isinstance(v, (dt.datetime, dt.date)):
                    c.number_format = "yyyy-mm-dd" if (not isinstance(v, dt.datetime) or v.time() == dt.time(0)) else "yyyy-mm-dd hh:mm"
                    date_cols.add(j)
        base = len(orig)
        hdr_row = meta.get("header_row", 0) or 0
        for i in range(n):
            r = first + i
            ws.cell(r, base + 1, i + 2 + hdr_row)                     # row number in the source file
            ws.cell(r, base + 2, issues[i] or None)
            ws.cell(r, base + 3, f'=IF({letters["DQ Issues"]}{r}="","OK","CHECK")')
            ws.cell(r, base + 4, include[i])
        for k, (name, spec) in enumerate(derived.items()):
            j = base + 5 + k
            if "formula" in spec:
                tmpl = spec["formula"]
                for i in range(n):
                    r = first + i
                    f = re.sub(r"\{(.+?)\}", lambda m: f"{letters[m.group(1)]}{r}" if m.group(1) in letters else m.group(0), tmpl)
                    ws.cell(r, j, f)
            else:
                for i, v in enumerate(spec["values"]):
                    ws.cell(first + i, j, v)
            if spec.get("format"):
                for i in range(n):
                    ws.cell(first + i, j).number_format = spec["format"]
        dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=False)
        ws.add_data_validation(dv)
        dv.add(f"{letters['Include']}{first}:{letters['Include']}{last}")
        ws.conditional_formatting.add(
            f"{letters['DQ Status']}{first}:{letters['DQ Status']}{last}",
            FormulaRule(formula=[f'{letters["DQ Status"]}{first}="CHECK"'], font=Font(color=BRAND["fuchsia"], bold=True)))
        ws.conditional_formatting.add(
            f"{letters['Include']}{first}:{letters['Include']}{last}",
            FormulaRule(formula=[f'{letters["Include"]}{first}="N"'], fill=fill("FDE3EB")))
        ws.freeze_panes = ws.cell(first, 1)
        ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(allcols))}{last}"
        for j, h in enumerate(allcols, start=1):
            sample = [df[h].iloc[i] for i in range(min(n, 200))] if h in orig and j <= base else []
            ws.column_dimensions[get_column_letter(j)].width = max(12 if j not in date_cols else 12,
                                                                  min(40, _col_width_for(sample, h)))
        ws.column_dimensions[letters["DQ Issues"]].width = 44

        for h in allcols:
            nm = self._range_name(h)
            L = letters[h]
            self.wb.defined_names[nm] = DefinedName(nm, attr_text=f"{qs(RAW_SHEET)}!${L}${first}:${L}${last}")
            self.names[h] = nm
        self.raw_info = {"sheet": RAW_SHEET, "header_row": HEADER_ROW, "first": first, "last": last,
                         "orig_cols": orig, "added_cols": added, "letters": letters,
                         "include_y": include.count("Y"), "rows": n, "required": list(required),
                         "flagged": sum(1 for x in issues if x), "derived_rules":
                             {k: v.get("rule") or v.get("formula") for k, v in derived.items()}}
        # live source-integrity checks
        self.add_check("Raw Data row count equals source file", f"=ROWS({self.names['Row ID']})", n)
        self.add_check("Included + excluded rows equal total rows",
                       f'=COUNTIF({self.names["Include"]},"Y")+COUNTIF({self.names["Include"]},"N")', n)
        for col, t in meta.get("control_totals", {}).items():
            if col in self.names:
                self.add_check(f"Control total: sum of '{col}' matches source file",
                               f"=SUM({self.names[col]})", round(t["sum"], 6), tolerance=1e-6 * max(1, abs(t["sum"])))
        self.add_check("Include flags unchanged since verification (if FAIL: data edited - re-run QA)",
                       f'=COUNTIF({self.names["Include"]},"Y")', include.count("Y"))
        return sh

    def _range_name(self, header):
        base = "raw_" + (re.sub(r"[^A-Za-z0-9_]+", "_", header).strip("_") or "col")
        if re.match(r"^raw_\d", base):
            base = "raw_c" + base[4:]
        nm, k = base[:250], 2
        while nm in self.names.values():
            nm, k = f"{base[:245]}_{k}", k + 1
        return nm

    def col(self, header):
        """Named range for a Raw Data column, for use in formulas: wb.col('Status') -> raw_Status."""
        if header not in self.names:
            raise KeyError(f"'{header}' is not a Raw Data column. Columns: {list(self.names)}")
        return self.names[header]

    @property
    def INC(self):
        """Criteria pair to add to every COUNTIFS/SUMIFS so excluded rows drop out."""
        return f'{self.names["Include"]},"Y"'

    # ---- tabs --------------------------------------------------------------
    def add_tab(self, name, explanation, title=None):
        nm = safe_sheet_name(name)
        if nm in (SUMMARY, QA_SHEET, RAW_SHEET) or nm in self.wb.sheetnames:
            raise ValueError(f"Sheet name '{nm}' already used")
        ws = self.wb.create_sheet(nm)
        sh = Sheet(self, ws, title or name, explanation=explanation)
        self.sheets.append(sh)
        return sh

    # ---- governance --------------------------------------------------------
    def add_check(self, label, actual_formula, expected, tolerance=1e-6):
        """Live check written to the QA tab: PASS when |actual - expected| <= tolerance."""
        self.checks.append({"label": label, "actual": actual_formula, "expected": expected, "tolerance": tolerance})

    def log_decision(self, issue, rows_affected, decision, approved_by, columns=()):
        """Record an ETL / data-quality decision agreed with the requester."""
        self.decisions.append({"issue": issue, "rows": rows_affected, "decision": decision,
                               "approved_by": approved_by, "columns": list(columns),
                               "date": dt.date.today().isoformat()})

    def define(self, term, definition, formula_or_rule=""):
        self.definitions.append((term, definition, formula_or_rule))

    def attest(self, key, answer, note=""):
        """Analyst checklist. Keys: definitions_confirmed, period_confirmed, outliers_reviewed,
        sample_sizes_reviewed, no_causal_overreach, requester_questions_answered."""
        self.attestations[key] = {"answer": bool(answer), "note": note}

    # ---- QA sheet ----------------------------------------------------------
    def _build_qa_live(self):
        ws = self.wb.create_sheet(QA_SHEET)
        sh = Sheet(self, ws, "QA & Data Quality", kind="qa")
        sh.width_cols = 6
        self.qa_sheet = sh
        ws.column_dimensions["A"].width = 62
        for L in "BCDE":
            ws.column_dimensions[L].width = 18
        ws.column_dimensions["F"].width = 60
        ws.cell(5, 1, "OVERALL QA VERDICT").font = F(9, bold=True, color=BRAND["emerald"])
        ws.cell(6, 1, "Overall verdict (automated gates + live checks)").font = F(11, bold=True)
        # C6 filled in pass 2
        r = 9
        ws.cell(r - 1, 1, "Live checks - recalculate every time the file opens").font = F(12, bold=True, color=BRAND["navy"])
        heads = ["Check", "Actual", "Expected", "Difference", "Status"]
        for j, h in enumerate(heads, 1):
            c = ws.cell(r, j, h)
            c.font = Font(name=FONT, bold=True, color=BRAND["white"], size=10)
            c.fill = fill(BRAND["navy"])
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        first = r + 1
        for i, chk in enumerate(self.checks):
            rr = first + i
            ws.cell(rr, 1, chk["label"]).alignment = Alignment(wrap_text=True)
            a = chk["actual"] if str(chk["actual"]).startswith("=") else "=" + str(chk["actual"])
            ws.cell(rr, 2, a).number_format = "#,##0.####"
            e = chk["expected"]
            ws.cell(rr, 3, e).number_format = "#,##0.####"
            ws.cell(rr, 4, f"=IFERROR(B{rr}-C{rr},\"ERROR\")").number_format = "#,##0.######"
            ws.cell(rr, 5, f'=IF(ISERROR(B{rr}),"FAIL",IF(ABS(B{rr}-C{rr})<={chk["tolerance"]},"PASS","FAIL"))')
            for j in range(1, 6):
                ws.cell(rr, j).font = F(10)
                ws.cell(rr, j).border = Border(bottom=_thin)
        last = first + max(len(self.checks), 1) - 1
        self.qa_live = {"first": first, "last": last}
        self._status_format(ws, f"E{first}:E{last}")
        sh.cursor = last + 3
        return sh

    def _status_format(self, ws, rng):
        tl = rng.split(":")[0]
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("FAIL",{tl}))'],
                                                       fill=fill(BRAND["fuchsia"]), font=Font(color="FFFFFF", bold=True)))
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("WARN",{tl}))'],
                                                       fill=fill(BRAND["lemon"]), font=Font(color=BRAND["charcoal"], bold=True)))
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("PASS",{tl}))'],
                                                       fill=fill(BRAND["emerald"]), font=Font(color="FFFFFF", bold=True)))

    def _write_qa_static(self, results):
        sh, ws = self.qa_sheet, self.qa_sheet.ws
        lv = self.qa_live
        static = results["static_verdict"]
        ws.cell(6, 3, f'=IF(OR("{static}"="FAIL",COUNTIF(E{lv["first"]}:E{lv["last"]},"FAIL")>0),"FAIL",'
                      f'IF("{static}"="PASS WITH WARNINGS","PASS WITH WARNINGS","PASS"))')
        ws.merge_cells("C6:E6")
        ws.cell(6, 3).font = Font(name=FONT, size=14, bold=True)
        ws.cell(6, 3).alignment = Alignment(horizontal="center")
        self._status_format(ws, "C6:C6")
        ws.cell(7, 1, f"Automated verification ran {results['ran_at']} using {results['engine']}. "
                      "If you edit Raw Data, re-run QA before sharing.").font = F(8.5, italic=True, color=BRAND["grey"])
        r = sh.cursor
        # gates
        ws.cell(r, 1, "Verification gates (automated, run at build)").font = F(12, bold=True, color=BRAND["navy"])
        r += 1
        for j, h in enumerate(["Gate / check", "Status", "Detail"], 1):
            c = ws.cell(r, [1, 5, 6][j - 1], h)
            c.font = Font(name=FONT, bold=True, color="FFFFFF")
            c.fill = fill(BRAND["navy"])
        for j in (2, 3, 4):
            ws.cell(r, j).fill = fill(BRAND["navy"])
        g_first = r + 1
        for g in results["gates"]:
            r += 1
            ws.cell(r, 1, f"{g['gate']}  -  {g['name']}").font = F(10, bold=True, color=BRAND["navy"])
            ws.cell(r, 5, g["status"])
            for ch in g["checks"]:
                r += 1
                ws.cell(r, 1, "    " + ch["check"]).alignment = Alignment(wrap_text=True, vertical="top")
                ws.cell(r, 5, ch["status"])
                d = ws.cell(r, 6, ch.get("detail", "")[:800])
                d.alignment = Alignment(wrap_text=True, vertical="top")
                d.font = F(9)
                ws.row_dimensions[r].height = max(15, 13 * math.ceil(len(ch.get("detail", "")[:800]) / 70))
        self._status_format(ws, f"E{g_first}:E{r}")
        r += 3
        # DQ by column (formulas)
        ri = self.raw_info
        ws.cell(r, 1, "Data quality by column (live formulas on Raw Data)").font = F(12, bold=True, color=BRAND["navy"])
        r += 1
        for j, h in enumerate(["Column", "Blank cells", "Blank %", "Rows flagged mentioning column", "Notes"], 1):
            c = ws.cell(r, j if j < 5 else 6, h)
            c.font = Font(name=FONT, bold=True, color="FFFFFF")
            c.fill = fill(BRAND["navy"])
        ws.cell(r, 5).fill = fill(BRAND["navy"])
        for col in ri["orig_cols"]:
            r += 1
            nm = self.names[col]
            ws.cell(r, 1, col)
            ws.cell(r, 2, f"=COUNTBLANK({nm})").number_format = "#,##0"
            ws.cell(r, 3, f"=IFERROR(B{r}/ROWS({nm}),0)").number_format = "0.0%"
            ws.cell(r, 4, f'=COUNTIF({self.names["DQ Issues"]},"*"&A{r}&"*")').number_format = "#,##0"
            note = results.get("column_notes", {}).get(col, "")
            ws.cell(r, 6, note).font = F(9)
        r += 1
        ws.cell(r, 1, "Rows flagged CHECK (any issue)").font = F(10, bold=True)
        ws.cell(r, 2, f'=COUNTIF({self.names["DQ Status"]},"CHECK")')
        ws.cell(r, 3, f'=IFERROR(B{r}/ROWS({self.names["DQ Status"]}),0)').number_format = "0.0%"
        r += 1
        ws.cell(r, 1, "Rows excluded from analysis (Include = N)").font = F(10, bold=True)
        ws.cell(r, 2, f'=COUNTIF({self.names["Include"]},"N")')
        ws.cell(r, 3, f'=IFERROR(B{r}/ROWS({self.names["Include"]}),0)').number_format = "0.0%"
        self.qa_dq_rows = (r - 1, r)
        r += 3
        # decisions
        ws.cell(r, 1, "ETL and data-quality decisions (agreed with requester)").font = F(12, bold=True, color=BRAND["navy"])
        r += 1
        heads = [("A", "Issue"), ("B", "Rows"), ("C", "Approved by"), ("D", "Date"), ("F", "Decision")]
        for L, h in heads:
            c = ws[f"{L}{r}"]
            c.value = h
            c.font = Font(name=FONT, bold=True, color="FFFFFF")
            c.fill = fill(BRAND["navy"])
        ws[f"E{r}"].fill = fill(BRAND["navy"])
        if not self.decisions:
            r += 1
            ws.cell(r, 1, "No data changes or exclusions were made.").font = F(10, italic=True)
        for d in self.decisions:
            r += 1
            ws.cell(r, 1, d["issue"]).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(r, 2, d["rows"]).alignment = Alignment(horizontal="center")
            ws.cell(r, 3, d["approved_by"])
            ws.cell(r, 4, d["date"])
            ws.cell(r, 6, d["decision"]).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[r].height = max(15, 13 * math.ceil(max(len(d["decision"]) / 70, len(d["issue"]) / 70)))
        r += 3
        # definitions + ETL rules
        ws.cell(r, 1, "Definitions and method").font = F(12, bold=True, color=BRAND["navy"])
        r += 1
        for L, h in (("A", "Term"), ("F", "Definition / rule")):
            ws[f"{L}{r}"].value = h
        for L in "ABCDEF":
            ws[f"{L}{r}"].font = Font(name=FONT, bold=True, color="FFFFFF")
            ws[f"{L}{r}"].fill = fill(BRAND["navy"])
        rows = list(self.definitions) + [(f"Added column: {k}", "Derived during ETL", v) for k, v in ri["derived_rules"].items()]
        for term, defin, rule in rows:
            r += 1
            ws.cell(r, 1, term).font = F(10, bold=True)
            txt = defin + (f"  |  {rule}" if rule else "")
            ws.cell(r, 6, txt).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[r].height = max(15, 13 * math.ceil(len(txt) / 70))
        r += 3
        ws.cell(r, 1, "How to read this tab").font = F(10, bold=True, color=BRAND["navy"])
        ws.cell(r + 1, 1, "PASS = verified. PASS WITH WARNINGS = numbers verified, but read the warnings before "
                          "relying on the findings. FAIL = do not share; the file is a draft until fixed.").font = F(9, italic=True)

    def _write_summary_strip(self):
        ws = self.summary.ws
        lv = self.qa_live
        c = ws.cell(4, 1, f'="QA GATE: "&{qs(QA_SHEET)}!C6&"   |   Live checks passed: "&COUNTIF({qs(QA_SHEET)}!E{lv["first"]}:E{lv["last"]},"PASS")&" of "&ROWS({qs(QA_SHEET)}!E{lv["first"]}:E{lv["last"]})'
                             f'&"   |   Rows flagged for data quality: "&{qs(QA_SHEET)}!B{self.qa_dq_rows[0]}&"   |   Rows excluded: "&{qs(QA_SHEET)}!B{self.qa_dq_rows[1]}&"   (details: QA & Data Quality tab)"')
        c.font = F(9.5, bold=True)
        c.alignment = Alignment(vertical="center", indent=1)
        ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=max(8, self.summary.width_cols))
        ws.row_dimensions[4].height = 20
        self._status_format(ws, "A4:A4")

    # ---- save + verify --------------------------------------------------------
    def save(self, path, finalize_with_excel=False):
        """Build, recalculate, run every QA gate, write the QA tab, and save.

        Returns the QA result dict. If the verdict is FAIL the file is saved as
        *_DRAFT-QA-FAILED.xlsx so it cannot be mistaken for a final deliverable.
        """
        import qa
        from recalc import RecalcUnavailable, excel_finalize, recalc_copy
        if self.raw is None:
            raise RuntimeError("add_raw_data() must be called before save().")
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        if self.summary.cursor <= 5:
            self.summary.cursor = 6
        self._build_qa_live()
        order = [SUMMARY] + [s.name for s in self.sheets[1:]] + [QA_SHEET, RAW_SHEET]
        self.wb._sheets = [self.wb[n] for n in order]
        self.wb.active = 0
        for ws in self.wb.worksheets:
            ws.sheet_properties.tabColor = BRAND["navy"] if ws.title not in (QA_SHEET, RAW_SHEET) else BRAND["emerald"]
            ws.page_setup.orientation = "landscape"
            ws.page_setup.fitToWidth = 1
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.fitToHeight = 0
        self.wb.calculation.fullCalcOnLoad = True
        # summary strip needs qa_dq_rows -> compute provisional layout in pass 1 with placeholder
        self.qa_dq_rows = (1, 1)
        tmp = path + ".pass1.xlsx"
        self.wb.save(tmp)
        engine = "LibreOffice/Excel recalculation"
        try:
            calc = recalc_copy(tmp)
        except RecalcUnavailable as e:
            calc, engine = None, f"NONE ({e})"
        results = qa.run_gates(self, calc, engine)
        self._write_qa_static(results)
        self._write_summary_strip()
        self.wb.save(tmp)
        # pass 2: confirm live checks and the rebuilt QA tab evaluate cleanly
        try:
            calc2 = recalc_copy(tmp)
            results = qa.finalize(self, results, calc2)
        except RecalcUnavailable:
            pass
        final = path
        if results["verdict"] == "FAIL":
            root, ext = os.path.splitext(path)
            final = root + "_DRAFT-QA-FAILED" + ext
        os.replace(tmp, final)
        if finalize_with_excel:
            excel_finalize(final)
        results["output"] = os.path.abspath(final)
        qa.write_reports(self, results, final)
        print(qa.console_summary(results))
        return results

    def manifest(self):
        return {"title": self.title, "built_at": self.built_at.isoformat(timespec="seconds"),
                "prepared_by": self.prepared_by, "requested_by": self.requested_by, "period": self.period,
                "source": self.source_meta, "raw": self.raw_info, "tables": self.tables, "kpis": self.kpis,
                "checks": self.checks, "charts": self.charts, "decisions": self.decisions,
                "definitions": self.definitions, "attestations": self.attestations,
                "narratives": [n for s in self.sheets for n in s.narratives],
                "sheets": [{"name": s.name, "kind": s.kind, "explanation": s.explanation,
                            "tables": len(s.tables)} for s in self.sheets],
                "logo": self.logo_path}
