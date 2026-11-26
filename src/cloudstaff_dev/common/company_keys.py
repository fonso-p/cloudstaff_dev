"""
Company names, websites and register numbers: the one home for every normalisation rule used to match a company
across sources (Apollo, HubSpot, MyStaff, news, Companies House, CQC, Find a Tender, CVs).

Which key for which job
-----------------------
name_key(name)      'Smoke Alarms Australia Pty Ltd' -> 'smoke alarms'. Lower case, '&' -> 'and', punctuation and legal /
                    generic words dropped (Pty, Ltd, Group, Holdings, The, UK, Australia). For JOINING two name lists.
core_name(name)     'Orchard Medical Pty Ltd' -> 'Orchard Medical'. Keeps case and words; strips legal suffixes only. For
                    SEARCH QUERIES and display.
clean_name(name)    'MIRACL | The login you love' -> 'MIRACL'. Apollo's company-name noise (taglines, '(an X company)',
                    '- City', ALL CAPS). Run before either of the above on Apollo names.
root_domain(url)    'https://www.xero.com/au/' -> 'xero.com'. Use the domain whenever both sides have one: it beats any
                    name key.
ch_number(v)        Companies House number in its 8-character form ('123' -> '00000123', 'SC12345' -> 'SC012345').
split_renamed(...)  Apollo's 'Old Name Now New Name', split only when outside evidence backs it.

When NOT to use a name key
--------------------------
On its own for one-word names ("Athena", "Orchard"): too many unrelated companies share them. Require an exact key plus
another check (location, domain), as cloudstaff_dev.leads does.
"""
import re
from urllib.parse import urlparse

# ---------------------------------------------------------------- joining keys
LEGAL_WORDS = r"\b(pty|ltd|limited|llc|inc|plc|llp|corp|corporation|co|company|group|holdings|the|uk|australia|au|us|usa)\b"


def name_key(name) -> str:
    """Normalised company-name key ('' for blanks)."""
    if name is None:
        return ""
    s = str(name).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(LEGAL_WORDS, " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- search names, domains, text (was news_scraper/names.py)
LEGAL = re.compile(r"\b(pty|pte|ltd|limited|inc|incorporated|llc|llp|plc|corp|corporation|co|company|gmbh|ag|sa|nv|bv)\b\.?", re.I)
NUMBERED = re.compile(r"^\s*(a\.?\s?c\.?\s?n\.?\s*)?[\d\s]{5,}", re.I)     # "12768640 CANADA INC.", "A.C.N. 633 889 433 Pty Ltd"
ENGLISH = {"the", "and", "of", "to", "in", "a", "is", "for", "that", "on", "with", "as", "it", "its", "by", "was", "are", "has", "have", "from", "will", "this", "at", "be"}
ENGLISH_MIN_WORDS, ENGLISH_MIN_SHARE = 60, 0.08
# social and video posts are not news (Nepali cricket videos matched "Boundaryline")
SOCIAL = {"instagram", "facebook", "linkedin", "tiktok", "youtube", "x", "x.com", "twitter", "threads", "reddit", "pinterest"}


def core_name(name):
    """'Orchard Medical Pty Ltd' -> 'Orchard Medical'."""
    n = LEGAL.sub(" ", name.replace(",", " ").replace("&amp;", "&"))
    return re.sub(r"\s+", " ", n).strip(" .-") or name.strip()


def root_domain(domain):
    """'https://www.xero.com/au/' -> 'xero.com'."""
    if not domain:
        return ""
    d = domain.lower().strip()
    d = urlparse(d if "//" in d else "//" + d).netloc or d
    return d.removeprefix("www.").split(":")[0]


def name_pattern(term):
    """Case-insensitive whole-word pattern; search it against lowercased text."""
    return re.compile(r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])")


def not_english(text):
    """True when a long enough text has almost none of the commonest English words (checked on the first 3,000 characters)."""
    words = re.findall(r"[a-z']+", (text or "").lower()[:3000])
    return len(words) >= ENGLISH_MIN_WORDS and sum(w in ENGLISH for w in words) / len(words) < ENGLISH_MIN_SHARE


# ---------------------------------------------------------------- Apollo names
def clean_name(name):
    """'MIRACL | The login you love' -> 'MIRACL'; 'White Hat (an EPAM company)' -> 'White Hat';
    'Coxbench Hall Residential Care Home - Derby' -> 'Coxbench Hall Residential Care Home';
    'BLANEFIELD CARE LIMITED' -> 'Blanefield Care Limited' (one-word all-caps names such as CYJAX are kept)."""
    n = re.split(r"\s+\|\s+|\s+\(|\s+[-–]\s+", str(name).strip())[0].strip()
    if n.isupper() and len(n.split()) > 1:
        n = " ".join(w if len(w) <= 3 and not w.isalpha() else w.capitalize() for w in n.split())
    return n


