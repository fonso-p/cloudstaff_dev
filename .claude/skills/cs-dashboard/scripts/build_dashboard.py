"""Build a single-file Cloudstaff dashboard from a template and a JSON data file.

Fills three markers in the template, each of which must appear exactly once:
    /*__TOKENS__*/   Cloudstaff design tokens (assets/tokens.css)
    <!--__LOGO__-->  Cloudstaff landscape logo (assets/cloudstaff-logo-landscape.svg)
    /*__DATA__*/     the JSON data (must contain meta.title)
and replaces __TITLE__ (the <title>) with meta.title.

The output opens by double-click. The data is embedded in the page; only fonts, icons and Chart.js
load from public CDNs, and no data is sent anywhere.

Usage:
    python build_dashboard.py --template work/x/dashboard_template.html --data data/x.json \
        --out "outputs/html/{date}_X_Dashboard.html"
{date} in --out becomes today's date (YYYY-MM-DD).
"""
import argparse
import datetime as dt
import html as htmlmod
import json
import os
import re

SKILL = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def build(template, data_path, out):
    page = open(template, encoding="utf-8").read()
    tokens = open(os.path.join(SKILL, "assets", "tokens.css"), encoding="utf-8").read()
    logo = open(os.path.join(SKILL, "assets", "cloudstaff-logo-landscape.svg"), encoding="utf-8").read()
    logo = re.sub(r"<\?xml.*?\?>", "", logo).strip()
    data = json.load(open(data_path, encoding="utf-8"))
    # allow_nan=False: NaN/inf are not valid JSON and would break JSON.parse in the page. Convert them to None in prep.
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    title = htmlmod.escape(data.get("meta", {}).get("title", "Dashboard"))
    for marker, value in [("/*__TOKENS__*/", tokens), ("<!--__LOGO__-->", logo), ("/*__DATA__*/", payload)]:
        assert page.count(marker) == 1, f"template must contain {marker} exactly once"
        page = page.replace(marker, value)
    page = page.replace("__TITLE__", title)
    out = out.replace("{date}", f"{dt.date.today():%Y-%m-%d}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "w", encoding="utf-8").write(page)
    print(f"Wrote {out} ({os.path.getsize(out) / 1e6:.2f} MB)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=os.path.join(SKILL, "assets", "template.html"))
    ap.add_argument("--data", default=os.path.join(SKILL, "assets", "example_data.json"))
    ap.add_argument("--out", default="outputs/html/{date}_Dashboard.html")
    a = ap.parse_args()
    build(a.template, a.data, a.out)
