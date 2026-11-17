"""Headline test set: real headlines gathered by event keywords, for hand-labelling and measuring the event categories.

  testset gather   search Google News and Bing News with keyword queries per category (AU, UK, US; half of the queries
                   steered to small and mid-sized firms), keep ~N distinct headlines per search bucket, and write
                     testset_label.xlsx   the sheet you label: headline, publisher, date, link, your category. Rows are shuffled
                                          and nothing shows which search found them or what the system predicts (blind).
                     testset_meta.csv     per headline: search bucket, query, source, region, and the system's prediction
                     pool.jsonl           every search result (a re-run skips queries already done, so a block costs nothing)
  testset score    read your labels from testset_label.xlsx and compare them with the system's predictions.

The search bucket is not the label: a "lays off" search also returns stories that are not layoffs, which is the point.
The near-miss bucket searches event words used in a non-event sense ("raises prices", "talent acquisition"); the
other bucket searches ordinary business news. Google is paced slowly (default one query per 20 s) and waits 20 minutes
when it blocks, so a run takes about an hour.
"""
import csv
import datetime as dt
import json
import os
import random
import re
import time

from . import http
from .classify import LAYOFFS_CAT, OTHER, classify, split_layoffs
from .sources import _google_once, bing_search

REGIONS = ["AU", "UK", "US"]
# half of the queries add this, so not every result is about Qantas or Google
SMB = '("small business" OR "local business" OR firm OR agency OR practice OR "family-owned")'

# bucket -> keyword queries. The first half run as is, the second half with SMB appended.
QUERIES = {
    "PE buyout": ['"private equity" acquires', '"private equity" "majority stake"', '"management buyout"', '"private equity" "take private"',
                  '"private equity" acquires', '"private equity" "majority stake"', '"backed by private equity" acquired'],
    "Funding round": ['"series a" raises', '"seed round"', '"funding round" startup', '"capital raise"',
                      '"raises" funding', '"series a"', '"secures" investment'],
    "M&A": ['acquires', '"has been acquired"', 'merger agreement', '"acquisition of"',
            'acquires', '"has acquired"', 'merge'],
    "Expansion / new office": ['"opens new office"', '"expands into"', '"new headquarters"', '"to create" jobs',
                               '"opens new office"', '"expands into"', '"new location"'],
    "Restructuring": ['"enters administration"', '"goes into liquidation"', 'restructure business', '"to close" office',
                      '"administration"', '"liquidation"', '"closes its doors"'],
    LAYOFFS_CAT: ['"lays off"', 'redundancies staff', '"job cuts"', '"jobs to go"',
                  '"lays off"', 'redundancies', '"cuts jobs"'],
    "Leadership change": ['appoints CEO', '"new chief executive"', 'CEO "steps down"', '"appointed managing director"',
                          'appoints CEO', '"managing director" appointed', '"steps down"'],
    "near-miss": ['"raises prices"', '"talent acquisition"', '"appointed distributor"', '"stocks to buy"', 'downsizers',
                  '"helps businesses expand"', 'fundraiser', '"cuts prices"', '"private equity" explained', '"new chapter"'],
    "other": ['"partners with"', '"wins award"', '"launches new"', '"wins contract"', '"case study"',
              '"partners with"', '"wins award"', '"launches"', 'sponsorship', '"celebrates"'],
}
CATEGORIES = ["PE buyout", "Funding round", "M&A", "Expansion / new office", "Restructuring", LAYOFFS_CAT, "Leadership change", OTHER]
LABEL_CHOICES = CATEGORIES + ["Not about a company", "Can't tell"]
SHEET = "testset_label.xlsx"


def _plan():
    """(bucket, query, region, source) for every search, in a fixed order."""
    out = []
    for bucket, qs in QUERIES.items():
        half = (len(qs) + 1) // 2
        for i, q in enumerate(qs):
            q = q if i < half else f"{q} {SMB}"
            for region in REGIONS:
                for source in ("google", "bing"):
                    out.append((bucket, q, region, source))
    return out


