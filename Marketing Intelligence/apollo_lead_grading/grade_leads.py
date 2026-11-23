"""Lead grading: Apollo leads -> Priority Score (live profile, New Logo) + gates + reasons -> xlsx and dashboard JSON.

Reads (all local except the code it imports):
  Apollo export(s)            <DATA_DIR>/EMEA/*.csv                    what we HAVE (firmographics, funding label, contacts)
  News Scraper results        News Scraper/apollo_emea/out/*.csv       what we GATHER (news, jobs, filings)
  Industry trend              News Scraper/out/industry_trend.csv      what we gather about the segment
  Priority list (identity)    <DATA_DIR>/priority_company_info_combined*.xlsx   INTERNAL: MyStaff clients, HubSpot prospects
  Client Propensity profiles  <DATA_DIR>/*_Propensity_Extract_prospect_profiles.csv   INTERNAL: how clients like this grow
Scores with ../format data/priority_scoring.py (the same code as the Priority Score notebook).
Writes to <DATA_DIR>: lead_grades_<name>.xlsx and lead_grades_<name>.json (the page's data). Rules: README.md.

Usage, from the Marketing Intelligence folder:
  ../.venv/Scripts/python.exe apollo_lead_grading/grade_leads.py [--name apollo_emea]
"""
import argparse
import datetime as dt
import glob
import json
import math
import os
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "format data"))
sys.path.insert(0, str(REPO / "references" / "mystaff_industry"))
sys.path.insert(0, str(REPO / "shared"))                  # old home of the helpers (before 20 Nov), kept as a fallback
sys.path.insert(0, str(REPO / "reference_code"))
from company_keys import name_key, split_renamed                                                          # noqa: E402
from priority_scoring import FIT, SCORING_DASHBOARD_V3, NEWS_STRENGTH, RECENCY, _recency, percentile_tier, score_accounts   # noqa: E402
from mystaff_industry import INDUSTRY_GROUPS, INDUSTRY_SECTOR                              # noqa: E402

# ---------------------------------------------------------------- settings (rules as data; README.md §4 explains each)
DATA_DIR = Path.home() / "Desktop" / "Projects" / "Marketing Intelligence Priority" / "Data"
APOLLO_DIR = DATA_DIR / "EMEA"
SCRAPER_OUT = REPO / "News Scraper" / "apollo_emea" / "out"
TREND_FILE = REPO / "News Scraper" / "out" / "industry_trend.csv"
TREND_IN_SCORE = False                             # decision 2026-11-18: industry trend is context only (see add_trend)
PROFILE_KINDS = {"service", "pitch", "info"}       # chips that describe the company: shown in its profile, not in Why
# The live Priority Score profile (dashboard_v3), New Logo, without the parts that need HubSpot (decision 2026-11-18: these
# leads are pre-HubSpot, so there is no website activity and no Diamond referral). Their 40 points are shared out in the
# live profile's own proportions: news & hiring 30 -> 50 (25 + 25), Competitor client 10 -> 17, Fit 20 -> 33.
# Two event types added 18 Nov 2026 (requested; News Scraper classifies them since then). Strengths are a first guess to
# tune: a won contract or partnership ranks with restructuring (0.5), a product launch with a leadership change (0.3).
NEW_EVENT_STRENGTH = {"Contract / partnership win": 0.5, "Product launch": 0.3}
SCORING = {**SCORING_DASHBOARD_V3,
           "max_points": {**SCORING_DASHBOARD_V3["max_points"],
                          "New Logo": {"web": 0, "news": 50, "diamond": 0, "bpo": 17, "seat": 0, "fit": 33}},
           "news_strength_extra": NEW_EVENT_STRENGTH}
assert sum(SCORING["max_points"]["New Logo"].values()) == 100
STRENGTH = {**NEWS_STRENGTH, **NEW_EVENT_STRENGTH}
GOAL = "New Logo"
TEAM = "BDM Marketing"                             # decision 2026-11-18: one list, no SDR / BDM / Marketing split yet
FIT_COUNTRY = "Unknown"                            # decision 2026-11-18: only 26 UK clients (2 Healthcare, 2 Technology), too
                                                   # few for a UK fit, so use the industry-only profile (all countries)
NEWS_EVENTS = ["Funding round", "PE buyout", "M&A", "Expansion / new office", "Restructuring", "Leadership change"] + list(NEW_EVENT_STRENGTH)
# Registers (collected by News Scraper/apollo_emea/cqc.py and contracts.py, added 20 Nov): dated facts, counted at full
# strength like hand-labelled events. CQC registered-manager changes are shown but not scored: turnover at one home is
# common, and a scored Leadership change would trigger Act now.
REGISTER_FILES = {"CQC register": SCRAPER_OUT / "cqc_events.csv", "Find a Tender": SCRAPER_OUT / "contract_awards.csv"}
REGISTER_SCORED = {"M&A", "Expansion / new office", "Contract / partnership win"}
CQC_PROVIDERS, CQC_LOCATIONS = SCRAPER_OUT / "cqc_providers.csv", SCRAPER_OUT / "cqc_locations.csv"
# Ownership (News Scraper/apollo_emea/ownership.py, Companies House PSC register): a flag, never points. BDM feedback
# 23 Nov 2026: companies not owned by a parent, an umbrella group or an investor, and not run on public money, have
# fewer layers of sign-off and buy faster. "Owner-managed" is that target.
OWNERSHIP = SCRAPER_OUT / "ownership.csv"
OWNERSHIP_ORDER = ["Owner-managed", "Owner-managed group", "Part of a corporate group", "Investor-backed",
                   "Charity / not-for-profit", "Public body", "Unknown", "Not checked"]
OWNERSHIP_PRIVATE = {"Owner-managed", "Owner-managed group"}
OWNERSHIP_EVENT_DAYS = 730                         # a PE buyout in the news this recent overrides an older register filing
# Sub-sector: what kind of business, from CQC's service types when the lead is in the CQC register (care, England),
# else from its activity codes (Apollo US SIC 4-digit, NAICS 4-digit, Companies House UK SIC prefixes).
# Descriptive: no points. A lead can have several.
SUBSECTORS = {
    "UK care homes": {
        "Nursing homes":            {"cqc": r"Care home service with nursing", "sic": {"8051"}, "naics": {"6231"}, "uk": {"871"}},
        "Residential care":         {"cqc": r"Care home service without nursing", "sic": {"8361", "8059", "8052"}, "naics": {"6233"}, "uk": {"873"}},
        "Learning disability / mental health": {"cqc": r"learning disability|mental health|Supported living|Shared Lives",
                                     "sic": set(), "naics": {"6232"}, "uk": {"872"}},
        "Home care":                {"cqc": r"Domiciliary care service|Extra Care housing", "sic": {"8082"}, "naics": {"6216"}, "uk": {"881"}},
        "Care staffing agency":     {"cqc": r"Nurses Agency", "sic": {"7361", "7363"}, "naics": {"5613"}, "uk": {"78"}},
    },
    "UK cybersecurity": {
        "Cyber services / consultancy": {"sic": {"7371", "7373", "7379", "8742"}, "naics": {"5415", "5416"}, "uk": {"62020", "62090"}},
        "Software product":         {"sic": {"7372"}, "naics": {"5112", "5132"}, "uk": {"58290", "62012"}},
        "Managed / hosted services": {"sic": {"7374"}, "naics": {"5182"}, "uk": {"63110"}},
        "Training":                 {"sic": {"8243"}, "naics": {"6114", "6115"}, "uk": {"8559"}},
    },
}
# back-office work each kind of business typically has: a first draft for BDM Marketing to correct, shown as pitch hints
SUBSECTOR_PITCH = {
    "Nursing homes": "rostering and agency-shift admin, payroll, care-fee and NHS funded-nursing invoicing",
    "Residential care": "care-fee and council-funding invoicing, payroll, recruitment admin, compliance paperwork",
    "Learning disability / mental health": "rotas, support-plan and compliance admin, council billing, payroll",
    "Home care": "rostering and visit scheduling, call-monitoring checks, payroll and mileage, recruitment and onboarding",
    "Care staffing agency": "candidate compliance and vetting checks, shift booking, timesheets and payroll",
    "Cyber services / consultancy": "SOC triage, GRC and compliance documentation, project coordination, bid support",
    "Software product": "developers and QA, customer support, technical writing, customer success",
    "Managed / hosted services": "service desk, monitoring, billing",
    "Training": "course admin, content production, sales support",
}
# Events a person (or Claude) labelled by hand that the classifier missed: they count like news when stronger than the
# lead's own; labelled_by is shown on the page. Columns: company_name, date, category, headline, url, publisher, labelled_by,
# labelled_on, note
MANUAL_EVENTS = HERE / "manual_events.csv"
CONFIDENCE_FACTOR = {"high": 1.0, "reviewed": 1.0, "medium": 0.5, "low": 0.5}   # decision D2: medium / low events at half strength
# Register matches made on an exact name alone (CQC provider name, contract supplier name) are medium reliability: flagged
# "check match" until a person marks them in REGISTER_REVIEWS (confirmed: flag cleared; rejected: the match is dropped).
# Columns: company_name, source (CQC | Find a Tender), notice (Find a Tender notice id; blank for CQC), verdict, reviewed_by,
# reviewed_on, note. A flagged match still scores until rejected.
REGISTER_REVIEWS = HERE / "register_match_reviews.csv"
EVENT_OVERRIDES = HERE / "event_overrides.csv"     # a person's correction of an event's category, keyed on company + headline
OWN_SITE_SOURCE = "newsroom"                       # the scraper's source name for the company's own website / blog
OTHER_NEWS_POINTS = False                          # decision 2026-11-18: "Other / Unclassified" news earns no points for leads
# Apollo "Latest Funding" label -> the news event types that would be the same event (strict: Debt Financing is not a buyout)
APOLLO_CONFIRMS = {"Seed": ["Funding round"], "Angel": ["Funding round"], "Series A": ["Funding round"], "Series B": ["Funding round"],
                   "Series C": ["Funding round"], "Series D": ["Funding round"], "Venture (Round not Specified)": ["Funding round"],
                   "Debt Financing": ["Funding round"], "Private Equity": ["PE buyout"], "Merger / Acquisition": ["M&A", "PE buyout"],
                   "Other": ["Funding round", "PE buyout", "M&A"]}
# decision 2026-11-18: a company's own blog posts earn no news points unless the post is a relevant event (NEWS_EVENTS)
# Several events add up (user, 20 Nov 2026: "multiple events is a strong indicator"). A lead's items (news, own site,
# hand-labelled, CQC, contracts, its parent's event) are grouped into distinct events: same type within EVENT_WINDOW_DAYS
# = one event (one deal reported by three outlets and CQC is one event). Each event's value is strength x confidence x
# recency; they combine as 1 - (1-a)(1-b)...: one event scores as before, each extra one adds part of what is left, never
# above the news maximum. Act now still keys off the single strongest event.
COMPOUND_EVENTS = True
EVENT_WINDOW_DAYS = 30
PARENT_FACTOR = 0.5                                # decision 2026-11-18: a parent's event counts, at half strength, when it beats
                                                   # the lead's own news; marked "Parent" wherever it shows
