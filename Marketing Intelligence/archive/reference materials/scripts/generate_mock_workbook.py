import random, datetime as dt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, FormulaRule, ColorScaleRule
from openpyxl.utils import get_column_letter

random.seed(42)
AS_OF = dt.date(2026, 11, 8)
N = 400

F = "Arial"
base = Font(name=F, size=10)
bold = Font(name=F, size=10, bold=True)
blue = Font(name=F, size=10, color="0000FF")
hdr_font = Font(name=F, size=10, bold=True, color="FFFFFF")
title = Font(name=F, size=14, bold=True)
in_fill = PatternFill("solid", fgColor="1F4E78")
calc_fill = PatternFill("solid", fgColor="375623")
out_fill = PatternFill("solid", fgColor="7F3F00")
yellow = PatternFill("solid", fgColor="FFFF00")
grey = PatternFill("solid", fgColor="D9D9D9")
thin = Side(style="thin", color="BFBFBF")
box = Border(left=thin, right=thin, top=thin, bottom=thin)
wrap = Alignment(wrap_text=True, vertical="top")

wb = Workbook()

# ---------------- Settings ----------------
S = wb.active; S.title = "Settings"
for c, w in zip("ABCDEFG", [42, 14, 18, 4, 24, 12, 44]): S.column_dimensions[c].width = w
S["A1"] = "Scoring Settings (edit the yellow cells, all scores recalculate)"; S["A1"].font = title
def lab(cell, text, f=bold): S[cell] = text; S[cell].font = f
def txt(cell, text): S[cell] = text; S[cell].font = base
def inp(cell, val, fmt=None, note=None):
    S[cell] = val; S[cell].font = blue; S[cell].fill = yellow; S[cell].border = box
    if fmt: S[cell].number_format = fmt
    if note: S[cell].comment = Comment(note, "Mock")

lab("A3", "As-of date (for news recency)"); inp("B3", AS_OF, "yyyy-mm-dd", "Mock assumption.")

lab("A5", "Component max points"); lab("B5", "New Logo"); lab("C5", "Organic Growth")
for i, (n, a, b) in enumerate([("Website Activities", 35, 50), ("News / Jobs / Social", 35, 50),
                               ("Diamond Referral", 15, 0), ("Prior BPO Experience", 15, 0)]):
    r = 6 + i; txt(f"A{r}", n); inp(f"B{r}", a); inp(f"C{r}", b)
S["C8"].comment = Comment("New Logo only.", "Mock"); S["C9"].comment = Comment("New Logo only.", "Mock")
lab("A10", "Total (should be 100)")
S["B10"] = "=SUM(B6:B9)"; S["C10"] = "=SUM(C6:C9)"
for c in ("B10", "C10"): S[c].font = bold; S[c].border = box

lab("A12", "Baseline for unknown data (share of max)"); lab("B12", "Baseline"); lab("C12", "Observed average")
txt("A13", "Website Activities"); inp("B13", 0.35, "0%", "Used when web data is unknown. Compare with the observed average of accounts that do have data.")
txt("A14", "News / Jobs / Social"); inp("B14", 0.30, "0%", "Used when news and jobs data are unknown.")
S["C13"] = f"=AVERAGE('Priority List'!$R$2:$R${N+1})"; S["C14"] = f"=AVERAGE('Priority List'!$S$2:$S${N+1})"
for c in ("C13", "C14"): S[c].number_format = "0%"; S[c].font = base; S[c].border = box
txt("A15", "Diamond / Prior BPO blanks are treated as 'No' (no record = no evidence), not given a baseline.")
S["A15"].font = Font(name=F, size=9, italic=True)

lab("A17", "Website sub-rules")
txt("A18", "Share: Team Builder page visit"); inp("B18", 0.4, "0%")
txt("A19", "Share: Form fill (last 30 days)"); inp("B19", 0.3, "0%")
txt("A20", "Share: Visit volume (scaled)"); inp("B20", 0.3, "0%")
txt("A21", "Visits for full volume credit"); inp("B21", 20)

lab("A23", "News / Jobs / Social sub-rules")
txt("A24", "Share: Strongest news signal"); inp("B24", 0.6, "0%")
txt("A25", "Share: Hiring activity"); inp("B25", 0.4, "0%")
txt("A26", "Job postings for full credit (if no spike)"); inp("B26", 20)

