"""Quick environment check shown when the cs-data-analytics skill loads.

Always exits 0 so it never blocks the skill; problems are printed as MISSING lines.
Run by hand:  python .claude/skills/cs-data-analytics/scripts/check_env.py
"""
import importlib
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
lines = []


def ok(label, detail=""):
    lines.append(f"- OK       {label}" + (f" ({detail})" if detail else ""))


def missing(label, fix):
    lines.append(f"- MISSING  {label}: {fix}")


# Python
v = sys.version_info
if v >= (3, 10):
    ok("Python", f"{v.major}.{v.minor}")
else:
    missing("Python 3.10+", f"found {v.major}.{v.minor}; install a newer Python")

# Packages
absent = []
for mod in ("pandas", "openpyxl", "numpy", "scipy", "PIL", "matplotlib", "nbformat", "nbconvert", "ipykernel"):
    try:
        importlib.import_module(mod)
    except Exception:
        absent.append("pillow" if mod == "PIL" else mod)
if absent:
    missing("Python packages " + ", ".join(absent), "run `pip install -r requirements.txt` in the project folder")
else:
    ok("Python packages", "pandas, openpyxl, numpy, scipy, pillow, matplotlib, jupyter")

# Recalculation engine (needed for QA)
sys.path.insert(0, HERE)
try:
    from recalc import _find_soffice  # noqa: E402
    soffice = _find_soffice()
except Exception:
    soffice = None
engine = None
if soffice:
    engine = "LibreOffice"
else:
    for mod, name in (("win32com.client", "Excel via pywin32"), ("xlwings", "Excel via xlwings")):
        try:
            importlib.import_module(mod)
            engine = name
            break
        except Exception:
            pass
if engine:
    ok("Recalculation engine for QA", engine)
else:
    fix = {"Darwin": "`brew install --cask libreoffice`",
           "Windows": "install LibreOffice from libreoffice.org, or `pip install pywin32` with Excel installed"}.get(
        platform.system(), "`sudo apt install libreoffice-calc`")
    missing("Recalculation engine (LibreOffice or Excel)", fix + " - without it every build FAILs QA")

# Logo
logo = next((os.path.join(SKILL, "assets", n) for n in ("cloudstaff-logo.png", "logo.png")
             if os.path.exists(os.path.join(SKILL, "assets", n))), None)
if logo:
    ok("Cloudstaff logo", os.path.basename(logo))
else:
    missing("Cloudstaff logo", "add the full-colour landscape logo as assets/cloudstaff-logo.png in the skill folder (QA warns until then)")

# Git
if shutil.which("git"):
    try:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True,
                                timeout=10).stdout.strip() == "true"
    except Exception:
        inside = False
    ok("git", "project is a repository" if inside else "not a repository yet - Phase 5 will run `git init`")
else:
    missing("git", "install git (Mac: `xcode-select --install`) to use the Commit phase")

# Project folders
cwd = os.getcwd()
folders = [f for f in ("data/raw", "work", "outputs", "qa") if not os.path.isdir(os.path.join(cwd, f))]
if folders:
    lines.append(f"- NOTE     folders to create in {cwd}: " + ", ".join(folders))
else:
    ok("Project folders", "data/raw, work, outputs, qa")

print("\n".join(lines))
sys.exit(0)
