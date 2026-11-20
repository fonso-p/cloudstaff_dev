"""
Company-name keys for matching the same company across sources that have no shared id or website.

What it does
------------
`name_key("Smoke Alarms Australia Pty Ltd")` -> "smoke alarms": lower case, "&" -> "and", punctuation removed, and
legal / generic words dropped (Pty, Ltd, Inc, Group, Holdings, The, and country words such as UK or Australia), so
spellings of one company collapse to one key.

When to use it
--------------
- Joining a list of names to another list of names: candidates' CV employers (Client Extraction) to Apollo leads or
  HubSpot companies.
- Use the website domain when both sides have one; it beats any name key.

When NOT to use it
------------------
- On its own for one-word names ("Athena", "Orchard"): too many unrelated companies share them. Require an exact
  key plus another check (location, domain), as `Marketing Intelligence/apollo_lead_grading/grade_leads.py` does.
"""
import re

LEGAL_WORDS = r"\b(pty|ltd|limited|llc|inc|plc|llp|corp|corporation|co|company|group|holdings|the|uk|australia|au|us|usa)\b"


def name_key(name) -> str:
    """Normalised company-name key ('' for blanks)."""
    if name is None:
        return ""
    s = str(name).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(LEGAL_WORDS, " ", s)
    return re.sub(r"\s+", " ", s).strip()
