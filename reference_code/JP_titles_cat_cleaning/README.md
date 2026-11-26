# shared

Reusable analysis code that more than one project or ad hoc notebook can use.
Since 26 Nov 2026 the modules live in the installed package `cloudstaff_dev.common` (`src/cloudstaff_dev/common/`);
the files here only re-export them, so older notebooks that import them by path keep working.
Each module's docstring at the top explains what it does, when to use it and how.

| Module | What it's for | Used in |
|---|---|---|
| `cloudstaff_dev.common.jp_titles` (`src/cloudstaff_dev/common/jp_titles.py`; [jp_titles.py](jp_titles.py) here is a re-export) | Cleans Staff Central JP titles by removing seniority words (Senior/Junior, Level 2, II, ...) and fixing known typos. It also backfills blank `JP Title (All)` / `JP Category (All)` values from `Designation (All)` using a strict rule: when the evidence is ambiguous, it leaves the field blank instead of guessing. | `Adhoc/Top roles APAC/top_roles_APAC.ipynb`, `src/cloudstaff_dev/common/roles.py` (lead grading) |
| `cloudstaff_dev.common.company_keys` (`src/cloudstaff_dev/common/company_keys.py`; `reference_code/company_keys.py` is a re-export) | `name_key()`: one normalised key per company name (lower case, "&" = "and", punctuation and legal / generic words such as Pty Ltd, Inc, Group, UK removed), for joining name lists that share no id or website. Not enough on its own for one-word names. Merged with the news scraper's `names.py` on 26 Nov 2026, so it also has `core_name`, `root_domain`, `clean_name`, `ch_number` and `split_renamed`. | `Client Extraction (CS Jobs)/export_client_map.py`, lead grading (`cloudstaff_dev.leads`), the news scraper (`cloudstaff_dev.signals`) |

## Importing from a notebook or script

`cloudstaff_dev` is installed (editable) in the repo's `.venv`, so with that environment as the kernel or interpreter
no import-path setup is needed, from any folder:

```python
from cloudstaff_dev.common.jp_titles import backfill_jp, strip_title
from cloudstaff_dev.common.company_keys import name_key
```

## Adding a module

- Put generic, reusable logic in `src/cloudstaff_dev/common/`. Keep project-specific config (file paths, thresholds,
  vertical lists) in the project itself; shared folder locations go in `cloudstaff_dev.common.paths`.
- Start the file with a docstring that covers what it does, when to use it, when not to,
  the input it expects, and a usage example.
- Add a row to the table above, including where the module is used.
