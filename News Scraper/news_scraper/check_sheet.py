"""article_check.xlsx: one sheet to check, per article, (1) is it really this company and (2) is the event category right,
side by side with the company name. Written by `export` next to the CSVs. Needs openpyxl (skipped with a note if missing)."""
import os

OTHER = "Other / Unclassified"

# (group, header, width, key) -- key is read from the row dict built in rows()
COLUMNS = [
    ("COMPANY", "Company name", 30, "company_name"),
    ("COMPANY", "Company ID", 16, "company_id"),
    ("COMPANY", "Website", 22, "website"),
    ("COMPANY", "What its website says", 45, "company_profile"),
    ("ARTICLE", "Published", 11, "published_at"),
    ("ARTICLE", "Headline", 55, "title"),
    ("ARTICLE", "Publisher", 20, "publisher"),
    ("ARTICLE", "Source", 16, "origin"),
    ("ARTICLE", "Link", 10, "url"),
    ("IS IT THIS COMPANY?", "Match", 26, "match"),
    ("IS IT THIS COMPANY?", "Evidence found in the article", 30, "evidence"),
    ("IS IT THIS COMPANY?", "Why rejected", 34, "check"),
    ("IS IT THIS COMPANY?", "Name type", 22, "name_type"),
    ("IS IT THIS COMPANY?", "Article text read?", 14, "text_read"),
    ("IS IT THIS COMPANY?", "Opening of the article", 50, "lead"),
    ("WHAT HAPPENED?", "Event category", 22, "category"),
    ("WHAT HAPPENED?", "Event confidence", 15, "confidence"),
    ("WHAT HAPPENED?", "How the category was decided", 34, "basis"),
    ("YOUR CHECK", "Right company? (Yes/No/Unsure)", 16, None),
    ("YOUR CHECK", "Right category? (Yes/No/Unsure)", 16, None),
    ("YOUR CHECK", "Notes", 30, None),
]
GROUP_FILL = {"COMPANY": "1F4E79", "ARTICLE": "595959", "IS IT THIS COMPANY?": "2E7D32", "WHAT HAPPENED?": "B26A00", "YOUR CHECK": "7F6000"}

BASIS = {
    "rules": "Keyword rules (headline or opening)",
    "classifier": "Headline classifier",
    "classifier veto": "Rules matched, classifier overruled (no event)",
    "nlp event": "NLP event extraction",
    "zero-shot": "Zero-shot model",
    "setfit": "Trained category model",
    "denied": "Article denies the event",
}
TEXT = {"ok": "Yes", "too_short": "Partly (paywall / script page)", "http_error": "No (site refused)", "blocked_robots": "No (robots.txt)",
        "decode_failed": "No (link not decoded)", "not read": "No"}


def match_label(r, counted):
    """The identity indicator, from what the measured sample showed: an article with evidence was right ~9 in 10 times,
    one counted on the name alone only ~4 in 10."""
    if not counted:
        return "Rejected: not this company"
    if r.get("source") == "newsroom":
        return "Certain: company's own website"
    if (r.get("evidence") or "").strip():
        return "Likely: name + evidence"
    return "Unconfirmed: name only"


def confidence_label(r):
    if r.get("category") == OTHER:
        return "n/a (no event)"
    return {"high": "High", "medium": "Medium", "low": "Low"}.get(r.get("event_confidence") or "", "Unrated")


def rows(events, review, who, name_type):
    out = []
    for counted, src in ((True, events), (False, review)):
        for r in src:
            if r.get("signal_type", "news") != "news":
                continue
            cid = r["company_id"]
            basis = r.get("category_basis") or ""
            out.append({**who.get(cid, {}), "company_id": cid, "published_at": r.get("published_at", ""), "title": r.get("title", ""),
                        "publisher": r.get("publisher", ""), "origin": "Company website" if r.get("source") == "newsroom" else "News",
                        "url": r.get("url", ""), "match": match_label(r, counted), "evidence": r.get("evidence", ""),
                        "check": "" if counted else r.get("check", ""), "name_type": name_type.get(cid, ""),
                        "text_read": TEXT.get(r.get("text_status") or "not read", r.get("text_status")), "lead": r.get("lead", ""),
                        "category": r.get("category", "") if counted else "",
                        "confidence": confidence_label(r) if counted else "",
                        "basis": (BASIS.get(basis, basis[:1].upper() + basis[1:]) if basis else "No event words found") if counted else "",
                        "_counted": counted})
    rank = {"Certain": 0, "Likely": 1, "Unconfirmed": 2, "Rejected": 3}
    out.sort(key=lambda x: x["published_at"], reverse=True)          # newest first inside each company + match group (stable sort)
    out.sort(key=lambda x: ((x.get("company_name") or "").lower(), rank[x["match"].split(":")[0]]))
    return out


