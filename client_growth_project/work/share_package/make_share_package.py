"""Builds a shareable copy of the client growth project (code only, no data) in outputs/share/.

Copies the scripts, notebooks (outputs cleared, so no client rows), design files and helper scripts
into the same folder layout as this project, so every script runs unchanged once the data files are added.
Re-run any time the code changes:  python work/share_package/make_share_package.py
"""
import os
import shutil

import nbformat

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
NAME = "client_growth_project"
DEST = os.path.join("outputs", "share", NAME)

# folders copied whole (logs, caches and review copies skipped)
FOLDERS = ["work/client_growth_dashboard", "work/early_signal_prediction", "work/icp_growth_potential",
           "work/share_package", ".claude/skills/cs-data-analytics/scripts", ".claude/skills/cs-data-analytics/assets",
           ".claude/skills/cloudstaff-design/css", ".claude/skills/cloudstaff-design/assets/logos"]
SKIP = shutil.ignore_patterns("__pycache__", "_review", "*.log", "*.pyc", ".DS_Store")
FILES = ["requirements.txt", "qa/2026-10-10_Client_Growth_Dashboard_REVIEW.md"] + \
        [f"qa/2026-10-10_Early_Signals_of_Account_Growth_{k}.md" for k in ["QA", "REVIEW", "STATS", "ANALYST", "RECONCILE"]]
NOTEBOOKS = ["notebooks/early_signal_prediction.ipynb", "notebooks/icp_growth_potential.ipynb"]

if os.path.exists(DEST):
    shutil.rmtree(DEST)
for d in FOLDERS:
    shutil.copytree(d, os.path.join(DEST, d), ignore=SKIP)
for f in FILES:
    if os.path.exists(f):
        os.makedirs(os.path.join(DEST, os.path.dirname(f)), exist_ok=True)
        shutil.copy2(f, os.path.join(DEST, f))
# notebooks: outputs cleared in the copy only (saved outputs show client names and staff rows); the originals are only read
os.makedirs(os.path.join(DEST, "notebooks"), exist_ok=True)
for nb in NOTEBOOKS:
    book = nbformat.read(nb, as_version=4)
    for c in book.cells:
        if c.cell_type == "code":
            c.outputs, c.execution_count = [], None
    nbformat.write(book, os.path.join(DEST, nb))
# empty folders the scripts write to or read from
for d in ["data/raw", "data/Organic rate", "Marketing", "outputs/excel", "outputs/html", "outputs/pdf", "qa"]:
    os.makedirs(os.path.join(DEST, d), exist_ok=True)
shutil.copy2("work/share_package/README_share.md", os.path.join(DEST, "README.md"))
shutil.make_archive(DEST, "zip", os.path.dirname(DEST), NAME)
print("Folder:", DEST)
print("Zip:   ", DEST + ".zip")