JOBS_DB = REPO / "News Scraper" / "apollo_emea" / "data" / "news.db"   # read-only: per-role posted dates, for job recency
HIRING_BANDS = [(1, "1–2"), (3, "3–5"), (6, "6–10"), (11, "11–20"), (21, "21+")]   # open roles (from) -> band, shown as a reason
# Roles we fill (roles.py): posted job titles matched to Staff Central's JP titles. Decision 2026-11-18: hiring points count
# only roles Cloudstaff fills; on-site roles (carers, nurses, cooks...) still show in the hiring chip as context
STAFF_REPORT_GLOB = "Desktop/Projects/Data/**/Staff Report with Details*.xlsx"   # newest is used; only JP Title / Category read
HIRING_SCORE = "roles_we_fill"                     # "roles_we_fill" or "all" (every open role, the main pipeline's rule)
# Service lines from the company's website card (description, title, keywords): for targeting and the pitch, no points
SERVICE_LINES = {
    "UK care homes": {
        "Residential care": r"residential care|care home", "Nursing care": r"nursing (care|home)", "Dementia care": r"dementia",
        "Home care": r"home care|domiciliary|homecare|care at home", "Live-in care": r"live[- ]in care", "Supported living": r"supported living",
        "Learning disability / autism": r"learning disabilit|autis", "Mental health": r"mental health", "Children's services": r"child(ren)?'?s? (care|home|service)",
        "Retirement living": r"retirement (living|village|communit)|later living", "Complex care": r"complex care", "End of life": r"end of life|palliative",
        "Respite": r"respite"},
    "UK cybersecurity": {
        "Penetration testing": r"penetration test|pen ?test|red team|ethical hack", "SOC / MDR": r"\bsoc\b|security operations|mdr\b|managed detection|siem",
        "Managed security (MSSP)": r"managed (security|service)|mssp", "GRC / compliance": r"complian|iso ?27001|cyber essentials|governance|\bgrc\b|nis2|dora\b",
        "Identity & access": r"identity|access control|authori[sz]ation|authentication|\biam\b|passwordless|login", "Data security": r"data (security|protection|loss)|dspm|\bdlp\b|encrypt",
        "Threat intelligence": r"threat intel|dark web|threat landscape", "OT / maritime security": r"\bot\b security|operational technology|maritime|industrial control|\bics\b",
        "Human risk / awareness": r"human risk|awareness|behaviou?r|phishing simulation", "Cloud security": r"cloud security|cspm|cloud posture",
        "App / API security": r"api (security|attack|protection)|app(lication)? security|mobile app", "Risk analytics / insurance": r"insur|risk analytic|cyber risk",
        "Forensics / incident response": r"forensic|incident response|\bdfir\b", "Cryptography / post-quantum": r"post[- ]quantum|cryptograph|quantum"},
}
TIER_GROUP = "lead_list"                           # decision 2026-11-18: tiers are ranked within each Apollo list (separate campaigns)
DUPLICATE = "Duplicate"                            # an Apollo account renamed to another lead in the same list ("X Now Y")
CHECK_FIT = "Check fit"                            # leads outside the list's target industry (builders, furniture, investors in
                                                   # the care list): scored, but not tiered against the campaign's own targets
DISTRESS = r"administration|liquidation|strike|dissolved|insolvency|receivership"
LIST_TARGET = {                                    # Apollo list (substring, lower case) -> short name, intended industry groups
    "care home": ("UK care homes", {"Healthcare & Wellness"}),
    "cyber": ("UK cybersecurity", {"Technology"}),
}
# Activity codes that mean "the list's target business" (first 4 digits of US SIC / NAICS, first 2 of UK SIC 2007)
TARGET_CODES = {
    "UK care homes": {"sic": {"8051", "8052", "8059", "8361", "8082"},            # nursing / residential care, home health
                      "naics": {"6231", "6232", "6233", "6239", "6216", "6241"},  # nursing & residential care, home health, elderly
                      "uk": {"87", "88"}},                                         # residential care; social work without accommodation
    "UK cybersecurity": {"sic": {"7371", "7372", "7373", "7374", "7375", "7379"},  # programming, software, IT and information services
                         "naics": {"5415", "5182", "5112", "5132", "5192"},
                         "uk": {"62", "63"}},                                       # IT services, information services
}
# UK SIC that point to another trade. STRONG (furniture, building) always wins. WEAK codes are also how care groups and
# consultancies register their holding company (70100 head offices, 68209 property, 74990 non-trading, 70229 consulting,
# 71122 engineering, 78xxx staffing), so they decide only when there is no other evidence (18 Nov: ASHA Healthcare, Priority
# Care Group, Lab 1 and others are registered that way)
OTHER_TRADE_UK_STRONG = {"31", "41", "42", "43"}
# Apollo industry groups that, for these lists, mean a supplier (builders, architects, designers, agencies, investors): their
# websites mention care because they sell to care homes, so the website alone can't put them in the target
SUPPLIER_GROUPS = {"Construction & Engineering", "Professional Services", "Retail & Consumer Goods", "Manufacturing & Industrial",
                   "Real Estate", "Marketing, Media & Creative", "Hospitality, Travel & Leisure"}
OTHER_TRADE_UK_WEAK = {"68", "70", "71", "74", "78"}
LIST_TARGET_GROUPS = {name: groups for name, groups in LIST_TARGET.values()}
# Competitor client (17 points): candidates' CVs name the lead as a competitor's client. Map from
# "Client Extraction (CS Jobs)/export_client_map.py"; company names only
COMPETITOR_MAP = Path.home() / "Desktop" / "Projects" / "Competitor Analysis (client scrape)" / "data" / "competitor_clients.csv"
COMPETITOR_FUZZY = 0.95                           # close-name matches: shown for a person to check, no points
COUNTRY_WORDS = {"UK": "kingdom", "AU": "austral", "US": "united states", "NZ": "zealand", "CA": "canada", "IE": "ireland"}
BAND_EDGES = [(10, "1-10"), (50, "11-50"), (200, "51-200"), (500, "201-500"), (math.inf, "500+")]
COUNTRY_CODE = {"united kingdom": "UK", "ireland": "IE", "australia": "AU", "new zealand": "NZ", "united states": "US", "canada": "CA"}
SENIORITY_ORDER = ["owner", "founder", "c suite", "partner", "vp", "head", "director", "manager", "senior", "entry"]
DECISION_MAKER = {"owner", "founder", "c suite", "partner", "vp", "director"}
TECH = {   # Apollo technology -> pitch chip (no points: a conversation opener, not intent)
    "Support / sales-ops team": r"\b(zendesk|intercom|freshdesk|help ?scout|zoho desk)\b",
    "CRM in use": r"\b(hubspot|salesforce|zoho crm|pipedrive|dynamics 365)\b",
    "In-house finance admin": r"\b(sage|xero|quickbooks|zoho books|netsuite)\b",
    "Hires through a job system": r"\b(greenhouse|lever|ashby|workable|smartrecruiters|bamboohr|recruitee|personio|teamtailor|workday|ukg|zoho recruit|jobvite|icims)\b",
}
LEGAL = r"\b(limited|ltd\.?|plc|llp|llc|inc\.?)$"


# ---------------------------------------------------------------- helpers
def newest(pattern):
    files = sorted(glob.glob(str(DATA_DIR / pattern)))
    return Path(files[-1]) if files else None


def domain(u):
    if not isinstance(u, str) or not u.strip():
        return ""
    u = re.sub(r"^[a-z]+://", "", u.strip().lower())
    return re.sub(r"^www\.", "", u.split("/")[0].split("?")[0].split(":")[0])


def clean_name(name):   # same rule as News Scraper/apollo_emea/prepare.py
    n = re.split(r"\s+\|\s+|\s+\(|\s+[-–]\s+", str(name).strip())[0].strip()
    if n.isupper() and len(n.split()) > 1:
        n = " ".join(w if len(w) <= 3 and not w.isalpha() else w.capitalize() for w in n.split())
    return n


_norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower().replace("&", "and"))   # 'nonprofit' = 'Non-Profit', '&' = 'and'
_INDUSTRY = {_norm(v): g for g, vs in INDUSTRY_GROUPS.items() for v in vs}


def industry_group(apollo_industry):
    """Apollo uses LinkedIn's lower-case names ('hospital & health care'); HubSpot's are 'Hospital & Health Care'."""
    return _INDUSTRY.get(_norm(apollo_industry)) if isinstance(apollo_industry, str) else None


def band(n):
    return None if pd.isna(n) or n <= 0 else next(lbl for hi, lbl in BAND_EDGES if n <= hi)


def blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or v == ""


def jsonable(v):
    if blank(v) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if hasattr(v, "item"):
        return v.item()
    return v


# ---------------------------------------------------------------- 1. extract + standardise Apollo
def extract_apollo(folder):
    files = sorted(glob.glob(str(folder / "*.csv")))
    frames = [pd.read_csv(f, dtype=str, encoding="utf-8-sig", encoding_errors="replace").assign(_file=os.path.basename(f)) for f in files]
    return pd.concat(frames, ignore_index=True), files


def standardise(c):
    c = c.copy()
    c["account_id"] = "AP-" + c["Apollo Account Id"]
    leads = []
    firsts = c.groupby("account_id", sort=False).first()
    others = {a: (clean_name(x["Company Name"]), x.get("Website")) for a, x in firsts.iterrows()}
    for acc, g in c.groupby("account_id", sort=False):
        r = g.iloc[0]
        # "Monarch Healthcare Now RDCP Care": same rule as the scraper's prepare.py (reference_code/company_keys.py)
        rn = split_renamed(clean_name(r["Company Name"]), [r.get("Website"), r.get("Company Linkedin Url")] + g["Email"].dropna().tolist(),
                           [v for k, v in others.items() if k != acc]) or {}
        same_as = next((k for k, v in others.items() if k != acc and rn.get("same_as") and v[0] == rn["same_as"]), None)
        shown = (f"{rn['name']} (was {rn['former_name']})" if rn.get("former_name") else rn.get("name")) or clean_name(r["Company Name"])
        lst = str(r.get("Lists", ""))
        list_name, targets = next(((n, t) for k, (n, t) in LIST_TARGET.items() if k in lst.lower()), (lst, set()))
        emp = pd.to_numeric(r.get("# Employees"), errors="coerce")
        grp = industry_group(r.get("Industry"))
        email_doms = g["Email"].dropna().str.split("@").str[-1].str.lower()
        tech = str(r.get("Technologies") or "")
        leads.append({
            "account_id": acc, "company_name": shown, "goal": GOAL,
            "former_name": rn.get("former_name") or None, "name_note": rn.get("basis"), "name_check": bool(rn.get("check")),
            "duplicate_of": same_as, "duplicate_of_name": rn.get("same_as") or None,
            "industry": grp, "employee_band": band(emp), "region": COUNTRY_CODE.get(str(r.get("Company Country", "")).lower(), "Other"),
            "lead_list": list_name, "list_target": ", ".join(sorted(targets)),
            "industry_raw": r.get("Industry"), "industry_sector": INDUSTRY_SECTOR.get(grp) if grp else None,
            "employee_count": None if pd.isna(emp) else int(emp), "city": r.get("Company City"),
            "website_domain": domain(r.get("Website")) or (email_doms.mode().iloc[0] if len(email_doms) else ""),
            "email_domain": email_doms.mode().iloc[0] if len(email_doms) else "",
            "annual_revenue": pd.to_numeric(r.get("Annual Revenue"), errors="coerce"),
            "apollo_latest_funding": r.get("Latest Funding"), "parent_company": r.get("Parent company (Apollo data)"),
            "pitch": "; ".join(k for k, rx in TECH.items() if re.search(rx, tech, re.I)),
            "company_linkedin": r.get("Company Linkedin Url"), "apollo_name": r["Company Name"],
            "_on_target": (grp in targets) if targets else None,   # first view, from Apollo's industry only; target_check() decides
            "sic_us": r.get("SIC Codes"), "naics": r.get("NAICS Codes"),
        })
    contacts = pd.DataFrame({
        "account_id": c["account_id"], "name": (c["First Name"].fillna("") + " " + c["Last Name"].fillna("")).str.strip(),
        "title": c["Title"], "seniority": c["Seniority"], "email": c["Email"], "email_status": c["Email Status"],
        "linkedin": c["Person Linkedin Url"], "country": c["Country"],
    })
    contacts["_rank"] = contacts["seniority"].str.lower().map({s: i for i, s in enumerate(SENIORITY_ORDER)}).fillna(99)
    contacts = contacts.sort_values(["account_id", "_rank", "name"]).drop(columns="_rank")
    return pd.DataFrame(leads), contacts