lab("A28", "Industry modifier (multiplies the score)")
txt("A29", "Multiplier at trend score 0"); inp("B29", 0.9, "0.00")
txt("A30", "Multiplier at trend score 1"); inp("B30", 1.1, "0.00")
txt("A31", "Unknown industry → 1.00 (no effect). Final score capped at 100.")
S["A31"].font = Font(name=F, size=9, italic=True)

lab("A33", "Tiers and routing")
txt("A34", "Tier 1 minimum score"); inp("B34", 70)
txt("A35", "Tier 2 minimum score"); inp("B35", 40)
txt("A36", "New Logo score sent to BDM (else SDR)"); inp("B36", 60)
txt("A37", "Also cap Tier 1 on low data coverage? (Yes/No)"); inp("B37", "No", None, "Optional now that baselines are used.")
txt("A38", "Minimum coverage for Tier 1 (if cap is on)"); inp("B38", 0.6, "0%")

lab("A40", "Hot triggers (pinned above the score)"); lab("B40", "Applies to"); lab("C40", "On? (Yes/No)")
for i, (n, a) in enumerate([("Diamond referral", "New Logo"), ("Form fill in last 30 days", "Both"),
                            ("Team Builder page visit", "Organic Growth"), ("Top news signal, recent", "Both")]):
    r = 41 + i; txt(f"A{r}", n); txt(f"B{r}", a); inp(f"C{r}", "Yes")
txt("A45", "Top news: minimum strength"); inp("B45", 1.0, "0.0")
txt("A46", "Top news: within N days"); inp("B46", 30)
txt("A47", "Hot New Logo accounts are always routed to BDM.")
S["A47"].font = Font(name=F, size=9, italic=True)

lab("E5", "news_signal"); lab("F5", "Strength"); lab("G5", "Reasoning")
news_map = [("Funding round", 1.0, "Fresh capital, usually spent on headcount"),
            ("PE buyout", 1.0, "Cost and scale mandates, strong outsourcing trigger"),
            ("M&A", 0.8, "Integration creates staffing needs"),
            ("Expansion / new office", 0.7, "Growth, but may hire locally"),
            ("Restructuring", 0.5, "Ambiguous: cost-cutting or shrinking"),
            ("Leadership change", 0.3, "Weak on its own"),
            ("Other / Unclassified", 0.3, "Scraper text not mapped to a category"),
            ("None", 0.0, "Checked, nothing found")]
for i, (n, v, why) in enumerate(news_map):
    r = 6 + i; txt(f"E{r}", n); inp(f"F{r}", v, "0.0"); txt(f"G{r}", why)
lab("E16", "Days since news (from)"); lab("F16", "Factor")
for i, (d, f) in enumerate([(0, 1.0), (31, 0.7), (91, 0.4), (181, 0.0)]):
    r = 17 + i; txt(f"E{r}", d); inp(f"F{r}", f, "0.0")
txt("G17", "Lookup by lower bound, e.g. 45 days → 0.7")
industries = [("Healthcare", 0.8), ("Logistics", 0.7), ("Legal", 0.5), ("Real Estate", 0.4),
              ("Accounting & Finance", 0.7), ("E-commerce", 0.9), ("Construction", 0.6),
              ("Insurance", 0.5), ("Marketing Agency", 0.6), ("SaaS / Tech", 0.8),
              ("Education", 0.3), ("Hospitality", 0.4)]
lab("E22", "Industry"); lab("F22", "Trend (0-1)")
for i, (n, v) in enumerate(industries):
    r = 23 + i; txt(f"E{r}", n); inp(f"F{r}", v, "0.0")
txt("G23", "Mock values; would come from Positive Industry News.")
# ---------------- Generate data ----------------
pref = ["Harbor", "Vantage", "Kestrel", "Northwind", "Bluegum", "Summit", "Ironbark", "Coral", "Meridian",
        "Redgate", "Silverline", "Wattle", "Pinnacle", "Cobalt", "Driftwood", "Granite", "Lumen", "Orchard",
        "Tasman", "Beacon", "Clearwater", "Fernhill", "Halcyon", "Juniper", "Larkspur", "Marlow", "Oakridge",
        "Quarry", "Riverstone", "Sterling", "Thornbury", "Waratah", "Yarra", "Ember", "Foxglove", "Gullwing"]
