"""Score the event classification against the labelled headlines in gold_events.csv. No database needed.

    ../.venv/Scripts/python.exe eval/eval_events.py            (from the News Scraper folder)

gold_events.csv: one row per distinct story. set = build (10 sample companies + the 100-company test, the data the rules
and example headlines were developed on) or holdout (12 companies scraped afterwards and never used for development).
Labels were made by Claude from the headline alone: about_company yes/no, and the Priority Score category.
Only trust the holdout numbers as an estimate of real performance; the build set is flattered by 61 Canva layoff stories.
Add your own rows (or correct labels) and re-run after any change to classify.py, event_examples.py or nlp.combine_event.
"""
import csv
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from news_scraper import nlp                       # noqa: E402
from news_scraper.classify import OTHER, classify  # noqa: E402
from news_scraper.match import _pat, core_name     # noqa: E402


def main():
    rows = list(csv.DictReader(open(os.path.join(HERE, "gold_events.csv"), encoding="utf-8-sig")))
    clf = nlp.EventClassifier()
    probs = clf.probs([nlp.mask_name(r["title"], [_pat(core_name(r["company"]))]) for r in rows])
    for r, p in zip(rows, probs):
        r["rule"] = classify(r["title"], "") or OTHER
        r["final"], r["basis"], r["conf"] = nlp.combine_event(r["rule"], p, OTHER)
        r["about"] = r["about_company"] == "yes"
    for name in ("build", "holdout"):
        D = [r for r in rows if r["set"] == name]
        gold = [r for r in D if r["about"] and r["category"] != OTHER]
        print(f"\n{name}: {len(D)} stories, {len(gold)} real events  {dict(Counter(r['category'] for r in gold))}")
        for label, key in (("rules alone", "rule"), ("rules + classifier", "final")):
            pred = [r for r in D if r[key] != OTHER]
            ok = sum(r["about"] and r[key] == r["category"] for r in pred)
            hit = sum(r[key] == r["category"] for r in gold)
            print(f"  {label:<20} precision {ok / max(len(pred), 1):.2f} ({ok}/{len(pred)})   recall {hit / max(len(gold), 1):.2f} ({hit}/{len(gold)})")
        tiers = Counter((r["conf"], r["about"] and r["final"] == r["category"]) for r in D if r["final"] != OTHER)
        print("  by confidence: " + " · ".join(f"{t} {tiers[(t, True)]}/{tiers[(t, True)] + tiers[(t, False)]} right" for t in ("high", "medium", "low")))


if __name__ == "__main__":
    main()