# ---------------------------------------------------------------- 2. internal data: clients, HubSpot prospects, fit
def match_internal(leads, path):
    if path is None:
        leads["internal_match"] = None
        return leads, "no priority list found"
    pl = pd.read_excel(path, sheet_name="priority_list", usecols=["account_id", "company_name", "goal", "website_domain", "source"])
    pl = pl[pl["website_domain"].fillna("") != ""]
    by_dom = pl.groupby("website_domain").first()
    def m(r):
        for d in {r["website_domain"], r["email_domain"]} - {""}:
            if d in by_dom.index:
                x = by_dom.loc[d]
                return f"{'Existing client' if x['goal'] == 'Organic Growth' else 'In HubSpot'}: {x['company_name']} ({x.name})"
        return None
    leads["internal_match"] = leads.apply(m, axis=1)
    return leads, f"{path.name}: {len(pl)} accounts with a website ({(pl.goal == 'Organic Growth').sum()} clients)"


def add_fit(leads, path):
    cols = ["fit_growth_p", "fit_growth_band", "fit_reach_10_p", "fit_reach_10_band", "fit_branch_1y_p", "fit_branch_1y_band", "likely_first_new_dept"]
    if path is None:
        for k in cols:
            leads[k] = None
        return leads, "no prospect profiles found"
    pp = pd.read_csv(path).set_index("profile_key")
    leads["fit_profile"] = leads["industry"].fillna("Unknown") + "|" + FIT_COUNTRY
    for k in cols:
        leads[k] = leads["fit_profile"].map(pp[k])
    leads["fit_outlook"] = leads["fit_profile"].map(pp["outlook"]) if "outlook" in pp else None
    # the usual rate of each score (Client Propensity's score definitions): a fit chip needs High AND >= FIT_CHIP_LIFT x usual
    defs = sorted(glob.glob(str(path).replace("_prospect_profiles.csv", "_score_definitions.csv")))
    base = pd.read_csv(defs[-1]).set_index("score")["base_rate"].to_dict() if defs else {}
    for s in ("fit_growth", "fit_reach_10", "fit_branch_1y"):
        leads[f"{s}_usual"] = base.get(s)
    return leads, path.name


def add_trend(leads, path):
    if not path.exists():
        leads["industry_trend"] = None
        return leads, "no industry_trend.csv"
    t = pd.read_csv(path, encoding="utf-8-sig")
    by = {(r.industry_group, r.country): r.industry_trend for r in t.itertuples()}
    def tr(r):
        if not r["industry"]:
            return None, "unknown industry"
        for ctry, why in ((r["region"], f"{r['industry']} × {r['region']}"), ("ALL", f"{r['industry']}, all countries")):
            if (r["industry"], ctry) in by:
                return by[(r["industry"], ctry)], why
        return None, "segment not run"
    leads[["market_trend", "trend_basis"]] = leads.apply(lambda r: pd.Series(tr(r)), axis=1)
    # decision 2026-11-18: not in the score. Tiers rank within each list, where every lead shares the same trend, so the
    # multiplier could only blur scores, never reorder them. Kept as market context (market_trend) on the Fit page.
    leads["industry_trend"] = leads["market_trend"] if TREND_IN_SCORE else None
    return leads, path.name


# ---------------------------------------------------------------- 3. gathered: news, jobs, filings (News Scraper)
def _strength(news, factor, d, as_of):
    """Strength x recency of one news signal (what the score uses), for choosing between the lead's and its parent's."""
    if news not in STRENGTH or news == "None" or pd.isna(d):
        return 0.0
    return STRENGTH[news] * factor * _recency((as_of - d).days)


def compound_events(leads, ev, as_of):
    """Distinct events per lead and their combined value (see COMPOUND_EVENTS). Writes news_compound (0-1, read by the
    shared scoring), unique_events, scoring_events, event_list (for the page)."""
    by = {k: g for k, g in ev.groupby("account_id")}
    overrides = {}
    if EVENT_OVERRIDES.exists():
        for o in pd.read_csv(EVENT_OVERRIDES, dtype=str).fillna("").itertuples():
            overrides.setdefault(o.company_name, []).append((o.headline_starts_with, o.category))
    comp, n_all, n_scoring, lists = [], [], [], []
    for _, r in leads.iterrows():
        g = by.get(r["account_id"])
        items = []
        if g is not None:
            for x in g.itertuples():
                cat, src = x.category, str(x.source or "")
                if cat not in NEWS_EVENTS or pd.isna(x.published):
                    continue
                if src == "cqc" and cat not in REGISTER_SCORED:
                    continue                           # a new registered manager: shown, not scored
                conf = str(x.event_confidence or "")
                f = 1.0 if conf.startswith(("labelled by", "from ")) else CONFIDENCE_FACTOR.get(conf, 1.0)
                # a person's review (event_overrides.csv) of one headline: applied below to the whole event it belongs to
                ovr = next((c for p, c in overrides.get(r["company_name"], []) if str(x.title or "").startswith(p)), None)
                if ovr:
                    f = 1.0
                kind = {"cqc": "CQC", "fts": "contract", "manual": "hand-labelled", OWN_SITE_SOURCE: "own site"}.get(src, "news")
                items.append({"cat": cat, "date": x.published, "f": f, "kind": kind, "title": x.title, "ovr": ovr})
        if r.get("parent_signal") in NEWS_EVENTS and not pd.isna(r.get("parent_signal_date")):
            pf = CONFIDENCE_FACTOR.get(r.get("parent_confidence") or "", 1.0) * PARENT_FACTOR
            items.append({"cat": r["parent_signal"], "date": r["parent_signal_date"], "f": pf, "kind": "parent",
                          "title": f"Parent {r.get('parent_name')}: {r.get('parent_headline') or ''}", "parent": True})
        events = []                                    # group: same type (and own vs parent) within EVENT_WINDOW_DAYS
        for it in sorted(items, key=lambda d: d["date"]):
            e = next((e for e in events if e["cat"] == it["cat"] and e["parent"] == it.get("parent", False)
                      and (it["date"] - e["first"]).days <= EVENT_WINDOW_DAYS), None)
            if e is None:
                e = {"cat": it["cat"], "parent": it.get("parent", False), "first": it["date"], "items": []}
                events.append(e)
            e["items"].append(it)
        # a reviewed headline decides for its whole event: "Other" drops it (Beal Homes' "sales manager snapped up" was
        # reported by three outlets), another type relabels it (Dunham Care's site purchase = Expansion, not M&A)
        kept = []
        for e in events:
            ovr = next((it["ovr"] for it in e["items"] if it.get("ovr")), None)
            if ovr and ovr not in NEWS_EVENTS:
                continue
            if ovr:
                e["cat"] = ovr
            kept.append(e)
        events = kept
        out, prod = [], 1.0
        for e in events:
            v = max(_strength(e["cat"], it["f"], it["date"], as_of) for it in e["items"])
            prod *= 1 - v
            best = max(e["items"], key=lambda it: (_strength(e["cat"], it["f"], it["date"], as_of), it["kind"] == "news"))
            out.append({"type": ("Parent: " if e["parent"] else "") + e["cat"], "date": e["first"].date().isoformat(),
                        "last": max(it["date"] for it in e["items"]).date().isoformat(), "value": round(v, 3),
                        "reports": len(e["items"]), "sources": ", ".join(sorted({it["kind"] for it in e["items"]})),
                        "title": best["title"]})
        out.sort(key=lambda d: (-d["value"], d["date"]))
        comp.append(round(1 - prod, 4) if events else None)
        n_all.append(len(events)); n_scoring.append(sum(1 for d in out if d["value"] > 0)); lists.append(out)
    if COMPOUND_EVENTS:
        leads["news_compound"] = comp
    leads["unique_events"], leads["scoring_events"], leads["_event_list"] = n_all, n_scoring, lists
    return leads


def hiring_band(status, open_roles):
    """Open roles in bands (HIRING_BANDS). 'unknown' when the careers page wasn't read: never a zero."""
    if status != "ok" or blank(open_roles):
        return "unknown"
    n = int(open_roles)
    return "none open" if n <= 0 else next(lbl for lo, lbl in reversed(HIRING_BANDS) if n >= lo)


def event_detail(nlp_event, nlp_role):
    """Readable detail of an event from the scraper's NLP pass ('M&A: target · SecureSky' -> 'bought by SecureSky').
    Only ever describes an event already counted; never creates one."""
    if blank(nlp_event) or ":" not in str(nlp_event):
        return None
    d = str(nlp_event).split(":", 1)[1].strip()
    head, _, rest = d.partition(" · ")               # the scraper writes "M&A: target · SecureSky"
    head, rest = head.strip(), rest.strip(" ,")
    if nlp_role == "target" or head.startswith("target"):
        return f"bought by {rest.split(',')[0]}" if rest else "being bought"
    if nlp_role == "acquirer" or head.startswith("acquirer"):
        what = rest.split(",")[0]
        # a one-word object is usually a place ("buys Derbyshire nursing home" -> "Derbyshire"), not what was bought
        return f"buying {what}" if len(what.split()) > 1 else "as the buyer"
    m = re.match(r"(.+?) in$", head)
    if m:
        return f"new {m.group(1)}" + (f": {rest}" if rest else "")
    if head.startswith("raised") and re.search(r"\d", head):
        return head
    return None


def _codes(v):
    return [c.strip() for c in str(v).replace(";", ",").split(",") if c.strip() and c.strip().lower() != "nan"]


