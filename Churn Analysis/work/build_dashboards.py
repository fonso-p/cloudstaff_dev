"""Check and build both churn dashboards into the LOCAL dashboards folder (never the repo).

    Desktop/Projects/Churn Analysis/Dashboards/
        <date>_Churn_Warning_Signs.html
        <date>_Churn_Outlook.html                      anonymised client IDs
        <date>_Churn_Outlook_with_shortcodes.html      real shortcodes: keep local, do not share
        data/   the JSON each page is built from (written by the notebook's export cells)

Run the whole notebook first (it writes data/), then from the repo root:
    .venv/Scripts/python.exe "Churn Analysis/work/build_dashboards.py"
Each data file is verified before its page is built; a failed check stops the build.
"""
import datetime as dt
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
WORK = REPO / "Churn Analysis" / "work"
SKILL = REPO / ".claude" / "skills" / "cs-dashboard" / "scripts"
OUT = pathlib.Path.home() / "Desktop" / "Projects" / "Churn Analysis" / "Dashboards"
DATE = f"{dt.date.today():%Y-%m-%d}"
PAGES = [("churn_warning_signs", "verify_onepager.py", "Churn_Warning_Signs"),
         ("churn_outlook", "verify_outlook.py", "Churn_Outlook")]


def run(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    tail = (r.stdout + r.stderr).strip().splitlines()
    if r.returncode:
        print("\n".join(tail[-25:]))
        sys.exit(f"stopped: {pathlib.Path(str(args[0])).name} failed")
    return tail


for folder, verify, name in PAGES:
    print(f"{name}: {run(WORK / folder / verify)[-1]}")
    html = OUT / f"{DATE}_{name}.html"
    run(SKILL / "build_dashboard.py", "--template", WORK / folder / "dashboard_template.html", "--data", OUT / "data" / f"{folder}.json", "--out", html)
    errs = [l for l in run(SKILL / "check_page.py", html) if "errors:" in l]
    bad = [l for l in errs if not l.rstrip().endswith("errors: []")]
    if bad:
        sys.exit("page errors:\n" + "\n".join(bad))
    print(f"  built {html} ({len(errs)} pages, no errors)")

print("  " + run(WORK / "churn_outlook" / "add_shortcodes.py")[-1])