suff = {"Healthcare": ["Dental Group", "Medical", "Allied Health", "Clinics"],
        "Logistics": ["Freight", "Logistics", "Transport", "Supply Co"],
        "Legal": ["Legal", "Law Partners", "Lawyers"],
        "Real Estate": ["Realty", "Property Group", "Estates"],
        "Accounting & Finance": ["Accountants", "Advisory", "Financial", "Tax & Co"],
        "E-commerce": ["Store", "Goods Online", "Commerce"],
        "Construction": ["Builders", "Construction", "Civil"],
        "Insurance": ["Insurance", "Underwriting", "Cover"],
        "Marketing Agency": ["Creative", "Media", "Digital"],
        "SaaS / Tech": ["Software", "Labs", "Systems", "Cloud"],
        "Education": ["Academy", "Learning", "College"],
        "Hospitality": ["Hotels", "Hospitality", "Venues"]}
regions = ["AU-NSW", "AU-VIC", "AU-QLD", "AU-WA", "AU-SA", "NZ", "US", "UK"]
bands = ["1-10", "11-50", "51-200", "201-500", "500+"]
news_cats = [n for n, _, _ in news_map]
used = set()
rows = []
for i in range(N):
    goal = "Organic Growth" if random.random() < 0.4 else "New Logo"
    ind = random.choice(list(suff))
    while True:
        name = f"{random.choice(pref)} {random.choice(suff[ind])}"
        if name not in used: used.add(name); break
    intent = random.betavariate(1.05, 1.0)  # spread-out latent intent
    newlogo = goal == "New Logo"
    # Industry: sometimes unknown
    ind_val = ind if random.random() > 0.16 else None
    band = random.choice(bands) if random.random() > 0.18 else None
    reg = random.choice(regions) if random.random() > 0.10 else None
    # Website: unknown much more often for prospects
    web_unknown = random.random() < (0.68 if newlogo else 0.28)
    if web_unknown:
        visits = tb = ff = None
    else:
        visits = int(max(0, random.gauss(intent * 26, 4))) if random.random() < 0.35 + intent else 0
        tb = "Yes" if (visits > 0 and random.random() < intent * 0.45) else "No"
        ff = int(random.random() < intent * 0.28) * random.randint(1, 3) if visits > 0 else 0
    # News/Jobs: scraper coverage gaps
    nj_unknown = random.random() < (0.55 if newlogo else 0.38)
    if nj_unknown:
        news = ndate = jobs = spike = None
    else:
        if random.random() < 0.15 + intent * 0.8:
            weights = [intent, intent, intent * 0.8, 0.6, 0.5, 0.4, 0.3]
            news = random.choices(news_cats[:-1], weights=weights)[0]
            ndate = AS_OF - dt.timedelta(days=int(random.uniform(3, 60 + (1 - intent) * 280)))
        else:
            news, ndate = "None", None
        jobs = None if random.random() < 0.30 else int(max(0, random.gauss(intent * 26, 5)))
        spike = None if jobs is None else ("Yes" if jobs >= 18 and random.random() < 0.7 else "No")
    if newlogo:
        r_ = random.random()
        dia = "Yes" if r_ < 0.02 + intent * 0.25 else ("No" if r_ < 0.45 else None)
        r2 = random.random()
        bpo = "Yes" if r2 < 0.05 + intent * 0.5 else ("No" if r2 < 0.40 else None)
    else:
        dia = bpo = "N/A"
    rows.append([f"ACC-{1001+i}", name, goal, ind_val, band, reg, visits, tb, ff,
                 news, ndate, jobs, spike, dia, bpo])

# ---------------- Priority List ----------------
P = wb.create_sheet("Priority List", 0)
inputs = ["account_id", "company_name", "goal", "industry", "employee_band", "region",
          "web_visits_30d", "team_builder_visit", "form_fill_30d",
          "news_signal", "news_signal_date", "job_postings_30d", "hiring_spike",
          "diamond_referral", "prior_bpo_flag"]
calcs = ["industry_trend", "industry_modifier", "web_signal (0-1)", "news_jobs_signal (0-1)",
         "web_pts", "news_jobs_pts", "diamond_pts", "bpo_pts", "base_points"]
outs = ["priority_score", "estimated_fields", "data_coverage", "hot_trigger", "tier", "assigned_team",
        "rank_in_team_list", "sort_key"]