def target_check(leads):
    """Is the lead in its list's target industry? Apollo's one-word industry is often wrong ("individual & family services"
    for Coxbench Hall Residential Care Home), so the activity codes decide: Apollo's US SIC / NAICS and the Companies House
    UK SIC, then the service lines on its website. Order: codes showing the target activity (and no other trade) -> in;
    a UK SIC for another trade (furniture, building, staffing...) -> check fit, even if its website mentions care (suppliers'
    sites do); website service lines for the list -> in; otherwise Apollo's industry decides. fit_basis says which applied."""
    on, why = [], []
    for r in leads.itertuples():
        rules = TARGET_CODES.get(r.lead_list)
        if not rules:
            on.append(None); why.append(None); continue
        sic, naics = _codes(r.sic_us), _codes(r.naics)
        uk = re.findall(r"\b(\d{5})\b", str(r.uk_sic or ""))
        hit = ([f"SIC {c}" for c in sic if c[:4] in rules["sic"]] + [f"NAICS {c}" for c in naics if c[:4] in rules["naics"]]
               + [f"UK SIC {c}" for c in uk if c[:2] in rules["uk"]])
        strong = [f"UK SIC {c}" for c in uk if c[:2] in OTHER_TRADE_UK_STRONG]
        weak = [f"UK SIC {c}" for c in uk if c[:2] in OTHER_TRADE_UK_WEAK]
        web = [] if blank(r.service_lines) else str(r.service_lines).split("; ")   # what its website says it does
        industry_ok = isinstance(r.industry, str) and r.industry in r.list_target
        supplier = isinstance(r.industry, str) and r.industry in SUPPLIER_GROUPS   # Apollo itself names a supplier trade
        if strong:                                  # a supplier's site says "residential care" too, so building / furniture codes win
            on.append(False); why.append(f"another trade: {', '.join(strong[:2])}" + (f" (codes also show {', '.join(hit[:2])})" if hit else ""))
        elif hit and not (weak and supplier):       # codes win over a holding-company registration, unless Apollo agrees it's another trade
            on.append(True); why.append(f"activity codes: {', '.join(hit[:3])}" + (f" (registered as {', '.join(weak[:1])})" if weak else ""))
        elif weak:
            on.append(False); why.append(f"another trade: {', '.join(weak[:2])} and Apollo industry {r.industry_raw}")
        elif web and not supplier:
            on.append(True); why.append(f"website: {', '.join(web[:3])}")
        else:
            on.append(industry_ok); why.append(f"Apollo industry only: {r.industry_raw}" + (f" (website mentions {web[0]})" if web else ""))
    leads["_on_target"], leads["fit_basis"] = on, why
    leads["on_target"] = on                        # same, kept in the outputs
    # a lead the evidence puts in the target gets the target's industry group for fit and trend (Apollo's label kept in
    # industry_raw / industry_apollo): Royal Variety Charity is "entertainment" in Apollo but runs a care home
    leads["industry_apollo"] = leads["industry"]
    for i, r in leads.iterrows():
        targets = sorted(LIST_TARGET_GROUPS.get(r["lead_list"], []))
        if r["_on_target"] is True and r["industry"] not in targets and len(targets) == 1:
            leads.loc[i, ["industry", "industry_sector"]] = [targets[0], INDUSTRY_SECTOR.get(targets[0])]
    return leads


def competitor_matches(names, domains, country, cmap):
    """Match one company to the competitor-client map (names from candidates' CVs, no domains there).
    exact name key, or the website's name ('smokealarmsaustralia.com.au') = a map name without spaces -> 'confirmed' if
    the map row is confirmed; a close fuzzy match (>= COMPETITOR_FUZZY, names of 2+ words) -> 'pending' (a person checks).
    One-word names (the "Athena" problem) need an exact match and a location that doesn't point elsewhere."""
    import difflib
    keys = {name_key(n) for n in names if not blank(n)} - {""}
    stems = {d.split(".")[0].replace("-", "") for d in domains if isinstance(d, str) and d}
    out = []
    for k in keys:
        rows = cmap.get(k, [])
        if len(k.split()) == 1:                     # one-word: exact, long enough, and no other country named
            rows = [r for r in rows if len(k) >= 6 and (blank(r["client_locations"]) or COUNTRY_WORDS.get(country, "~") in str(r["client_locations"]).lower())]
        out += [(r, "exact name") for r in rows]
    for s in stems:
        out += [(r, "website name") for k, rows in cmap.items() if len(s) >= 6 and k.replace(" ", "") == s for r in rows]
    if not out:                                     # close names: both sides 2+ words and 10+ letters ("c technologies" ≠ "technologies")
        multi = [c for c in cmap if len(c.split()) >= 2 and len(c) >= 10]
        for k in keys:
            if len(k.split()) >= 2 and len(k) >= 10:
                for m in difflib.get_close_matches(k, multi, n=1, cutoff=COMPETITOR_FUZZY):
                    out += [({**r, "status": "pending"}, f"close name ({m})") for r in cmap[m]]
    return out


def add_competitor_clients(leads, path):
    """Competitor client (prior_bpo_flag): the lead appears as a competitor's client in candidates' CVs."""
    cols = ["competitor_client", "competitor_client_status", "competitor_client_basis"]
    if not path.exists():
        return leads.assign(**{k: None for k in cols}), f"no competitor map ({path.name}): Competitor client counts as No"
    m = pd.read_csv(path, dtype={"name_key": str})
    cmap = {}
    for r in m.to_dict("records"):
        cmap.setdefault(r["name_key"], []).append(r)
    res = []
    for r in leads.itertuples():
        hits = competitor_matches([r.company_name, r.apollo_name], [r.website_domain, r.email_domain], r.region, cmap)
        if not hits:
            res.append((None, None, None)); continue
        conf = [h for h in hits if h[0]["status"] == "confirmed"]
        use = conf or hits
        comp = "; ".join(sorted({f"{h[0]['competitor']} ({int(h[0]['rows_confirmed'] + h[0]['rows_pending'])} CV mentions)" for h in use}))
        res.append((comp, "confirmed" if conf else "pending", "; ".join(sorted({h[1] for h in use}))))
    leads[cols] = pd.DataFrame(res, index=leads.index, columns=cols)
    leads["prior_bpo_flag"] = leads["competitor_client_status"].map({"confirmed": "Yes"}).fillna("No")
    return leads, f"{path.name}: {m['name_key'].nunique():,} clients of {m['competitor'].nunique()} competitors"


def apollo_vs_news(label, news):
    """How Apollo's undated 'Latest Funding' compares with the event the news found (decision 2026-11-18: shown side by
    side; how to reconcile the two is still open). None = no Apollo label."""
    if blank(label):
        return None
    if news not in NEWS_EVENTS:
        return "not in the news"
    return "matches the news" if news in APOLLO_CONFIRMS.get(label, []) else "news shows a different event"


def best_detail(arts, category, date):
    """The fullest detail for one event: among the company's articles about it (the NLP pass read the same event type,
    published within 30 days of the event date), prefer one that names the other party, amount or person."""
    if arts.empty or blank(category):
        return None
    a = arts[arts["nlp_event"].fillna("").str.startswith(category + ":")]
    if not pd.isna(date):
        a = a[(a["published"] - date).abs() <= pd.Timedelta(days=30)]
    best = None
    for e, ro in sorted(zip(a["nlp_event"], a["nlp_role"]), key=lambda x: (" · " not in x[0], len(x[0]))):
        best = best or event_detail(e, ro)
    return best


def add_service_lines(leads, db):
    """Service lines found on the company's website card (SERVICE_LINES for its list). No points: targeting and pitch."""
    if not db.exists():
        return leads.assign(service_lines=None)
    import sqlite3
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as con:
        cards = dict(con.execute("SELECT company_id, data FROM company_profiles WHERE company_id LIKE 'apollo-%'").fetchall())
    def tags(r):
        raw = cards.get("apollo-" + r["account_id"][3:])
        if not raw:
            return None
        c = json.loads(raw)
        text = " ".join([c.get("site_name") or "", c.get("description") or "", " ".join(c.get("keywords") or []), r["company_name"]]).lower()
        found = [k for k, rx in SERVICE_LINES.get(r["lead_list"], {}).items() if re.search(rx, text)]
        return "; ".join(found) or None
    return leads.assign(service_lines=leads.apply(tags, axis=1))


def add_roles(leads, db):
    """Each lead's posted job titles matched to the roles Cloudstaff fills (roles.py), and the per-title list for the page."""
    cols = ["roles_listed", "roles_we_fill", "roles_we_fill_30d", "roles_possible", "roles_onsite", "roles_we_fill_categories", "roles_we_fill_titles"]
    reports = sorted(glob.glob(str(Path.home() / STAFF_REPORT_GLOB), recursive=True))
    if not db.exists() or not reports:
        return leads.assign(**{k: None for k in cols}), {}, "no Staff Central report found: hiring counts every open role"
    import sqlite3
    from roles import RoleMatcher
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as con:
        jp = pd.read_sql("SELECT company_id, title, posted_at FROM job_postings WHERE company_id LIKE 'apollo-%'", con)
    jp["account_id"] = "AP-" + jp["company_id"].str.slice(7)
    jp["posted"] = pd.to_datetime(jp["posted_at"], errors="coerce")
    m = RoleMatcher(reports[-1]).match(jp["title"].unique())
    jp = jp.merge(m, on="title", how="left")
    today = pd.Timestamp.today().normalize()
    jp["_fill"] = jp["verdict"] == "we fill"
    jp["_fill30"] = jp["_fill"] & (jp["posted"] >= today - pd.Timedelta(days=30))
    g = jp.groupby("account_id").agg(roles_listed=("title", "size"), roles_we_fill=("_fill", "sum"), roles_we_fill_30d=("_fill30", "sum"),
                                     roles_possible=("verdict", lambda s: int((s == "possible").sum())),
                                     roles_onsite=("verdict", lambda s: int((s == "on-site").sum())),
                                     roles_we_fill_categories=("jp_category", lambda s: "; ".join(sorted(set(s[jp.loc[s.index, "_fill"]].dropna())))),
                                     roles_we_fill_titles=("clean", lambda s: "; ".join(sorted(set(s[jp.loc[s.index, "_fill"]])))))
    per_lead = {k: [{"title": x.clean, "posted": jsonable(x.posted), "verdict": x.verdict, "jp_title": jsonable(x.jp_title),
                     "jp_category": jsonable(x.jp_category), "similarity": jsonable(x.similarity)} for x in d.sort_values("posted", ascending=False).itertuples()]
                for k, d in jp.groupby("account_id")}
    return leads.merge(g, on="account_id", how="left"), per_lead, f"{Path(reports[-1]).name} (JP titles only)"


def job_recency(leads, db):
    """Per lead: roles posted in the last 30 / 90 days and the newest posting date, from the scraper's per-role table."""
    cols = ["jobs_new_30d", "jobs_new_90d", "jobs_newest"]
    if not db.exists():
        return leads.assign(**{k: None for k in cols})
    import sqlite3
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as con:
        jp = pd.read_sql("SELECT company_id, posted_at FROM job_postings", con)
    jp["posted"] = pd.to_datetime(jp["posted_at"], errors="coerce")
    jp["account_id"] = "AP-" + jp["company_id"].str.replace("^apollo-", "", regex=True)
    today = pd.Timestamp.today().normalize()
    g = jp.groupby("account_id")["posted"].agg(jobs_new_30d=lambda s: int((s >= today - pd.Timedelta(days=30)).sum()),
                                                jobs_new_90d=lambda s: int((s >= today - pd.Timedelta(days=90)).sum()), jobs_newest="max")
    return leads.merge(g, on="account_id", how="left")