def _search(source, query, region, since, until, google_interval, log):
    if source == "bing":
        return bing_search(query, market=region)
    for block in range(4):                           # Google blocks for ~1 hour after too many queries: wait it out
        try:
            http.LIMITER.wait("google_testset", google_interval)
            return _google_once(query, region, since, until)        # one request (max 100 results), no splitting by month
        except http.FetchError as e:
            if block == 3 or not re.search(r"\b(503|429)\b", str(e)):
                raise
            log(f"    Google blocked ({str(e)[:12]}); waiting 20 min ({block + 1}/3)")
            time.sleep(1200)


def _norm(title):
    return re.sub(r"[^a-z0-9 ]", "", (title or "").lower()).strip()


def gather(out_dir, per_bucket=100, lookback_days=180, google_interval=20.0, seed=7, log=print):
    os.makedirs(out_dir, exist_ok=True)
    pool_path = os.path.join(out_dir, "pool.jsonl")
    done = set()
    if os.path.exists(pool_path):
        for line in open(pool_path, encoding="utf-8"):
            r = json.loads(line)
            done.add((r["bucket"], r["query"], r["region"], r["source"]))
    until = dt.date.today()
    since = until - dt.timedelta(days=lookback_days)
    plan = _plan()
    todo = [p for p in plan if p not in done]
    log(f"{len(plan)} searches, {len(plan) - len(todo)} already done · Google one query per {google_interval:.0f}s")
    with open(pool_path, "a", encoding="utf-8") as f:
        for i, (bucket, q, region, source) in enumerate(todo, 1):
            try:
                items = _search(source, q, region, since, until, google_interval, log)
                err = ""
            except Exception as e:                   # one failed search is skipped, not fatal; it is retried on the next run
                log(f"    {source} {region} {q[:40]}: {type(e).__name__}: {str(e)[:80]}")
                continue
            for it in items:
                d = it.get("published_at")
                if d and d.date() < since:
                    continue
                f.write(json.dumps({"bucket": bucket, "query": q, "region": region, "source": source, "title": it.get("title", ""),
                                    "publisher": it.get("publisher", ""), "url": it.get("url", ""),
                                    "published_at": d.date().isoformat() if d else "", "error": err}) + "\n")
            # a marker row, so a query with no results also counts as done
            f.write(json.dumps({"bucket": bucket, "query": q, "region": region, "source": source, "title": "", "error": "marker"}) + "\n")
            f.flush()
            if i % 10 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)} searches")
    return build_sheet(out_dir, per_bucket, seed, log)