headers = inputs + calcs + outs
for j, h in enumerate(headers, 1):
    c = P.cell(row=1, column=j, value=h); c.font = hdr_font; c.border = box
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    c.fill = in_fill if h in inputs else (calc_fill if h in calcs else out_fill)
P.row_dimensions[1].height = 32
widths = [11, 26, 15, 20, 12, 10, 10, 11, 10, 22, 12, 11, 10, 11, 11,
          10, 10, 11, 12, 9, 10, 9, 9, 10, 10, 15, 10, 18, 9, 10, 10, 8]
for j, w in enumerate(widths, 1): P.column_dimensions[get_column_letter(j)].width = w
last = N + 1
for i, row in enumerate(rows):
    r = i + 2
    for j, v in enumerate(row, 1):
        c = P.cell(row=r, column=j, value=v); c.font = blue; c.border = box
        if j == 11 and v is not None: c.number_format = "yyyy-mm-dd"
    mW = f'IF(C{r}="New Logo",Settings!$B$6,Settings!$C$6)'
    mN = f'IF(C{r}="New Logo",Settings!$B$7,Settings!$C$7)'
    f = {}
    f["P"] = f'=IF(D{r}="","",IFERROR(VLOOKUP(D{r},Settings!$E$23:$F$34,2,FALSE),""))'
    f["Q"] = f'=IF(P{r}="",1,ROUND(Settings!$B$29+P{r}*(Settings!$B$30-Settings!$B$29),3))'
    f["R"] = (f'=IF(G{r}="","",ROUND(IF(H{r}="Yes",Settings!$B$18,0)+IF(N(I{r})>0,Settings!$B$19,0)'
              f'+MIN(G{r}/Settings!$B$21,1)*Settings!$B$20,3))')
    f["S"] = (f'=IF(AND(J{r}="",L{r}=""),"",ROUND(Settings!$B$24*IF(J{r}="",0,'
              f'IFERROR(VLOOKUP(J{r},Settings!$E$6:$F$13,2,FALSE),Settings!$F$12)'
              f'*IF(K{r}="",1,VLOOKUP(Settings!$B$3-K{r},Settings!$E$17:$F$20,2,TRUE)))'
              f'+Settings!$B$25*IF(M{r}="Yes",1,MIN(N(L{r})/Settings!$B$26,1)),3))')
    f["T"] = f'=ROUND({mW}*IF(R{r}="",Settings!$B$13,R{r}),1)'
    f["U"] = f'=ROUND({mN}*IF(S{r}="",Settings!$B$14,S{r}),1)'
    f["V"] = f'=IF(C{r}<>"New Logo","N/A",IF(N{r}="Yes",Settings!$B$8,0))'
    f["W"] = f'=IF(C{r}<>"New Logo","N/A",IF(O{r}="Yes",Settings!$B$9,0))'
    f["X"] = f'=SUM(T{r}:W{r})'
    f["Y"] = f'=MIN(100,ROUND(X{r}*Q{r},0))'
    f["Z"] = f'=IF(AND(R{r}="",S{r}=""),"Website, News",IF(R{r}="","Website",IF(S{r}="","News","")))'
    f["AA"] = (f'=(IF(R{r}="",0,{mW})+IF(S{r}="",0,{mN})+IF(ISNUMBER(V{r}),Settings!$B$8,0)'
               f'+IF(ISNUMBER(W{r}),Settings!$B$9,0))/IF(C{r}="New Logo",Settings!$B$10,Settings!$C$10)')
    f["AB"] = (f'=IF(AND(C{r}="New Logo",N{r}="Yes",Settings!$C$41="Yes"),"Diamond referral",'
               f'IF(AND(N(I{r})>0,Settings!$C$42="Yes"),"Form fill",'
               f'IF(AND(C{r}="Organic Growth",H{r}="Yes",Settings!$C$43="Yes"),"Team Builder visit",'
               f'IF(AND(Settings!$C$44="Yes",J{r}<>"",K{r}<>""),'
               f'IF(AND(IFERROR(VLOOKUP(J{r},Settings!$E$6:$F$13,2,FALSE),0)>=Settings!$B$45,'
               f'Settings!$B$3-N(K{r})<=Settings!$B$46),J{r},""),""))))')
    f["AC"] = (f'=IF(AND(Y{r}>=Settings!$B$34,OR(Settings!$B$37<>"Yes",AA{r}>=Settings!$B$38)),"Tier 1",'
               f'IF(Y{r}>=Settings!$B$35,"Tier 2","Tier 3"))')
    f["AD"] = (f'=IF(C{r}="Organic Growth","AM",IF(OR(N{r}="Yes",AB{r}<>"",Y{r}>=Settings!$B$36),"BDM","SDR"))')
    f["AE"] = f'=COUNTIFS($AD$2:$AD${last},AD{r},$AF$2:$AF${last},">"&AF{r})+1'
    f["AF"] = f'=IF(AB{r}<>"",1000,0)+Y{r}'
    for col, formula in f.items():
        c = P[f"{col}{r}"]; c.value = formula; c.font = base; c.border = box
    P[f"Q{r}"].number_format = "0.00"; P[f"P{r}"].number_format = "0.0"
    P[f"R{r}"].number_format = "0%"; P[f"S{r}"].number_format = "0%"
    P[f"AA{r}"].number_format = "0%"; P[f"Y{r}"].font = bold
    P[f"AF{r}"].font = Font(name=F, size=9, color="808080")