def load_reviews():
    """{(company_name, source, notice): (verdict, reviewed_by)} from REGISTER_REVIEWS."""
    if not REGISTER_REVIEWS.exists():
        return {}
    rv = pd.read_csv(REGISTER_REVIEWS, dtype=str, keep_default_na=False)
    return {(r.company_name.strip(), r.source.strip(), r.notice.strip()): (r.verdict.strip().lower(), r.reviewed_by.strip())
            for r in rv.itertuples() if r.company_name.strip()}


def review_of(reviews, company, source, notice=""):
    """'confirmed' / 'rejected' (with who) or None, for one register match."""
    return reviews.get((company, source, notice or ""))


def register_events(leads):
    """CQC and Find a Tender events in the manual-events shape, keyed by account (not by name). `match` says how the lead
    was found in the register; rejected name matches are dropped, confirmed ones say so."""
    cols = ["account_id", "date", "category", "headline", "url", "publisher", "labelled_by", "note", "kind", "source", "match"]
    frames = [pd.read_csv(p, dtype=str, keep_default_na=False).assign(labelled_by=name) for name, p in REGISTER_FILES.items() if p.exists()]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=cols)
    d = pd.concat(frames, ignore_index=True)
    if CQC_PROVIDERS.exists():                      # a CQC event is as good as the lead's CQC match
        basis = pd.read_csv(CQC_PROVIDERS, dtype=str, keep_default_na=False).set_index("company_id")["cqc_match"]
        cq = d["source"] == "cqc"
        d.loc[cq, "match"] = d.loc[cq, "company_id"].map(basis)
    d["match"] = d["match"].fillna("")
    out = pd.DataFrame({"account_id": "AP-" + d["company_id"].str.replace("^apollo-", "", regex=True), "date": d["date"],
                        "category": d["category"], "headline": d["headline"], "url": d["url"], "publisher": d["publisher"],
                        "labelled_by": d["labelled_by"], "note": d["detail"], "kind": "register", "source": d["source"], "match": d["match"]})
    reviews, names = load_reviews(), dict(zip(leads["account_id"], leads["company_name"]))
    keep = []
    for r in out.itertuples():
        notice = r.url.rsplit("/", 1)[-1] if r.source == "fts" else ""
        rv = review_of(reviews, names.get(r.account_id, ""), r.labelled_by, notice) if r.match.startswith("name") else None
        keep.append(not (rv and rv[0] == "rejected"))
        if rv and rv[0] == "confirmed":
            out.loc[r.Index, "match"] = f"name, confirmed by {rv[1]}"
    return out[keep]


def add_cqc(leads):
    """CQC profile per lead (cqc.py): providers, locations, beds, service types, ratings. England care providers only."""
    if not CQC_PROVIDERS.exists():
        leads["cqc_match"] = None
        return leads
    c = pd.read_csv(CQC_PROVIDERS, dtype=str, keep_default_na=False, na_values=[""])
    c["account_id"] = "AP-" + c.pop("company_id").str.replace("^apollo-", "", regex=True)
    for k in ("cqc_locations", "cqc_care_homes", "cqc_beds", "cqc_homecare_locations", "cqc_needs_improvement",
              "cqc_needs_improvement_180d", "cqc_new_locations", "cqc_closed_locations"):
        c[k] = pd.to_numeric(c[k], errors="coerce")
    return leads.merge(c, on="account_id", how="left")


def review_flags(leads):
    """Apply REGISTER_REVIEWS to the CQC match, and write match_review: what still needs a person's check."""
    reviews = load_reviews()
    cqc_cols = [c for c in leads.columns if c.startswith("cqc_")]
    flags = []
    for i, r in leads.iterrows():
        items = []
        if isinstance(r.get("cqc_match"), str) and r["cqc_match"].startswith("name"):
            rv = review_of(reviews, r["company_name"], "CQC register")
            if rv and rv[0] == "rejected":
                leads.loc[i, cqc_cols] = None
            elif rv and rv[0] == "confirmed":
                leads.loc[i, "cqc_match"] = f"name, confirmed by {rv[1]}"
            else:
                items.append(f"CQC matched by provider name ({r.get('cqc_providers')})")
        if isinstance(r.get("_contract_review"), str):
            items.append(r["_contract_review"])
        flags.append("; ".join(items) or None)
    leads["match_review"] = flags
    return leads


def add_subsectors(leads):
    """Sub-sector(s) from CQC service types (when matched), else from the activity codes. See SUBSECTORS."""
    subs, basis = [], []
    for r in leads.itertuples():
        rules = SUBSECTORS.get(r.lead_list, {})
        st = getattr(r, "cqc_service_types", None)
        st = st if isinstance(st, str) else ""
        if st and any("cqc" in v for v in rules.values()):
            found = [k for k, v in rules.items() if v.get("cqc") and re.search(v["cqc"], st, re.I)]
            if found:
                subs.append("; ".join(found)); basis.append("CQC service types"); continue
        sic, naics = [c[:4] for c in _codes(r.sic_us)], [c[:4] for c in _codes(r.naics)]
        uk = re.findall(r"\b(\d{5})\b", str(getattr(r, "uk_sic", "") or ""))
        found = [k for k, v in rules.items() if set(sic) & v["sic"] or set(naics) & v["naics"]
                 or any(u.startswith(tuple(v["uk"])) for u in uk)]
        subs.append("; ".join(found) or None); basis.append("activity codes" if found else None)
    leads["sub_sectors"], leads["sub_sector_basis"] = subs, basis
    return leads


def add_ownership(leads, ev, as_of):
    """Who owns the lead (ownership.py), cross-checked with Apollo's parent and the news. Writes `ownership` (one of
    OWNERSHIP_ORDER), `ownership_evidence` and `ownership_check` (a conflict for a person to look at)."""
    cols = ["ownership", "ownership_evidence", "ownership_number", "ownership_number_source", "ownership_number_name",
            "company_numbers", "company_type", "owner_chain", "owner_chain_steps", "top_owner", "group_companies", "owners_named",
            "cqc_charity_number", "cqc_provider_sector", "website_number_page", "psc_snapshot"]
    if OWNERSHIP.exists():
        o = pd.read_csv(OWNERSHIP, dtype=str, keep_default_na=False, na_values=[""])
        o["account_id"] = "AP-" + o.pop("company_id").str.replace("^apollo-", "", regex=True)
        o["group_companies"] = pd.to_numeric(o["group_companies"], errors="coerce")
        leads = leads.merge(o[["account_id"] + [c for c in cols if c in o.columns]], on="account_id", how="left")
    for c in cols:
        if c not in leads.columns:
            leads[c] = None
    leads["ownership"] = leads["ownership"].fillna("Not checked")
    recent = ev[(ev["published"] >= as_of - pd.Timedelta(days=OWNERSHIP_EVENT_DAYS))] if len(ev) else ev
    pe = recent[recent["category"] == "PE buyout"].groupby("account_id")["published"].max() if len(ev) else pd.Series(dtype=object)
    ma = recent[recent["category"] == "M&A"].groupby("account_id")["published"].max() if len(ev) else pd.Series(dtype=object)
    checks = []
    for i, r in leads.iterrows():
        cls, evid, notes = r["ownership"], r["ownership_evidence"], []
        if r["account_id"] in pe.index and cls in OWNERSHIP_PRIVATE | {"Unknown", "Not checked"}:
            cls, evid = "Investor-backed", f"PE buyout in the news ({pe[r['account_id']]:%b %Y})" + ("" if blank(evid) else f"; register: {evid}")
        if not blank(r.get("parent_company")):
            if cls in ("Unknown", "Not checked"):
                cls, evid = "Part of a corporate group", f"Apollo names a parent: {r['parent_company']}" + ("" if blank(evid) else f"; {evid}")
            elif cls in OWNERSHIP_PRIVATE:
                notes.append(f"Apollo names a parent ({r['parent_company']}) but Companies House shows individuals at the top")
        if r["account_id"] in ma.index and cls in OWNERSHIP_PRIVATE:
            notes.append(f"M&A in the news ({ma[r['account_id']]:%b %Y}): check who bought whom; the owner may have changed")
        if r.get("ownership_number_source") == "website":
            notes.append(f"company number read from its website ({r.get('ownership_number_name')}): confirm it is the same business")
        leads.at[i, "ownership"], leads.at[i, "ownership_evidence"] = cls, evid
        checks.append("; ".join(notes) or None)
    leads["ownership_check"] = checks
    leads["ownership_target"] = leads["ownership"].eq("Owner-managed")
    return leads


