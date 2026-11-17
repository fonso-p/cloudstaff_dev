"""Score "is this article about the company?" against hand labels. Needs the database the articles were scraped into.

    ../.venv/Scripts/python.exe eval/eval_identity.py [--db data/news.db] [--show errors|all] [--company NAME]
    (from the News Scraper folder)

Labels, merged (a label in gold_identity.csv wins over gold_events.csv for the same article):
  gold_identity.csv  company_id + dedupe_key -> about_company_claude_labelled. From `nlp label` sheets labelled by Claude from the headline
                     and lead (16 Nov 2026): 10 sample companies, and 18 small companies from the 100-company test database.
  gold_events.csv    company name + headline -> about_company_claude_labelled (headline only). Matched to stored articles by exact headline.

It runs the same judging as `export` (pipeline.judge_all), so it measures exactly what export would write. A label is only
scored when its article is in the database, inside the lookback window and judged; the rest are listed as "not scored".
Today's date matters: articles age out of the 180-day lookback, so scores on an old database drift down in coverage.

The target (BUSINESS_REQUIREMENTS.md): at least 90% of counted third-party articles are about the right company.
Company-website articles (newsroom) are always counted and are reported separately.
"""
import argparse
import csv
import os
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from news_scraper.pipeline import judge_all  # noqa: E402

TARGET_PRECISION = 0.90


def load_labels(db_path):
    """{(company_id, dedupe_key): {"about": bool, "title": ..., "from": file}} plus the count of labels with no stored article."""
    db = sqlite3.connect(db_path)
    by_name = {name: cid for cid, name in db.execute("SELECT company_id, name FROM companies")}
    stored = defaultdict(list)
    for cid, title, key in db.execute("SELECT company_id, title, dedupe_key FROM articles"):
        stored[(cid, (title or "").strip())].append(key)
    keys = {k for ks in stored.values() for k in ks}
    labels, missing = {}, Counter()
    for r in csv.DictReader(open(os.path.join(HERE, "gold_events.csv"), encoding="utf-8-sig")):
        cid = by_name.get(r["company"])
        found = stored.get((cid, r["title"].strip()), [])
        if not found:
            missing["gold_events.csv"] += 1
        for k in found:
            labels[(cid, k)] = {"about": r["about_company_claude_labelled"].strip().lower() == "yes", "title": r["title"], "from": "gold_events.csv"}
    for r in csv.DictReader(open(os.path.join(HERE, "gold_identity.csv"), encoding="utf-8-sig")):
        if r["dedupe_key"] not in keys:
            missing["gold_identity.csv"] += 1
            continue
        labels[(r["company_id"], r["dedupe_key"])] = {"about": r["about_company_claude_labelled"] == "yes", "title": r["title"], "from": "gold_identity.csv"}
    return labels, missing


def rule_of(row, counted):
    """Which rule decided. Rows from before identity_rule existed fall back to the reason text."""
    if row.get("identity_rule"):
        return row["identity_rule"]
    if counted:
        return "company website" if row["source"] == "newsroom" else ("evidence" if row["evidence"] else "name only")
    return (row["check"] or "?").split(":")[0][:60]


def pct(a, b):
    return f"{a / b:.1%}" if b else "n/a"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "news.db"))
    ap.add_argument("--settings", default=None)
    ap.add_argument("--show", choices=["none", "errors", "all"], default="errors", help="list the mistakes (default) or every scored article")
    ap.add_argument("--company", help="only this company (name or id)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    labels, missing = load_labels(a.db)
    events, review = judge_all(a.db, a.settings)
    judged = {(r["company_id"], r["_key"]): (r, True) for r in events}
    judged.update({(r["company_id"], r["_key"]): (r, False) for r in review})

    scored = []
    for key, lab in labels.items():
        if key not in judged:
            missing["not judged (outside lookback, not news, or social)"] += 1
            continue
        row, counted = judged[key]
        if a.company and a.company.lower() not in (row["company_id"].lower(), (row.get("company_name") or "").lower()):
            continue
        scored.append({"row": row, "counted": counted, "about": lab["about"], "rule": rule_of(row, counted), "from": lab["from"]})

    news = [s for s in scored if s["row"]["source"] != "newsroom"]
    site = [s for s in scored if s["row"]["source"] == "newsroom"]
    tp = sum(s["counted"] and s["about"] for s in news)
    fp = sum(s["counted"] and not s["about"] for s in news)
    fn = sum(not s["counted"] and s["about"] for s in news)
    tn = sum(not s["counted"] and not s["about"] for s in news)
    precision = tp / (tp + fp) if tp + fp else 0.0

    print(f"Labels: {len(labels)} matched to stored articles · scored {len(scored)} · " +
          " · ".join(f"{k}: {v}" for k, v in missing.items()))
    print(f"Companies scored: {len({s['row']['company_id'] for s in scored})}")
    print(f"\nThird-party news ({len(news)} articles, {sum(s['about'] for s in news)} labelled about the company)")
    print(f"  precision {pct(tp, tp + fp)} ({tp}/{tp + fp})   recall {pct(tp, tp + fn)} ({tp}/{tp + fn})")
    print(f"  counted & right {tp} · counted & wrong {fp} · rejected & wrong {fn} · rejected & right {tn}")
    print(f"  target precision {TARGET_PRECISION:.0%}: {'MET' if precision >= TARGET_PRECISION else 'NOT MET'}"
          + ("   (fewer than 50 counted: treat as indicative)" if tp + fp < 50 else ""))
    if site:
        print(f"Company website: {len(site)} articles, {sum(s['about'] for s in site)} labelled about the company")

    print("\nBy deciding rule (third-party news)        n   about   not   " + "share right")
    by = defaultdict(list)
    for s in news:
        by[("counted" if s["counted"] else "rejected", s["rule"])].append(s)
    for (verdict, rule), ss in sorted(by.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        yes = sum(s["about"] for s in ss)
        right = yes if verdict == "counted" else len(ss) - yes
        print(f"  {verdict:<9} {rule[:30]:<30} {len(ss):>4} {yes:>6} {len(ss) - yes:>5}   {pct(right, len(ss)):>7}")

    if a.show != "none":
        rows = [s for s in news if a.show == "all" or s["counted"] != s["about"]]
        if rows:
            print("\n" + ("Every scored article" if a.show == "all" else "Mistakes") + " (verdict · label · rule · company · headline)")
        for s in sorted(rows, key=lambda s: (s["counted"], s["row"]["company_id"])):
            r = s["row"]
            print(f"  {'COUNTED ' if s['counted'] else 'REJECTED'} {'yes' if s['about'] else 'no ':<3} {s['rule'][:28]:<28} "
                  f"{r['company_id'][:18]:<18} {r['title'][:90]}")
    return precision


if __name__ == "__main__":
    main()