def write(out_dir, events, review, who, name_type, name="article_check.xlsx"):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError:
        print("  openpyxl not installed: article_check.xlsx skipped")
        return None
    data = rows(events, review, who, name_type)
    wb = Workbook()
    ws = wb.active
    ws.title = "Article check"
    base, bold, white = Font(name="Arial", size=9), Font(name="Arial", size=9, bold=True), Font(name="Arial", size=9, bold=True, color="FFFFFF")
    thin = Side(style="thin", color="D9D9D9")
    # row 1: group bands, row 2: column headers
    start = 1
    for i, (g, h, w, _) in enumerate(COLUMNS, 1):
        ws.cell(row=2, column=i, value=h).font = white
        ws.cell(row=2, column=i).fill = PatternFill("solid", fgColor=GROUP_FILL[g])
        ws.cell(row=2, column=i).alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = w
        if i == len(COLUMNS) or COLUMNS[i][0] != g:
            ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=i)
            c = ws.cell(row=1, column=start, value=g)
            c.font, c.fill, c.alignment = white, PatternFill("solid", fgColor=GROUP_FILL[g]), Alignment(horizontal="center")
            start = i + 1
    ws.row_dimensions[2].height = 30
    fills = {"Certain": "E2EFDA", "Likely": "E2EFDA", "Unconfirmed": "FFF2CC", "Rejected": "F2F2F2"}
    conf_fill = {"High": "E2EFDA", "Medium": "FFF2CC", "Low": "FCE4D6"}
    review_fill = PatternFill("solid", fgColor="FFFDE7")
    for r_i, row in enumerate(data, 3):
        for c_i, (g, h, _, key) in enumerate(COLUMNS, 1):
            v = row.get(key, "") if key else ""
            cell = ws.cell(row=r_i, column=c_i, value=v if v not in (None, "nan") else "")
            cell.font, cell.border = base, Border(bottom=thin)
            cell.alignment = Alignment(vertical="top", wrap_text=key in ("title", "lead", "company_profile", "check", "evidence"))
            if key == "url" and v:
                cell.hyperlink, cell.value, cell.font = v, "open", Font(name="Arial", size=9, color="0563C1", underline="single")
            if key == "match":
                cell.fill = PatternFill("solid", fgColor=fills[v.split(":")[0]])
                cell.font = bold
            if key == "confidence" and v in conf_fill:
                cell.fill = PatternFill("solid", fgColor=conf_fill[v])
            if key == "company_name":
                cell.font = bold
            if g == "YOUR CHECK":
                cell.fill = review_fill
    last = 2 + len(data)
    dv = DataValidation(type="list", formula1='"Yes,No,Unsure"', allow_blank=True)
    ws.add_data_validation(dv)
    for col in (len(COLUMNS) - 2, len(COLUMNS) - 1):
        dv.add(f"{get_column_letter(col)}3:{get_column_letter(col)}{max(last, 3)}")
    ws.freeze_panes = "B3"
    ws.auto_filter.ref = f"A2:{get_column_letter(len(COLUMNS))}{max(last, 2)}"

    g = wb.create_sheet("How to read")
    guide = [
        ("Column", "Meaning"),
        ("Match: Certain", "From the company's own website (its news feed), so it is this company. It may be a blog post rather than news."),
        ("Match: Likely", "Third-party article that names the company AND has evidence (domain, city, a keyword or name from its website). "
                          "On the 100-company sample (16 Nov 2026) these were right about 9 in 10 times."),
        ("Match: Unconfirmed", "Third-party article counted on the name alone. On the sample only about 4 in 10 were right: check these first."),
        ("Match: Rejected", "Found by the search but judged not to be this company; the reason is in 'Why rejected'. Not used in the score."),
        ("Evidence found in the article", "What confirmed the match: domain, ticker, legal/trading name, founder, city or country, website keywords."),
        ("Name type", "distinctive, or ambiguous (with the reason). Ambiguous names need stronger evidence."),
        ("Event category", "The Priority Score news category. 'Other / Unclassified' = news, but not one of the scored events."),
        ("Event confidence", "High = keyword rules and headline classifier agree (about 9 in 10 right on unseen companies). "
                             "Medium = rules only, about a coin flip. Low = classifier only. n/a = no event."),
        ("How the category was decided", "Which method set the category. A company-website post whose headline doesn't name the company "
                                         "is never an event (blog posts and guides)."),
        ("Your check", "Yellow columns: pick Yes / No / Unsure. These marks can later be used to measure and tune the matching."),
        ("Note", "Precision figures are from one hand-labelled sample (Claude, 16 Nov 2026), not a person's review yet."),
    ]
    for i, (a, b) in enumerate(guide, 1):
        g.cell(row=i, column=1, value=a).font = bold if i > 1 else white
        g.cell(row=i, column=2, value=b).font = base if i > 1 else white
        g.cell(row=i, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        g.cell(row=i, column=1).alignment = Alignment(vertical="top")
        if i == 1:
            for c in (1, 2):
                g.cell(row=1, column=c).fill = PatternFill("solid", fgColor="1F4E79")
    g.column_dimensions["A"].width, g.column_dimensions["B"].width = 30, 110

    path = os.path.join(out_dir, name)
    try:
        wb.save(path)
    except PermissionError:
        import datetime as dt
        path = os.path.join(out_dir, f"{name[:-5]}_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx")
        print(f"  {name} is open in another program, so this export went to {os.path.basename(path)}")
        wb.save(path)
    return path