def add_collected(leads, out_dir, as_of):
    s_all = pd.read_csv(out_dir / "company_summary.csv", keep_default_na=False, na_values=[""], dtype=str)
    parents = s_all[s_all["company_id"].str.startswith("parent-")].set_index("company_id")
    s = s_all[s_all["company_id"].str.startswith("apollo-")].copy()
    s["account_id"] = "AP-" + s["company_id"].str.replace("^apollo-", "", regex=True)
    keep = {"news_status": "news_status", "news_signal": "news_signal", "news_signal_date": "news_signal_date",
            "signal_confidence": "signal_confidence", "headline": "news_headline", "url": "news_url", "publisher": "news_publisher",
            "matched_articles": "matched_articles", "distinct_stories": "distinct_stories", "events_not_other": "events_not_other",
            "company_website_articles": "company_website_articles", "possible_matches_to_review": "news_to_review",
            "jobs_status": "jobs_status", "open_roles": "open_roles", "job_postings_30d": "job_postings_30d",
            "hiring_spike": "hiring_spike", "careers_url": "careers_url", "filings_status": "filings_status",
            "filing_signal": "filing_signal", "filing_signal_date": "filing_signal_date", "registered_name": "registered_name",
            "registration_id": "company_number", "registered_status": "registered_status", "registered_on": "registered_on",
            "uk_accounts": "uk_accounts", "uk_sic": "uk_sic", "profile_status": "website_profile", "name_type": "name_type"}
    leads = leads.merge(s[["account_id"] + list(keep)].rename(columns=keep), on="account_id", how="left")
    for k in ("matched_articles", "distinct_stories", "events_not_other", "company_website_articles", "news_to_review", "open_roles", "job_postings_30d"):
        leads[k] = pd.to_numeric(leads[k], errors="coerce")
    leads["news_signal_date"] = pd.to_datetime(leads["news_signal_date"], errors="coerce")
    ev_all = pd.read_csv(out_dir / "signal_events.csv", dtype=str, keep_default_na=False, na_values=[""])
    ev_all = ev_all[ev_all["signal_type"] == "news"].copy()
    ev_all["published"] = pd.to_datetime(ev_all["published_at"], errors="coerce")
    pev = ev_all[ev_all["company_id"].str.startswith("parent-")].copy()
    ev = ev_all[ev_all["company_id"].str.startswith("apollo-")].copy()
    ev["account_id"] = "AP-" + ev["company_id"].str.replace("^apollo-", "", regex=True)

    # a person's review of the chosen event wins over the scraper's category (event_overrides.csv); applies to parents too
    overrides = pd.read_csv(EVENT_OVERRIDES, dtype=str) if EVENT_OVERRIDES.exists() else pd.DataFrame()
    leads["event_review"] = None
    for o in overrides.itertuples():
        hit = (leads["company_name"] == o.company_name) & leads["news_headline"].fillna("").str.startswith(o.headline_starts_with)
        leads.loc[hit, ["news_signal", "signal_confidence", "event_review"]] = [o.category, "reviewed", f"{o.reason} ({o.reviewed_on})"]
        ph = (parents["company_name"] == o.company_name) & parents["headline"].fillna("").str.startswith(o.headline_starts_with)
        parents.loc[ph, ["news_signal", "signal_confidence"]] = [o.category, "reviewed"]

    # own blog posts: no points unless the post is a relevant event. When the chosen signal is "Other" news, keep it only if
    # someone else wrote about the company in the last 180 days (dated by the newest such article); otherwise "None".
    third = ev[(ev["source"] != OWN_SITE_SOURCE) & (ev["published"] >= as_of - pd.Timedelta(days=180))]
    newest_third = third.sort_values("published").groupby("account_id").last()
    own_posts = ev[ev["source"] == OWN_SITE_SOURCE].groupby("account_id").size()
    leads["own_site_posts"] = leads["account_id"].map(own_posts).fillna(0).astype(int)
    leads["news_from"] = None
    for i, r in leads[leads["news_signal"] == "Other / Unclassified"].iterrows():
        if r["account_id"] in newest_third.index:
            t = newest_third.loc[r["account_id"]]
            leads.loc[i, ["news_signal_date", "news_headline", "news_url", "news_publisher"]] = [t["published"], t["title"], t["url"], t["publisher"]]
        else:
            leads.loc[i, ["news_signal", "news_signal_date", "news_headline", "news_url", "news_publisher"]] = ["None", pd.NaT, None, None, None]
    # decision 2026-11-18: "Other" news earns no points for leads (it isn't shown as a reason, so it mustn't move the score).
    # The articles stay in the lead's news list; other_news_date keeps the newest one for reference.
    leads["other_news_date"] = leads["news_signal_date"].where(leads["news_signal"] == "Other / Unclassified")
    if not OTHER_NEWS_POINTS:
        leads.loc[leads["news_signal"] == "Other / Unclassified", ["news_signal", "news_signal_date"]] = ["None", pd.NaT]
    is_event = leads["news_signal"].isin(NEWS_EVENTS)
    leads["news_strength_factor"] = [CONFIDENCE_FACTOR.get(c, 1.0) if e else 1.0 for c, e in zip(leads["signal_confidence"].fillna(""), is_event)]
    leads.loc[leads["news_signal"].notna() & (leads["news_signal"] != "None"), "news_from"] = "company"
    # event details (scraper NLP pass): who bought whom, amounts, new executives; only for the event already chosen
    leads["event_detail"] = [best_detail(ev[ev["account_id"] == a], s, d) if s in NEWS_EVENTS else None
                             for a, s, d in zip(leads["account_id"], leads["news_signal"], leads["news_signal_date"])]

    # parent company: its relevant event counts at PARENT_FACTOR when stronger than the lead's own news; marked "Parent"
    leads["parent_id"] = "parent-" + leads["parent_company"].fillna("").str.extract(r"\(([^()]+)\)\s*$")[0].fillna("").str.lower().str.replace("^www\\.", "", regex=True)
    pcols = {"company_name": "parent_name", "news_signal": "parent_signal", "news_signal_date": "parent_signal_date",
             "signal_confidence": "parent_confidence", "headline": "parent_headline", "url": "parent_url", "news_status": "parent_news_status"}
    leads = leads.merge(parents[list(pcols)].rename(columns=pcols), left_on="parent_id", right_index=True, how="left")
    leads["parent_signal_date"] = pd.to_datetime(leads["parent_signal_date"], errors="coerce")
    leads.loc[~leads["parent_signal"].isin(NEWS_EVENTS), ["parent_signal", "parent_signal_date", "parent_confidence", "parent_headline", "parent_url"]] = None
    for i, r in leads[leads["parent_signal"].notna()].iterrows():
        pf = CONFIDENCE_FACTOR.get(r["parent_confidence"] or "", 1.0) * PARENT_FACTOR
        if _strength(r["parent_signal"], pf, r["parent_signal_date"], as_of) > _strength(r["news_signal"], r["news_strength_factor"], r["news_signal_date"], as_of):
            leads.loc[i, ["news_signal", "news_signal_date", "signal_confidence", "news_strength_factor", "news_from"]] = \
                [r["parent_signal"], r["parent_signal_date"], r["parent_confidence"], pf, "parent"]

    # hand-labelled events (manual_events.csv, labelled_by Claude or a person): count in full when stronger than the lead's
    # own news; also added to the lead's news list so they show with who labelled them
    # registers (CQC, Find a Tender): dated facts, the same treatment, keyed by account; only REGISTER_SCORED types score
    leads["event_labelled_by"] = None
    me = pd.DataFrame(columns=["account_id", "date", "category", "headline", "url", "publisher", "labelled_by", "note", "kind", "source"])
    if MANUAL_EVENTS.exists():
        me = pd.read_csv(MANUAL_EVENTS, dtype=str).fillna("")
        acc = dict(zip(leads["company_name"], leads["account_id"]))
        me["account_id"] = me["company_name"].map(acc)
        unknown = me.loc[me["account_id"].isna(), "company_name"].unique()
        if len(unknown):
            print(f"manual_events.csv: no lead called {', '.join(unknown)} (check the spelling)")
        me = me[me["account_id"].notna()].assign(kind="manual", source="manual")
    reg = register_events(leads)
    # contract awards matched on a name only, not yet confirmed: listed on the lead for a person to check
    nm = reg[(reg["source"] == "fts") & (reg["match"] == "name")]
    leads["_contract_review"] = leads["account_id"].map(nm.groupby("account_id")["url"].agg(
        lambda u: f"{len(u)} contract{'s' if len(u) > 1 else ''} matched by supplier name"))
    me = pd.concat([me, reg], ignore_index=True)
    me = me[me["account_id"].isin(leads["account_id"])].copy()
    me["published"] = pd.to_datetime(me["date"], errors="coerce")
    for i, r in leads.iterrows():
        for m in me[me["account_id"] == r["account_id"]].itertuples():
            if m.kind == "register" and m.category not in REGISTER_SCORED:
                continue
            cur = _strength(leads.at[i, "news_signal"], leads.at[i, "news_strength_factor"], leads.at[i, "news_signal_date"], as_of)
            if _strength(m.category, 1.0, m.published, as_of) > cur:
                conf = "manual" if m.kind == "manual" else "register"
                leads.loc[i, ["news_signal", "news_signal_date", "signal_confidence", "news_strength_factor", "news_from",
                              "news_headline", "news_url", "news_publisher", "event_labelled_by", "event_detail"]] = \
                    [m.category, m.published, conf, 1.0, m.kind, m.headline, m.url, m.publisher, m.labelled_by, m.note or None]
    ev = pd.concat([ev, pd.DataFrame({"account_id": me["account_id"], "published_at": me["date"], "published": me["published"],
                                      "category": me["category"],
                                      "event_confidence": [("labelled by " if k == "manual" else "from ") + b for k, b in zip(me["kind"], me["labelled_by"])],
                                      "title": me["headline"], "url": me["url"], "publisher": me["publisher"],
                                      "source": me["source"]})], ignore_index=True)

    # jobs: a count is only known when the careers page was read (blank = unknown, never zero)
    leads.loc[leads["jobs_status"] != "ok", "job_postings_30d"] = None
    leads = job_recency(leads, JOBS_DB)
    leads["hiring_band"] = [hiring_band(s, n) for s, n in zip(leads["jobs_status"], leads["open_roles"])]
    leads, jobs_by_lead, roles_src = add_roles(leads, JOBS_DB)
    leads["all_postings_30d"] = leads["job_postings_30d"]
    if HIRING_SCORE == "roles_we_fill" and leads["roles_we_fill_30d"].notna().any():
        # hiring points count only roles Cloudstaff fills; a read careers page with none of them is a real zero
        leads.loc[leads["jobs_status"] == "ok", "job_postings_30d"] = leads["roles_we_fill_30d"].fillna(0)
    leads = add_service_lines(leads, JOBS_DB)
    leads = add_cqc(leads)
    leads = review_flags(leads)
    leads = target_check(leads)                    # needs the Companies House UK SIC, so after the scraper results
    leads = add_subsectors(leads)
    leads = add_ownership(leads, ev, as_of)
    leads["apollo_vs_news"] = [apollo_vs_news(a, s) for a, s in zip(leads["apollo_latest_funding"], leads["news_signal"])]
    leads["parent_detail"] = [best_detail(pev[pev["company_id"] == p], s, d) if not blank(s) else None
                              for p, s, d in zip(leads["parent_id"], leads["parent_signal"], leads["parent_signal_date"])]
    for k in ("team_builder_visit", "form_fill_30d", "web_visits_30d", "diamond_referral", "prior_bpo_flag"):
        leads[k] = None                            # no website analytics or referral data for Apollo leads yet
    pev["parent_id"] = pev["company_id"]
    return leads, ev, pev, jobs_by_lead, roles_src


# ---------------------------------------------------------------- 4. gates, score, reasons
def gate(r):
    status = " ".join(str(r.get(k) or "") for k in ("registered_status", "filing_signal")).lower()
    if re.search(DISTRESS, status):
        return "Excluded: distressed"
    if isinstance(r.get("internal_match"), str) and r["internal_match"].startswith("Existing client"):
        return "Existing client"
    if isinstance(r.get("duplicate_of"), str):
        return DUPLICATE                           # the other account carries the lead; this one keeps its contacts for reference
    if r.get("_on_target") is False:
        return CHECK_FIT                           # scored, but outside the list's tiers (not this campaign's industry)
    return None



def news_by_category(events, as_of):
    """account_id -> {event type: [{date, title, publisher, url, confidence}], newest first} for the lead's own relevant
    events in the last year. Feeds the Why chips' hover lists."""
    e = events[events["category"].isin(NEWS_EVENTS) & (events["published"] >= as_of - pd.Timedelta(days=365))]
    e = e.sort_values("published", ascending=False)
    out = {}
    for (acc, cat), g in e.groupby(["account_id", "category"], sort=False):
        out.setdefault(acc, {})[cat] = [{"date": f"{x.published:%Y-%m-%d}", "title": x.title, "publisher": None if blank(x.publisher) else x.publisher,
                                         "url": None if blank(x.url) else x.url,
                                         "confidence": None if blank(x.event_confidence) else x.event_confidence} for x in g.itertuples()]
    # newest type first
    return {a: dict(sorted(d.items(), key=lambda kv: kv[1][0]["date"], reverse=True)) for a, d in out.items()}