# ---------------------------------------------------------------- register numbers
def ch_number(v):
    """Companies House number, 8 characters: digits zero-padded ('123' -> '00000123'; longer than 8 -> ''), and a
    two-letter prefix padded after the letters ('SC12345' -> 'SC012345'). Anything else is returned cleaned, as is."""
    v = re.sub(r"[^A-Za-z0-9]", "", str(v or "")).upper()
    if v.isdigit():
        return v.zfill(8) if len(v) <= 8 else ""
    m = re.match(r"^([A-Z]{2})(\d{1,6})$", v)
    return m.group(1) + m.group(2).zfill(6) if m else v


# ---------------------------------------------------------------- renamed companies: "Old Name Now New Name"
# Apollo sometimes stores a rebrand in the company name itself: "Monarch Healthcare Now RDCP Care". Splitting on "Now"
# alone is unsafe ("Here and Now Care", "Care Now Ltd"), so a split is only made when outside evidence (the website,
# the contacts' email domains, the LinkedIn page, or another account in the same list) points to one of the two parts.
RENAMED = re.compile(r"[\s,(]+(now\s+part\s+of|now\s+known\s+as|now|formerly)\s+", re.I)


def _squash(s) -> str:
    return name_key(s).replace(" ", "")


def _labels(evidence) -> set:
    """Website / email domains -> their first label ('monarchhealthcare.co.uk' -> 'monarchhealthcare');
    a LinkedIn company URL -> its slug ('linkedin.com/company/monarchhealthcareuk' -> 'monarchhealthcareuk')."""
    out = set()
    for e in evidence or ():
        e = str(e or "").strip().lower()
        if not e or e == "nan":
            continue
        m = re.search(r"linkedin\.com/company/([^/?#]+)", e)
        if m:
            out.add(re.sub(r"[^a-z0-9]", "", m.group(1)))
            continue
        host = re.sub(r"^[a-z]+://", "", e).split("@")[-1].split("/")[0].split("?")[0]
        host = re.sub(r"^www\.", "", host)
        if host:
            out.add(re.sub(r"[^a-z0-9]", "", host.split(".")[0]))
    return {x for x in out if len(x) >= 4}


def _named_by(name, labels) -> bool:
    """A label starts with the squashed name or the name starts with the label ('monarchhealthcareuk' starts with
    'monarchhealthcare'). Prefix, not 'anywhere in': a short part such as 'Care' must not match 'nowcare.co.uk'."""
    k = _squash(name)
    return len(k) >= 4 and any(lab.startswith(k) or k.startswith(lab) for lab in labels)


def split_renamed(name, evidence=(), others=()):
    """Read 'Old Name Now New Name' (also 'now known as', 'now part of', 'New Name formerly Old Name').

    name      the company name as Apollo has it (after the usual cleaning)
    evidence  website, email domains, LinkedIn company URL of this account
    others    (name, website) of the OTHER accounts in the same export, to spot the new name already being a lead

    Returns None when the name has no such phrase, or when the whole name is the website's own ('herenowcare.co.uk').
    Otherwise a dict:
      name         the name to search and show: the new name for a rename, the company itself for 'now part of'
      former_name  the old name (rename only)
      parent       the group it is now part of ('now part of' only)
      same_as      name of another account in the list that is the same business, else ''
      basis        why, in words, for the page and the QA sheet
      check        True when no evidence supports a split: the name is left unchanged for a person to look at
    """
    name = str(name or "").strip()
    m = RENAMED.search(name)
    if not m:
        return None
    left, right = name[:m.start()].strip(" ,(-"), name[m.end():].strip(" ,)-")
    if not name_key(left) or not name_key(right):      # 'Care Now Ltd', 'Now Healthcare': not a rename
        return None
    labels = _labels(evidence)
    if any(_squash(name) in lab for lab in labels):     # the website spells the whole name, "now" included
        return None
    word = re.sub(r"\s+", " ", m.group(1).lower())
    if word == "now part of":
        return {"name": left, "former_name": "", "parent": right, "same_as": "", "check": False,
                "basis": f"Apollo name says it is now part of {right}"}
    old, new = (right, left) if word == "formerly" else (left, right)
    on_old, on_new = _named_by(old, labels), _named_by(new, labels)
    same = next((n for n, w in others if name_key(n) and (name_key(n) == name_key(new) or _named_by(new, _labels([w])))), "")
    if not (on_old or on_new or same):
        return {"name": name, "former_name": "", "parent": "", "same_as": "", "check": True,
                "basis": f"name contains '{m.group(1)}', but its website, email and LinkedIn match neither "
                         f"'{old}' nor '{new}': left unchanged, check by hand"}
    if on_new:
        basis = f"renamed from {old}; website matches {new}"
    elif on_old:
        basis = f"renamed from {old}; Apollo's website is still the old name's"
    else:
        basis = f"renamed from {old}; {new} is another account in this list"
    if same:
        basis += f"; same business as the {same} lead"
    return {"name": new, "former_name": old, "parent": "", "same_as": same, "check": False, "basis": basis}
