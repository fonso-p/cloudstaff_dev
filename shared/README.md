# shared

Reusable analysis code that more than one project or ad hoc notebook can use.
Each file is a standalone module, and its docstring at the top explains what it does,
when to use it and how.

| Module | What it's for | Used in |
|---|---|---|
| [jp_titles.py](jp_titles.py) | Cleans Staff Central JP titles by removing seniority words (Senior/Junior, Level 2, II, ...) and fixing known typos. It also backfills blank `JP Title (All)` / `JP Category (All)` values from `Designation (All)` using a strict rule: when the evidence is ambiguous, it leaves the field blank instead of guessing. | `Adhoc/Top roles APAC/top_roles_APAC.ipynb`, `Marketing Intelligence/apollo_lead_grading/roles.py` |
| [company_keys.py](company_keys.py) | `name_key()`: one normalised key per company name (lower case, "&" = "and", punctuation and legal / generic words such as Pty Ltd, Inc, Group, UK removed), for joining name lists that share no id or website. Not enough on its own for one-word names. | `Client Extraction (CS Jobs)/export_client_map.py`, `Marketing Intelligence/apollo_lead_grading/grade_leads.py` |

## Importing from a notebook or script

`shared/` is not an installed package. Add it to the import path first. This snippet
works from any folder inside the repo:

```python
import sys
from pathlib import Path

REPO_ROOT = next(p for p in [Path.cwd().resolve(), *Path.cwd().resolve().parents] if (p / "shared").is_dir())
sys.path.insert(0, str(REPO_ROOT / "shared"))

from jp_titles import backfill_jp, strip_title
```

## Adding a module

- Put generic, reusable logic here. Keep project-specific config (file paths, thresholds,
  vertical lists) in the project itself.
- Start the file with a docstring that covers what it does, when to use it, when not to,
  the input it expects, and a usage example.
- Add a row to the table above, including where the module is used.