def chips(r, as_of):
    out = []
    news, d = r.get("news_signal"), r.get("news_signal_date")
    from_parent = r.get("news_from") == "parent"
    by_cat = r.get("_news_by_cat") if isinstance(r.get("_news_by_cat"), dict) else {}   # {event type: [headlines]}, newest first
    head = r.get("news_headline")
    if news in NEWS_EVENTS and not from_parent and not blank(head):
        # a reviewed or hand-labelled event keeps its article under the reviewed type, not the scraper's original one
        mine = [x for xs in by_cat.values() for x in xs if x["title"] == head][:1]
        by_cat = {c: [x for x in xs if x["title"] != head] for c, xs in by_cat.items()}
        by_cat[news] = mine + by_cat.get(news, [])
        by_cat = {c: xs for c, xs in by_cat.items() if xs}
    if news in NEWS_EVENTS and not from_parent:
        conf = r.get("signal_confidence") or "unrated"
        suffix = ("" if conf == "high" else " (reviewed)" if conf == "reviewed"
                  else f" (labelled by {r.get('event_labelled_by')})" if conf == "manual"
                  else f" ({r.get('event_labelled_by')})" if conf == "register" else f" ({conf} confidence, half weight)")
        det = r.get("event_detail")
        out.append([f"{news}{'' if blank(det) else ': ' + det} · {d:%b %Y}{suffix}", "signal", by_cat.get(news, [])])
    # other kinds of news event the lead had in the year: one short chip each, headlines on hover. Not scored (only the
    # strongest event counts), but two or more different events say more than one.
    for cat, items in by_cat.items():
        if cat == news and not from_parent:
            continue
        n = len(items)
        low = all(x["confidence"] == "low" for x in items)
        out.append([f"{cat} · {pd.Timestamp(items[0]['date']):%b %Y}" + (f" · {n} articles" if n > 1 else "")
                    + (" · low confidence" if low else ""), "news", items])
    # "Other" news and own-website posts are not reasons (decision 2026-11-18): they stay in the lead's news list only
    if r.get("parent_signal") in NEWS_EVENTS:       # parent news: always shown, marked; scored only when it beat the lead's own
        pd_, pdet = r.get("parent_signal_date"), r.get("parent_detail")
        out.append([f"Parent {r.get('parent_name')}: {r['parent_signal']}{'' if blank(pdet) else ' (' + pdet + ')'}"
                    + ("" if pd.isna(pd_) else f" · {pd_:%b %Y}")
                    + (" (scored, half weight)" if from_parent else " (not scored: own news is stronger)"), "parent"])
    if r.get("hiring_band") not in (None, "unknown", "none open"):
        n30, newest = r.get("jobs_new_30d"), r.get("jobs_newest")
        recency = (f" · {int(n30)} new in 30 days" if not blank(n30) and n30 > 0
                   else f" · newest {newest:%d %b %Y}" if not blank(newest) and not pd.isna(newest) else " · dates unknown")
        spike = " · hiring spike" if r.get("hiring_spike") == "Yes" else ""
        k, listed, onsite = r.get("roles_we_fill"), r.get("roles_listed"), r.get("roles_onsite")
        if blank(k):
            fill = ""
        elif k > 0:
            fill = f" · {int(k)} we fill ({r.get('roles_we_fill_categories')})"
        else:
            fill = " · all on-site roles" if not blank(onsite) and onsite == listed else " · none we fill"
        out.append([f"Hiring {r['hiring_band']} roles{recency}{fill}{spike}", "signal" if not blank(k) and k > 0 else "jobs"])
    for s in ([] if blank(r.get("service_lines")) else str(r["service_lines"]).split("; ")):
        out.append([s, "service"])
    for s in ([] if blank(r.get("sub_sectors")) else str(r["sub_sectors"]).split("; ")):
        out.append([f"Sub-sector: {s}", "info"])
        if s in SUBSECTOR_PITCH:
            out.append([f"Pitch ({s.lower()}): {SUBSECTOR_PITCH[s]}", "pitch"])
    if not blank(r.get("cqc_locations")):
        out.append([f"CQC: {int(r['cqc_locations'])} locations"
                    + (f" · {int(r['cqc_care_homes'])} care homes, {int(r['cqc_beds'])} beds" if r.get("cqc_care_homes") else "")
                    + (f" · {int(r['cqc_homecare_locations'])} home-care offices" if r.get("cqc_homecare_locations") else ""), "info"])
    if not blank(r.get("cqc_needs_improvement_180d")) and r["cqc_needs_improvement_180d"] > 0:
        n = int(r["cqc_needs_improvement_180d"])
        out.append([f"CQC: {n} location{'s' if n > 1 else ''} rated Requires improvement or Inadequate in the last 6 months", "filing"])
    fs = r.get("filing_signal")
    if not blank(fs) and fs != "None" and not str(r.get("grade", "")).startswith("Excluded"):
        fd = r.get("filing_signal_date")
        out.append([fs + ("" if blank(fd) else f" · {fd}"), "filing"])
    if not blank(r.get("apollo_latest_funding")):   # Apollo's own funding event: its own chip, compared with the news, no points
        m = r.get("apollo_vs_news")
        tail = {"matches the news": f" · matches the news ({d:%b %Y})" if not pd.isna(d) else " · matches the news",
                "news shows a different event": f" · news shows {news} instead",
                "not in the news": " · undated, not in the news"}.get(m, "")
        out.append([f"Apollo funding: {r['apollo_latest_funding']}{tail}", "apollo"])
    # fit chip: the main dashboard's rule (FIT chip_band / chip_min_lift): High band AND at least 1.5x the usual rate.
    # Bands are relative, so "High" alone flags most industries; the full detail is in the lead's panel.
    for s, lbl in (("fit_growth", "5+ seats in a year"), ("fit_reach_10", "10+ seats in 2 years"), ("fit_branch_1y", "a 2nd department in a year")):
        p, usual = r.get(f"{s}_p"), r.get(f"{s}_usual")
        if r.get(f"{s}_band") == FIT["chip_band"] and not blank(p) and not blank(usual) and p >= FIT["chip_min_lift"] * usual:
            out.append([f"Fit: likely {lbl} ({p:.0%} vs usual {usual:.0%})", "fit"])
    if not blank(r.get("parent_company")):
        out.append([f"Part of {r['parent_company']}", "info"])
    if not blank(r.get("competitor_client")):       # from candidates' CVs (Client Extraction)
        if r.get("competitor_client_status") == "confirmed":
            out.append([f"Competitor client: {r['competitor_client']}", "signal"])
        else:
            out.append([f"Possible competitor client, check: {r['competitor_client']} · {r.get('competitor_client_basis')}", "warn"])
    if not blank(r.get("former_name")):          # Apollo name "Old Now New": searched under the new name
        out.append([f"Renamed: was {r['former_name']}" + ("" if blank(r.get("duplicate_of_name")) else f" · same business as the {r['duplicate_of_name']} lead"), "warn"])
    elif r.get("name_check"):
        out.append([f"Check the name: {r.get('name_note')}", "warn"])
    if r.get("_on_target") is False:
        out.append([f"Check fit: {r.get('fit_basis') or r.get('industry_raw')}", "warn"])
    if not blank(r.get("scoring_events")) and r["scoring_events"] > 1:
        out.append([f"{int(r['scoring_events'])} separate events in 6 months (added up)", "signal"])
    if not blank(r.get("match_review")):
        out.append([f"Check match: {r['match_review']}", "warn"])
    if not blank(r.get("ownership_check")):
        out.append([f"Check ownership: {r['ownership_check']}", "warn"])
    if isinstance(r.get("internal_match"), str):
        out.append([r["internal_match"], "warn"])
    for p in filter(None, str(r.get("pitch") or "").split("; ")):
        out.append([p, "pitch"])
    return out


def readiness(leads):
    """Lead readiness (0-4): tie-break only, never points. Decision 2026-11-18 ("use any data points we do have"): with few
    signals per lead, scores tie in large blocks (pilot: 129 care homes on one score), and percentile tiers then put whole
    blocks in Tier 1. One point each for READINESS (below)."""
    parts = pd.DataFrame({
        "Apollo funding label": leads["apollo_latest_funding"].notna(),
        "Decision-maker with a verified email": leads["dm_verified"].fillna(0) > 0,
        "In the news, or a relevant event on its own site, in the last 180 days": leads["recent_activity"],
        "In the list's target industry": leads["_on_target"].fillna(False).astype(bool),
    })
    return parts.sum(axis=1).astype(int), parts.apply(lambda r: "; ".join(k for k, v in r.items() if v), axis=1)


def grade(leads, contacts, events, as_of):
    # contact readiness: shown next to the grade, and one of the readiness points; not in the score
    c = contacts.assign(_dm=contacts["seniority"].str.lower().isin(DECISION_MAKER), _ver=contacts["email_status"].eq("Verified"))
    c["_dmv"] = c["_dm"] & c["_ver"]
    agg = c.groupby("account_id").agg(n_contacts=("name", "size"), decision_makers=("_dm", "sum"), verified_emails=("_ver", "sum"),
                                      dm_verified=("_dmv", "sum"), best_contact=("name", "first"), best_title=("title", "first"))
    leads = leads.merge(agg, on="account_id", how="left")
    counts = (events["source"] != OWN_SITE_SOURCE) | events["category"].isin(NEWS_EVENTS)   # own blog posts only when a relevant event
    recent = set(events.loc[counts & (events["published"] >= as_of - pd.Timedelta(days=180)), "account_id"])
    leads["recent_activity"] = leads["account_id"].isin(recent)
    leads["readiness"], leads["readiness_why"] = readiness(leads)

    leads["grade"] = leads.apply(gate, axis=1)
    scorable = leads["grade"].isna() | (leads["grade"] == CHECK_FIT)
    elig = leads["grade"].isna()                   # on target: these are tiered
    scored = score_accounts(leads.loc[scorable], as_of, SCORING)
    for k in scored.columns:
        if not k.startswith("_"):
            leads.loc[scorable, k] = scored[k]
    # website activity is not part of lead scoring (0 points), so it is not an "estimated" part either
    leads["estimated_fields"] = leads["estimated_fields"].map(
        lambda s: (", ".join(x for x in str(s).split(", ") if x != "Website") or None) if isinstance(s, str) else s)
    # tiers within each Apollo list (D3, per list since 18 Nov), ranked on the score and then readiness; exact ties share the higher tier
    key = leads.loc[elig, "priority_score"].astype(float) * 10 + leads.loc[elig, "readiness"]
    leads["tier"] = None
    leads.loc[elig, "tier"] = percentile_tier(key, leads.loc[elig, TIER_GROUP], SCORING)
    leads.loc[elig, "grade"] = leads.loc[elig, "tier"]
    leads["team"] = TEAM
    leads["act_now"] = leads["act_now_triggers"].notna() & scorable
    leads["_news_by_cat"] = leads["account_id"].map(news_by_category(events, as_of))
    allchips = leads.apply(lambda r: chips(r, as_of), axis=1)
    # Why = relevant signals only (decision 2026-11-18); service lines, pitch and group membership go to the company profile
    leads["chips"] = allchips.map(lambda cs: [c for c in cs if c[1] not in PROFILE_KINDS])
    leads["profile_chips"] = allchips.map(lambda cs: [c for c in cs if c[1] in PROFILE_KINDS])
    order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2, CHECK_FIT: 3, "Existing client": 4, DUPLICATE: 5, "Excluded: distressed": 6}
    leads["_o"] = leads["grade"].map(order)
    leads = leads.sort_values(["_o", "priority_score", "readiness"], ascending=[True, False, False]).drop(columns="_o")
    return leads.reset_index(drop=True)