P["AF1"].comment = Comment("Helper: hot accounts sort first (+1000), then by score.", "Mock")
P.freeze_panes = "C2"
P.auto_filter.ref = f"A1:AF{last}"
P.conditional_formatting.add(f"D2:O{last}", FormulaRule(formula=['LEN(D2)=0'], fill=grey))
est = Font(name=F, size=10, italic=True, color="808080")
P.conditional_formatting.add(f"T2:T{last}", FormulaRule(formula=['LEN($R2)=0'], font=est))
P.conditional_formatting.add(f"U2:U{last}", FormulaRule(formula=['LEN($S2)=0'], font=est))
P.conditional_formatting.add(f"Y2:Y{last}", ColorScaleRule(start_type="num", start_value=0, start_color="F8696B",
                             mid_type="num", mid_value=50, mid_color="FFEB84", end_type="num", end_value=100, end_color="63BE7B"))
P.conditional_formatting.add(f"AB2:AB{last}", FormulaRule(formula=['LEN(AB2)>0'], fill=PatternFill("solid", fgColor="F4CCCC"),
                             font=Font(name=F, size=10, bold=True, color="990000")))

# ---------------- Data Gaps ----------------
G = wb.create_sheet("Data Gaps", 1)
G["A1"] = "Data Gaps & Score Distribution"; G["A1"].font = title
G["A2"] = "Grey cells on the Priority List are unknown. Unknown website/news use the Settings baseline (grey italic points)."
G["A2"].font = base
for c, w in zip("ABCDEFG", [28, 14, 16, 4, 20, 10, 10]): G.column_dimensions[c].width = w
for c, t in zip("ABC", ["Field (share blank)", "New Logo", "Organic Growth"]):
    G[f"{c}4"] = t; G[f"{c}4"].font = hdr_font; G[f"{c}4"].fill = in_fill
rng = lambda col: f"'Priority List'!${col}$2:${col}${last}"
gap_fields = [("industry", "D"), ("employee_band", "E"), ("region", "F"), ("Website (visits)", "G"),
              ("news_signal", "J"), ("job_postings_30d", "L"), ("diamond_referral", "N"), ("prior_bpo_flag", "O")]
for i, (lbl, col) in enumerate(gap_fields):
    r = 5 + i; G[f"A{r}"] = lbl; G[f"A{r}"].font = base
    for gc, goal in (("B", "New Logo"), ("C", "Organic Growth")):
        if goal == "Organic Growth" and col in ("N", "O"): G[f"{gc}{r}"] = "N/A"
        else:
            G[f"{gc}{r}"] = f'=SUMPRODUCT(({rng("C")}="{goal}")*(LEN({rng(col)})=0))/MAX(1,COUNTIF({rng("C")},"{goal}"))'
            G[f"{gc}{r}"].number_format = "0%"
        G[f"{gc}{r}"].font = base; G[f"{gc}{r}"].border = box
r = 13
G[f"A{r}"] = "Average data coverage"; G[f"A{r}"].font = bold
for gc, goal in (("B", "New Logo"), ("C", "Organic Growth")):
    G[f"{gc}{r}"] = f'=AVERAGEIF({rng("C")},"{goal}",{rng("AA")})'; G[f"{gc}{r}"].number_format = "0%"; G[f"{gc}{r}"].font = bold