def build_sheet(out_dir, per_bucket=100, seed=7, log=print):
    """Pick ~per_bucket distinct headlines per bucket from the pool (spread over queries, regions and sources), predict
    their category, and write the blind labelling sheet and the meta file. Labels already typed in an existing sheet are kept."""
    rows = [json.loads(l) for l in open(os.path.join(out_dir, "pool.jsonl"), encoding="utf-8")]
    rows = [r for r in rows if r.get("error") != "marker" and len(_norm(r["title"]).split()) >= 4 and classify(r["title"], "") is not None]
    rnd = random.Random(seed)
    seen, picked = set(), []
    for bucket in QUERIES:
        groups = {}
        for r in rows:
            if r["bucket"] == bucket:
                groups.setdefault((r["query"], r["region"], r["source"]), []).append(r)
        for g in groups.values():
            rnd.shuffle(g)
        got, keys = [], list(groups)
        rnd.shuffle(keys)
        while len(got) < per_bucket and any(groups.values()):  # round-robin over the searches: no single query dominates
            for k in keys:
                while groups[k]:
                    r = groups[k].pop()
                    if _norm(r["title"]) not in seen:
                        seen.add(_norm(r["title"]))
                        got.append(r)
                        break
                if len(got) >= per_bucket:
                    break
        picked += got
        log(f"  {bucket}: {len(got)} headlines")
    rnd.shuffle(picked)
    for i, r in enumerate(picked, 1):
        r["id"] = f"T{i:04d}"
    _predict(picked, log)
    meta_cols = ["id", "bucket", "query", "region", "source", "title", "publisher", "published_at", "url",
                 "pred_rules", "pred_classifier", "pred_classifier_p", "pred_system", "pred_basis"]
    with open(os.path.join(out_dir, "testset_meta.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=meta_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(picked)
    path = _write_sheet(out_dir, picked, log)
    log(f"Wrote {len(picked)} headlines to {path}")
    return path


def _predict(rows, log):
    """What the export would say from the headline alone: keyword rules, the headline classifier, and the two combined."""
    probs = [None] * len(rows)
    try:
        from . import nlp
        clf = nlp.EventClassifier()
        probs = clf.probs([r["title"] for r in rows])
    except ImportError:
        log("  nlp group not installed: predictions are keyword rules only")
    for r, p in zip(rows, probs):
        rule = classify(r["title"], "") or OTHER
        r["pred_rules"] = split_layoffs(rule, r["title"])
        if p:
            from .nlp import combine_event
            top, score = max(p.items(), key=lambda kv: kv[1])
            cat, basis, _ = combine_event(rule, p, OTHER)
            r["pred_classifier"], r["pred_classifier_p"] = split_layoffs(top, r["title"]), round(score, 3)
            r["pred_system"], r["pred_basis"] = split_layoffs(cat, r["title"]), basis or "none"
        else:
            r["pred_system"], r["pred_basis"] = r["pred_rules"], "rules" if rule != OTHER else "none"


def _old_marks(path):
    if not os.path.exists(path):
        return {}
    from openpyxl import load_workbook
    ws = load_workbook(path)["Label"]
    head = {c.value: c.column for c in ws[1] if c.value}
    out = {}
    for r in range(2, ws.max_row + 1):
        t = ws.cell(row=r, column=head["Headline"]).value
        marks = [ws.cell(row=r, column=head[h]).value for h in ("Your category", "Notes")]
        if t and any(marks):
            out[_norm(t)] = marks
    return out


def _write_sheet(out_dir, rows, log):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    path = os.path.join(out_dir, SHEET)
    old = _old_marks(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Label"
    cols = [("ID", 8), ("Headline", 80), ("Publisher", 22), ("Published", 11), ("Link", 8), ("Your category", 24), ("Notes", 40)]
    base, white = Font(name="Arial", size=9), Font(name="Arial", size=9, bold=True, color="FFFFFF")
    for c, (h, w) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font, cell.fill = white, PatternFill("solid", fgColor="7F6000" if h in ("Your category", "Notes") else "1F4E79")
        ws.column_dimensions[cell.column_letter].width = w
    yellow = PatternFill("solid", fgColor="FFFDE7")
    kept = 0
    for i, r in enumerate(rows, 2):
        marks = old.get(_norm(r["title"]), [None, None])
        kept += any(marks)
        vals = [r["id"], r["title"], r["publisher"], r["published_at"], "open" if r.get("url") else "", marks[0], marks[1]]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=c, value=v)
            cell.font = base
            cell.alignment = Alignment(vertical="top", wrap_text=c == 2)
            if c >= 6:
                cell.fill = yellow
        if r.get("url"):
            ws.cell(row=i, column=5).hyperlink = r["url"]
            ws.cell(row=i, column=5).font = Font(name="Arial", size=9, color="0563C1", underline="single")
    lists = wb.create_sheet("Lists")
    for i, v in enumerate(LABEL_CHOICES, 1):
        lists.cell(row=i, column=1, value=v)
    lists.sheet_state = "hidden"
    dv = DataValidation(type="list", formula1=f"=Lists!$A$1:$A${len(LABEL_CHOICES)}", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"F2:F{len(rows) + 1}")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:G{len(rows) + 1}"
    g = wb.create_sheet("How to label")
    guide = [("Category", "Pick it when the headline is mainly about…")] + [
        ("PE buyout", "a private equity firm buying, taking a majority stake in, or taking private a company"),
        ("Funding round", "a company raising money from investors (seed, Series A-E, venture or growth round, capital raise)"),
        ("M&A", "a company buying, merging with, or selling another business, division or stake (no private equity buyer)"),
        ("Expansion / new office", "a new office, branch, site or HQ, entering a new country or market, or a plan to add jobs"),
        ("Restructuring", "a reorganisation, a closure (office, plant, store, division), administration, receivership, liquidation or bankruptcy"),
        (LAYOFFS_CAT, "job cuts: layoffs, redundancies, jobs to go, cutting staff or headcount"),
        ("Leadership change", "a new or departing CEO, CFO, chair, managing director, board member or other senior executive"),
        (OTHER, "news about a company that is none of the above (product, partnership, award, contract, opinion, guide…)"),
        ("Not about a company", "about a government, sport, a person or the economy, with no company at the centre"),
        ("Can't tell", "the headline alone is too vague; use the link if you want to check"),
        ("", ""),
        ("How", "Label from the headline as a reader would; open the link only when unsure. One category per headline: the main event. "
                "Rows are in random order and the sheet doesn't show what the system thinks, so the labels are a fair test."),
    ]
    for i, (a, b) in enumerate(guide, 1):
        g.cell(row=i, column=1, value=a).font = white if i == 1 else Font(name="Arial", size=9, bold=True)
        g.cell(row=i, column=2, value=b).font = white if i == 1 else base
        if i == 1:
            g.cell(row=1, column=1).fill = g.cell(row=1, column=2).fill = PatternFill("solid", fgColor="1F4E79")
    g.column_dimensions["A"].width, g.column_dimensions["B"].width = 26, 110
    if kept:
        log(f"  kept your labels on {kept} headlines")
    try:
        wb.save(path)
    except PermissionError:
        path = path[:-5] + f"_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx"
        log(f"  {SHEET} is open, so this went to {os.path.basename(path)}")
        wb.save(path)
    return path


def score(out_dir, log=print):
    """Your labels vs the system's predictions: accuracy, and per category how often the system finds it (recall) and is
    right when it says it (precision)."""
    from openpyxl import load_workbook
    ws = load_workbook(os.path.join(out_dir, SHEET))["Label"]
    head = {c.value: c.column for c in ws[1] if c.value}
    labels = {ws.cell(row=r, column=head["ID"]).value: ws.cell(row=r, column=head["Your category"]).value for r in range(2, ws.max_row + 1)}
    meta = {r["id"]: r for r in csv.DictReader(open(os.path.join(out_dir, "testset_meta.csv"), encoding="utf-8"))}
    pairs = [(lab, meta[i]) for i, lab in labels.items() if lab in CATEGORIES and i in meta]
    skipped = sum(1 for v in labels.values() if v and v not in CATEGORIES)
    log(f"{len(pairs)} labelled headlines ({skipped} 'not about a company' or 'can't tell' left out, "
        f"{sum(1 for v in labels.values() if not v)} not labelled yet)")
    if not pairs:
        return
    for col in ("pred_rules", "pred_classifier", "pred_system"):
        if not any(m.get(col) for _, m in pairs):
            continue
        right = sum(lab == m[col] for lab, m in pairs)
        log(f"\n{col}: {right}/{len(pairs)} right ({right / len(pairs):.0%})")
        log(f"  {'category':24} {'labelled':>8} {'found':>6} {'recall':>7} {'said':>5} {'precision':>9}")
        for c in CATEGORIES:
            n_lab = sum(lab == c for lab, _ in pairs)
            n_said = sum(m[col] == c for _, m in pairs)
            hit = sum(lab == c and m[col] == c for lab, m in pairs)
            log(f"  {c:24} {n_lab:8} {hit:6} {hit / n_lab if n_lab else 0:7.0%} {n_said:5} {hit / n_said if n_said else 0:9.0%}")