# ---------------------------------------------------------------- 5. readout + outputs
def readout(leads, events, apollo_files, n_contacts):
    L = leads
    news_checked = L["news_status"].isin(["found", "checked, nothing found"])
    counted = events
    by_src = counted.groupby("source").size().to_dict() if len(counted) else {}
    return {
        "apollo_files": [os.path.basename(f) for f in apollo_files], "contacts": int(n_contacts), "companies": int(len(L)),
        "news_checked": int(news_checked.sum()), "news_found": int((L["news_status"] == "found").sum()),
        "news_events": int(L["news_signal"].isin(NEWS_EVENTS).sum()),
        "news_events_high": int((L["news_signal"].isin(NEWS_EVENTS) & L["signal_confidence"].eq("high")).sum()),
        "articles_counted": int(len(counted)), "articles_by_source": by_src,
        "articles_to_review": int(L["news_to_review"].fillna(0).sum()),
        "website_profiles": L["website_profile"].fillna("not built").str.split(":").str[0].value_counts().to_dict(),
        "jobs_status": L["jobs_status"].fillna("not checked").str.split(":").str[0].value_counts().to_dict(),
        "filings_status": L["filings_status"].fillna("not checked").value_counts().to_dict(),
        "funding_labels": int(L["apollo_latest_funding"].notna().sum()),
        "funding_dated": int((L["apollo_latest_funding"].notna() & L["news_signal"].isin(["Funding round", "PE buyout", "M&A"])).sum()),
        "parents": int(L["parent_name"].notna().sum()), "parent_events": int(L["parent_signal"].notna().sum()),
        "parent_scored": int((L["news_from"] == "parent").sum()),
        "own_site_only": int(((L["news_signal"].isin(["None"]) | L["news_signal"].isna()) & (L["own_site_posts"] > 0)).sum()),
        "ownership": L["ownership"].value_counts().to_dict(),
        "ownership_checks": int(L["ownership_check"].notna().sum()),
    }


def lead_signals(r, e):
    """Signal types a lead has, for the page's "Has these signals" filter. Present, not necessarily the scored one."""
    out = []
    if e is not None:
        src = e["source"].fillna("")
        if (e["category"].isin(NEWS_EVENTS) & ~src.isin(["cqc", "fts"])).any():
            out.append("news")                         # a news event (publisher, own site or hand-labelled)
        if (src == "cqc").any():
            out.append("cqc")
        if (src == "fts").any():
            out.append("contract")
    if not blank(r.get("job_postings_30d")) and r["job_postings_30d"] > 0:
        out.append("hiring")                           # roles Cloudstaff fills, posted in the last 30 days
    if r.get("parent_signal") in NEWS_EVENTS:
        out.append("parent")
    if not blank(r.get("competitor_client")):
        out.append("competitor")
    if not blank(r.get("match_review")):
        out.append("review")
    if not blank(r.get("scoring_events")) and r["scoring_events"] > 1:
        out.append("multi")
    if any(c[1] == "fit" for c in r.get("chips") or []):
        out.append("fit")
    if not blank(r.get("filing_signal")) and r["filing_signal"] != "None":
        out.append("filing")
    return out


def save(leads, contacts, events, parent_events, jobs_by_lead, info, name, as_of):
    cols_out = [c for c in leads.columns if not c.startswith("_") and c not in ("chips", "profile_chips")]
    xlsx = DATA_DIR / f"lead_grades_{name}.xlsx"
    with pd.ExcelWriter(xlsx) as w:
        leads.assign(reasons=leads["chips"].map(lambda cs: "; ".join(c[0] for c in cs)), profile=leads["profile_chips"].map(lambda cs: "; ".join(c[0] for c in cs)))[["reasons", "profile"] + cols_out].to_excel(w, sheet_name="leads", index=False)
        contacts.to_excel(w, sheet_name="contacts", index=False)
        events.to_excel(w, sheet_name="news_articles", index=False)
        parent_events.to_excel(w, sheet_name="parent_news_articles", index=False)
        pd.DataFrame([{"key": k, "value": json.dumps(v) if isinstance(v, (dict, list)) else v} for k, v in info.items()]).to_excel(w, sheet_name="run_info", index=False)
    rows = []
    ev_by = {k: g.sort_values("published_at", ascending=False) for k, g in events.groupby("account_id")}
    # parent articles shown on the lead: its relevant events first, then its newest other news (max 3, marked "parent")
    pev_by = {k: g.assign(_e=g["category"].isin(NEWS_EVENTS)).sort_values(["_e", "published_at"], ascending=False)
              for k, g in parent_events.groupby("parent_id")}
    con_by = {k: g for k, g in contacts.groupby("account_id")}
    cqc_by, con_awards = {}, {}
    if CQC_LOCATIONS.exists():
        cl = pd.read_csv(CQC_LOCATIONS, dtype=str, keep_default_na=False)
        cl["account_id"] = "AP-" + cl["company_id"].str.replace("^apollo-", "", regex=True)
        cols = ["location_name", "city", "registered_on", "care_home", "beds", "rating", "rating_published", "service_types", "location_id"]
        cqc_by = {k: g.sort_values("registered_on", ascending=False)[cols].to_dict("records") for k, g in cl.groupby("account_id")}
    ca_path = REGISTER_FILES["Find a Tender"]
    if ca_path.exists():
        ca = pd.read_csv(ca_path, dtype=str, keep_default_na=False)
        ca["account_id"] = "AP-" + ca["company_id"].str.replace("^apollo-", "", regex=True)
        cols = ["date", "buyer", "headline", "value", "currency", "cpv_desc", "url", "supplier_name", "match"]
        reviews, names = load_reviews(), dict(zip(leads["account_id"], leads["company_name"]))
        for i, x in ca.iterrows():
            if x["match"] == "name":
                rv = review_of(reviews, names.get(x["account_id"], ""), "Find a Tender", x["url"].rsplit("/", 1)[-1])
                ca.loc[i, "match"] = "rejected" if rv and rv[0] == "rejected" else f"name, confirmed by {rv[1]}" if rv else "name"
        ca = ca[ca["match"] != "rejected"]
        con_awards = {k: g.sort_values("date", ascending=False)[cols].to_dict("records") for k, g in ca.groupby("account_id")}
    fields = (("date", "published_at"), ("category", "category"), ("confidence", "event_confidence"), ("title", "title"),
              ("publisher", "publisher"), ("url", "url"), ("source", "source"))
    for r in leads.to_dict("records"):
        row = {k: jsonable(r.get(k)) for k in cols_out}
        row["chips"], row["profile_chips"] = r["chips"], r["profile_chips"]
        e, pe = ev_by.get(r["account_id"]), pev_by.get(r.get("parent_id"))
        row["news"] = ([] if e is None else [{k: jsonable(getattr(x, f)) for k, f in fields} for x in e.head(8).itertuples()]) + \
                      ([] if pe is None else [{**{k: jsonable(getattr(x, f)) for k, f in fields}, "parent": r.get("parent_name")} for x in pe.head(3).itertuples()])
        row["jobs"] = jobs_by_lead.get(r["account_id"], [])
        row["signals"] = lead_signals(r, e)
        row["event_list"] = r.get("_event_list") or []
        row["cqc_list"] = cqc_by.get(r["account_id"], [])
        row["contracts"] = con_awards.get(r["account_id"], [])
        cg = con_by.get(r["account_id"])
        row["contacts"] = [] if cg is None else [{k: jsonable(v) for k, v in x.items() if k != "account_id"} for x in cg.to_dict("records")]
        rows.append(row)
    S = SCORING
    data = {"meta": {"title": "EMEA Lead Grades", "subtitle": "Apollo leads · UK", "source": "Apollo export + News Scraper",
                     "extract": info["apollo_extract"], "generated": dt.datetime.now().isoformat(timespec="seconds"),
                     "as_of": as_of.strftime("%Y-%m-%d"), "team": TEAM, "fit_country": FIT_COUNTRY,
                     "max_points": S["max_points"][GOAL], "news_strength": NEWS_STRENGTH, "recency": RECENCY,
                     "confidence_factor": CONFIDENCE_FACTOR, "tier_shares": S["tier"], "info": info},
            "qa": info["qa"], "rows": rows}
    js = DATA_DIR / f"lead_grades_{name}.json"
    json.dump(data, open(js, "w", encoding="utf-8"), ensure_ascii=False, allow_nan=False, default=str)
    return xlsx, js


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="apollo_emea")
    ap.add_argument("--apollo", default=str(APOLLO_DIR))
    ap.add_argument("--scraper-out", default=str(SCRAPER_OUT))
    a = ap.parse_args(argv)
    as_of = pd.Timestamp.today().normalize()

    raw, files = extract_apollo(Path(a.apollo))
    leads, contacts = standardise(raw)
    leads, internal_src = match_internal(leads, newest("priority_company_info_combined*.xlsx"))
    leads, events, parent_events, jobs_by_lead, roles_src = add_collected(leads, Path(a.scraper_out), as_of)
    leads = compound_events(leads, events, as_of)
    leads, competitor_src = add_competitor_clients(leads, COMPETITOR_MAP)   # sets prior_bpo_flag (Competitor client points)
    # fit and trend after the target check, which can correct the industry group (Companies House codes come from the scraper)
    leads, fit_src = add_fit(leads, newest("*_Propensity_Extract_prospect_profiles.csv"))
    leads, trend_src = add_trend(leads, TREND_FILE)
    leads = grade(leads, contacts, events, as_of)

    # checks: ids unique, every lead graded, contacts all belong to a lead
    assert leads["account_id"].is_unique, "duplicate account_id"
    assert leads["grade"].notna().all(), "a lead has no grade"
    assert set(contacts["account_id"]) <= set(leads["account_id"]), "contact without a lead"
    extract = max(pd.to_datetime(raw["Primary Email Last Verified At"], errors="coerce", utc=True).dropna()).strftime("%Y-%m-%d")
    qa = [{"step": "Apollo contacts (rows in the export files)", "rows": int(len(raw))},
          {"step": "Companies (one per Apollo account)", "rows": int(len(leads))},
          {"step": "  of which news checked by News Scraper", "rows": int(leads["news_status"].isin(["found", "checked, nothing found"]).sum())},
          {"step": "  of which found in Companies House", "rows": int((leads["filings_status"] == "found in Companies House").sum())},
          {"step": "  of which ownership known (Companies House PSC, Apollo parent or PE news)",
           "rows": int((~leads["ownership"].isin(["Unknown", "Not checked"])).sum())},
          {"step": "Excluded: distressed (administration, liquidation, strike-off)", "rows": int((leads["grade"] == "Excluded: distressed").sum())},
          {"step": "Existing client (sent to the AM, not graded)", "rows": int((leads["grade"] == "Existing client").sum())},
          {"step": "Duplicate (renamed to another lead in the list, not graded)", "rows": int((leads["grade"] == DUPLICATE).sum())},
          {"step": "Graded (Tier 1-3)", "rows": int(leads["grade"].str.startswith("Tier").sum())}]
    info = {"apollo_extract": extract, "internal": internal_src, "fit_profiles": fit_src, "trend": trend_src, "roles": roles_src,
            "competitor_map": competitor_src,
            "hiring_score": HIRING_SCORE, "service_lines": {k: list(v) for k, v in SERVICE_LINES.items()},
            "scoring_profile": "dashboard_v3 (priority_scoring.py)", "qa": qa,
            "readout": readout(leads, events, files, len(contacts))}
    xlsx, js = save(leads, contacts, events, parent_events, jobs_by_lead, info, a.name, as_of)
    print(leads["grade"].value_counts().to_string())
    print(f"wrote {xlsx}\n      {js}")


if __name__ == "__main__":
    main()
