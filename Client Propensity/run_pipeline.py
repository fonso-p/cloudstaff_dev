"""Run the whole Client Propensity pipeline and write the Excel workbook.

    uv run python "Client Propensity/run_pipeline.py"

From a notebook:  from run_pipeline import run_all;  res = run_all()
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so config / mi_pipeline import from anywhere

import config
from mi_pipeline import (step1_format, step2_merge, step3_features, step4_branching, step4_propensity, step5_output,
                         step5_extract)


def run_all(log=print, write_excel=False, write_extract=False):
    """Runs steps 1-4, then 5 (workbook) if write_excel and 5b (dashboard extract) if write_extract.
    Returns a dict of every table, keyed by step."""
    today = config.as_of()
    log(f"Data as of {today.date()} | raw data: {config.DATA_DIR}")
    formatted = step1_format.run(today, log)
    merged    = step2_merge.run(formatted, log)
    feat      = step3_features.run(merged, today, log)
    res = {"today": today, "formatted": formatted, "merged": merged, "features": feat,
           "branching":  step4_branching.run(feat, log),
           "propensity": step4_propensity.run(feat, today, log, current_seats=formatted["current_seats"])}
    if write_excel:
        res["workbook"] = step5_output.write_workbook(res)
        log(f"[5 output] workbook written: {res['workbook']}")
        res["department_reference"] = step5_output.write_department_reference(res)
        log(f"[5 output] department groupings written: {res['department_reference']}")
    if write_extract:
        res["extract"], res["extract_sheets"] = step5_extract.write_extract(res)
        log(f"[5b extract] dashboard extract written: {res['extract']} (+ CSVs)")
    return res


if __name__ == "__main__":
    run_all(write_excel=True, write_extract=True)