for c, t in zip("EFG", ["Team / Tier", "Accounts", "of which hot"]):
    G[f"{c}4"] = t; G[f"{c}4"].font = hdr_font; G[f"{c}4"].fill = out_fill
rr = 5
for team in ["AM", "BDM", "SDR"]:
    for tier in ["Tier 1", "Tier 2", "Tier 3"]:
        G[f"E{rr}"] = f"{team} – {tier}"; G[f"E{rr}"].font = base
        G[f"F{rr}"] = f'=COUNTIFS({rng("AD")},"{team}",{rng("AC")},"{tier}")'
        G[f"G{rr}"] = f'=COUNTIFS({rng("AD")},"{team}",{rng("AC")},"{tier}",{rng("AB")},"?*")'
        for c in "FG": G[f"{c}{rr}"].font = base; G[f"{c}{rr}"].border = box
        rr += 1
G["A16"] = "Score band"; G["B16"] = "New Logo"; G["C16"] = "Organic Growth"
for c in "ABC": G[f"{c}16"].font = hdr_font; G[f"{c}16"].fill = out_fill
for i, (lo, hi) in enumerate([(0, 19), (20, 39), (40, 59), (60, 79), (80, 100)]):
    r = 17 + i; G[f"A{r}"] = f"{lo}–{hi}"; G[f"A{r}"].font = base
    for gc, goal in (("B", "New Logo"), ("C", "Organic Growth")):
        G[f"{gc}{r}"] = f'=COUNTIFS({rng("C")},"{goal}",{rng("Y")},">={lo}",{rng("Y")},"<={hi}")'
        G[f"{gc}{r}"].font = base; G[f"{gc}{r}"].border = box
from openpyxl.chart import BarChart, Reference
ch = BarChart(); ch.title = "Priority Score distribution"; ch.y_axis.title = "Accounts"
ch.add_data(Reference(G, min_col=2, max_col=3, min_row=16, max_row=21), titles_from_data=True)
ch.set_categories(Reference(G, min_col=1, min_row=17, max_row=21)); ch.height = 7; ch.width = 14
G.add_chart(ch, "I4")

# ---------------- README ----------------
R = wb.create_sheet("How It Works", 0)
R.column_dimensions["A"].width = 115
lines = [
 ("Marketing Intelligence – Mock Priority Score Dataset (v2)", title),
 ("All companies and values are fictional, generated for illustration.", base), ("", base),
 ("How the score works", bold),
 ("1. Website and News/Jobs each produce a signal from 0 to 1. Unknown signals use the baseline on Settings (an 'average' assumption).", base),
 ("2. Points = signal × the component's max for that goal. Diamond Referral and Prior BPO add full points if 'Yes' (New Logo only).", base),
 ("3. base_points × industry_modifier = Priority Score (capped at 100). Industry nudges the score (0.9–1.1×) but can't create one on its own.", base),
 ("4. Hot triggers (Diamond referral, form fill, Team Builder visit, recent top-strength news) are flagged and pinned above the score in each team's list.", base),
 ("", base),
 ("Why baselines instead of rescaling", bold),
 ("An account we know little about lands near the middle, not at the top or bottom. One strong signal lifts it, but only real evidence can push it into Tier 1.", base),
 ("estimated_fields shows which components used the baseline; their points appear in grey italics. data_coverage is shown for information only.", base),
 ("", base),
 ("Three kinds of 'empty'", bold),
 ("Not applicable: Diamond/BPO for Organic Growth → 'N/A'. Checked, found nothing: 'None' or 0 → real zero. Unknown: blank → baseline (Diamond/BPO blanks = 'No').", base),
 ("", base),
 ("Routing and ranking", bold),
 ("Organic Growth → AM. New Logo with a Diamond referral, any hot trigger, or score ≥ BDM threshold → BDM. Other New Logo → SDR.", base),
 ("rank_in_team_list: hot accounts first, then by score, within each team's list. Sort by this column (or filter by assigned_team) to see a team's list.", base),
 ("", base),
 ("Testing", bold),
 ("Delete input values to simulate more blanks; change baselines, weights, modifier range, or trigger switches on Settings. Everything recalculates.", base),
]
for i, (t, fnt) in enumerate(lines, 1):
    R[f"A{i}"] = t; R[f"A{i}"].font = fnt; R[f"A{i}"].alignment = Alignment(wrap_text=True)
wb.save("mock/Priority_Score_Mock_Dataset.xlsx")
print("ok")
