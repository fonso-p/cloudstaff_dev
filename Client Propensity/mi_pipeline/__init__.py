"""Client Propensity pipeline.

Steps (run in order by run_pipeline.run_all):
    step1_format     load and clean the raw files
    step2_merge      seat churn exit reasons, StaffCentral departments, industry groups
    step3_features   headcount timeline, account summary, department history, snapshots
    step4_branching  department branching analysis
    step4_propensity new-client scorecard and organic client list
    step5_output     Excel workbook and charts
    step5_extract    extract keyed for the Account Priority Dashboard (separate output)
"""
