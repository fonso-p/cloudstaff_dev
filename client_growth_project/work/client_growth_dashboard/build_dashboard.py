"""Build the single-file client growth dashboard.

Reads  work/client_growth_dashboard/dashboard_template.html
       data/client_monthly.json                       (written by prep.py)
       .claude/skills/cloudstaff-design/css/tokens.css (design tokens, inlined)
       .claude/skills/cloudstaff-design/assets/logos/cloudstaff-logo-landscape.svg (inlined)
Writes outputs/html/<YYYY-MM-DD>_Client_Growth_Dashboard.html  (data embedded, opens offline by double-click;
       fonts, icons and Chart.js come from CDNs, no data is sent)

Run from the project root:  python work/client_growth_dashboard/build_dashboard.py
"""
import datetime as dt
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
HERE = "work/client_growth_dashboard"
DS = ".claude/skills/cloudstaff-design"
OUT = f"outputs/html/{dt.date.today():%Y-%m-%d}_Client_Growth_Dashboard.html"


def main():
    html = open(f"{HERE}/dashboard_template.html", encoding="utf-8").read()
    tokens = open(f"{DS}/css/tokens.css", encoding="utf-8").read()
    logo = open(f"{DS}/assets/logos/cloudstaff-logo-landscape.svg", encoding="utf-8").read()
    logo = re.sub(r"<\?xml.*?\?>", "", logo).strip()
    data = json.load(open("data/client_monthly.json", encoding="utf-8"))
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")   # valid JSON, safe inside <script>
    for marker, value in [("/*__TOKENS__*/", tokens), ("<!--__LOGO__-->", logo), ("/*__DATA__*/", payload)]:
        assert html.count(marker) == 1, marker
        html = html.replace(marker, value)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"Wrote {OUT} ({os.path.getsize(OUT) / 1e6:.2f} MB, {len(data['clients']):,} clients)")
    return OUT


if __name__ == "__main__":
    main()
