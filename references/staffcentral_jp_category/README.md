# StaffCentral departments: JP Category groupings

How a staffer's **department** is set from StaffCentral, for every project in this repo. The department is
StaffCentral's **`JP Category (All)`**. `Department (All)` is deprecated and only used to fill a blank category.

The rules live in `Client Propensity/config.py` and `Client Propensity/mi_pipeline/step2_merge.py`. The CSVs here are
**written by the pipeline on every full run** (`run_pipeline.py`), so they always show the groupings actually used.
Don't edit them by hand; change the settings below and rerun.

| File | What it is |
|---|---|
| `jp_category_merges.csv` | Tiny or duplicate JP Categories grouped before anything else |
| `jp_category_imputation_lookup.csv` | Every lookup used to fill a blank category: each JP Title, normalised Designation and old Department, the JP Category most of its staff have, that share, how many staff it rests on, and whether it is used |
| `departments.csv` | The departments that result (after merges and imputation), with staff counts |
| `department_sources.csv` | Where each staffer's department came from (given, imputed by which step, or Unknown) |
| `run_info.txt` | Run date, StaffCentral file and extract date, totals |

No staff or client data is stored here: only category, title, designation and department names, with counts.
Designations shared by fewer than 5 staff are left out of the lookup file, so one-off free-text titles stay out of git.

## The rules

**1. Department = JP Category.** Joined to each placement on CSID. StaffCentral is a snapshot: a person's current
category is assumed for all their past placements.

**2. Merge tiny or duplicate categories** (`JP_CATEGORY_MAP`):

| JP Category | Grouped into |
|---|---|
| Design & Multimedia | Creative, Design & Multimedia |
| Technical Support Services | IT Network Systems/Support |
| Ecommerce IT | Ecommerce |
| Coworker | blank (then imputed) |

**3. Fill a blank category**, in this order (`JP_IMPUTE_STEPS`). Each step learns from staff whose category is known,
and only fills what is still blank.

| Step | Lookup | Used when | Held-out accuracy | Filled (2026-11-12) |
|---|---|---|---|---|
| 1 | **JP Title** (exact) | always: the most common category for that title | 96% | 80 |
| 2 | **Designation**, normalised | at least 5 staff share it and at least 60% of them share one category | 91% | 4,821 |
| 3 | **Old Department** | at least 10 staff and at least 80% in one category | 92% | 210 |
| – | still blank | **Unknown**: left out of the department history | – | 4,101 |

Imputed rows are flagged in the pipeline (`role_group_source` = `JP Title (imputed)` / `Designation (imputed)` /
`Department (imputed)`, and `role_group_imputed` = 1).

**Designation normalisation** (`_norm_designation`, `DESIGNATION_DROP_WORDS`): lower case; remove "Level N" and Roman
numerals; remove seniority and training words (senior, sr, junior, jr, associate, lead, OJT, trainee, intern,
apprentice); keep letters, `&` and `/`. For example "Senior Technical Support II" → `technical support`, and
"Associate Accountant OJT" → `accountant`.

**Generic designations are never used** (`GENERIC_DESIGNATIONS`): Executive Services Specialist, For Executive
Services, Team Leader, ESS. They say nothing about the work. Staff with a known category and the designation
"Executive Services Specialist" split BPO Voice 31%, Virtual Assistant 16%, Back-Office 9% and many more.

**Old Departments that map cleanly** (step 3):

| Old Department | JP Category | Share |
|---|---|---|
| Freelance | Virtual Assistant | 97% |
| Finance | Accounting | 94% |
| Accounting Support Services | Accounting | 92% |
| Concierge, Drivers | Facilities Management | 100% |
| Facilities | Facilities Management | 87% |
| Talent Acquisition | Recruitment | 87% |
| Creative and Design Services | Creative, Design & Multimedia | 83% |
| Training and Professional Services | Training | 80% |

Not used, because they are mixed: Executive Services (BPO Voice 27%), Engineering (Architectural Design 32%), Marketing
(Marketing/Content 30%), Technical Support Services (IT Network Systems/Support 55%), Software Development (IT Software
Development 78%), Sales (Sales Professional 76%) and others. Mapping them would mislabel roughly the share not in the
main category.

## Coverage (2026-11-12, StaffCentral extract 2026-09-14)

* 45% of staff have no JP Category in StaffCentral, mostly disengaged staff hired before 2021. Currently engaged staff
  are 98% filled.
* After imputation: 80% of staff have a department (56% given, 24% imputed). 4,101 staff (20%) are Unknown.
* Client placements: 81% have a department (24% imputed). **Active** client placements: 97% (2% imputed).

**Why the Unknowns stay Unknown.** Almost all have a designation and an old department, but those don't point to one
category:

* about 2,400 have a generic designation *and* sit in Executive Services: nothing to go on;
* about 1,100 have a mixed designation (e.g. Technical Support: IT Network Systems/Support 48%, Back-Office the rest;
  Engineer: Architectural Design 40%) and a mixed department;
* the rest have a designation seen with too few staff, or never with a known category; about 170 have both fields blank.

Forcing these into a category would be wrong more often than right.

## Changing the groupings

| To | Change (in `Client Propensity/config.py`) |
|---|---|
| Merge or rename a JP Category | `JP_CATEGORY_MAP` (or `ROLE_GROUP_MAP` to merge after imputation) |
| Make a step stricter or looser, or drop one | `JP_IMPUTE_STEPS` (minimum staff, minimum share) |
| Treat another designation as generic | `GENERIC_DESIGNATIONS` |
| Ignore another word in designations | `DESIGNATION_DROP_WORDS` |

Rerun the pipeline, then check this folder's CSVs and the workbook's "Model checks" sheet.
