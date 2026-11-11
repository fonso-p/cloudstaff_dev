"""Build the one-page guide to the dashboard pages (HTML and A4 PDF).

Reads  work/client_growth_dashboard/page_guide.html, the design tokens and the colour logo (inlined, on white).
Writes outputs/html/<date>_Client_Growth_Dashboard_Page_Guide.html and outputs/pdf/<date>_Client_Growth_Dashboard_Page_Guide.pdf
       (the PDF is printed by headless Chrome and must be a single page).
Run from the project root:  python work/client_growth_dashboard/build_page_guide.py
"""
import datetime as dt
import os
import re
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
DS = ".claude/skills/cloudstaff-design"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
NAME = f"{dt.date.today():%Y-%m-%d}_Client_Growth_Dashboard_Page_Guide"


def main():
    html = open("work/client_growth_dashboard/page_guide.html", encoding="utf-8").read()
    tokens = open(f"{DS}/css/tokens.css", encoding="utf-8").read()
    logo = re.sub(r"<\?xml.*?\?>", "", open(f"{DS}/assets/logos/cloudstaff-logo-landscape.svg", encoding="utf-8").read()).strip()
    for marker, value in [("/*__TOKENS__*/", tokens), ("<!--__LOGO__-->", logo)]:
        assert html.count(marker) == 1, marker
        html = html.replace(marker, value)
    os.makedirs("outputs/html", exist_ok=True)
    os.makedirs("outputs/pdf", exist_ok=True)
    out_html, out_pdf = f"outputs/html/{NAME}.html", os.path.abspath(f"outputs/pdf/{NAME}.pdf")
    open(out_html, "w", encoding="utf-8").write(html)
    args = [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
            f"--print-to-pdf={out_pdf}", "file://" + os.path.abspath(out_html)]
    try:
        subprocess.run(args, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:            # headless Chrome sometimes does not exit; the PDF is already written
        subprocess.run(["pkill", "-f", out_html])
    pages = len(re.findall(rb"/Type\s*/Page[^s]", open(out_pdf, "rb").read()))
    print(f"Wrote {out_html}\nWrote {out_pdf} ({pages} page{'s' if pages != 1 else ''})")
    if pages != 1:
        raise SystemExit("The guide must fit on one page: shorten the text or tighten the layout")


if __name__ == "__main__":
    main()
