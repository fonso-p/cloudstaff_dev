"""Read one or more articles from the command line.

    python -m article_reader URL [URL ...] [--json] [--chars 600]
"""
import argparse
import json
import sys

from .reader import read_article


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="article_reader")
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--chars", type=int, default=600, help="how much of the text to print (default 600)")
    ap.add_argument("--ignore-robots", action="store_true", help="do not check robots.txt")
    a = ap.parse_args(argv)
    for u in a.urls:
        r = read_article(u, respect_robots=not a.ignore_robots)
        if a.json:
            print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
            continue
        print(f"[{r.status}] {r.method or '-'} · {r.chars:,} chars · {r.seconds}s\n{r.final_url}\n{r.title}  ({r.published})")
        print(r.text[: a.chars] + ("…" if r.chars > a.chars else "") if r.text else f"error: {r.error}")
        print("-" * 80)


if __name__ == "__main__":
    main()
