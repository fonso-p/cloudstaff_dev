"""Lead grading rules as data: scoring overrides, events, registers, ownership, sub-sectors, targets. README.md section 4 explains each.
Paths are not here: they come from the lead list (config.py) and cloudstaff_dev.common.paths."""

import math

from cloudstaff_dev.common import paths
from cloudstaff_dev.scoring.priority import NEWS_STRENGTH, SCORING_DASHBOARD_V3


# ---------------------------------------------------------------- settings (rules as data; README.md §4 explains each)
# Paths: config.L (the lead list's own files) and common/paths.py (shared inputs). None are set here.
TREND_FILE = paths.SEGMENTS_OUT / "industry_trend.csv"   # scraper segment mode (`segment export`)
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
# The list's own rules (team, fit country, target markets: sub-sectors, pitch, service lines, target codes,
# supplier groups) are in Marketing Intelligence/lead_lists/<list>/list.toml, read through config.L.
NEWS_EVENTS = ["Funding round", "PE buyout", "M&A", "Expansion / new office", "Restructuring", "Leadership change"] + list(NEW_EVENT_STRENGTH)
# Registers (collected by signals/registers/cqc.py and contracts.py, added 20 Nov): dated facts, counted at full
# strength like hand-labelled events. CQC registered-manager changes are shown but not scored: turnover at one home is
# common, and a scored Leadership change would trigger Act now.
REGISTER_SCORED = {"M&A", "Expansion / new office", "Contract / partnership win"}
# Ownership (signals/registers/ownership.py, Companies House PSC register): a flag, never points. BDM feedback
# 23 Nov 2026: companies not owned by a parent, an umbrella group or an investor, and not run on public money, have
# fewer layers of sign-off and buy faster. "Owner-managed" is that target.
OFFICER_ORDER = ["director", "llp designated member", "llp member", "secretary"]   # a person on several companies keeps the first
OWNERSHIP_ORDER = ["Owner-managed", "Owner-managed group", "Part of a corporate group", "Investor-backed",
                   "Charity / not-for-profit", "Public body", "Unknown", "Not checked"]
OWNERSHIP_PRIVATE = {"Owner-managed", "Owner-managed group"}
OWNERSHIP_EVENT_DAYS = 730                         # a PE buyout in the news this recent overrides an older register filing
# Events a person (or Claude) labelled by hand that the classifier missed: they count like news when stronger than the
# lead's own; labelled_by is shown on the page. Columns: company_name, date, category, headline, url, publisher, labelled_by,
# labelled_on, note
CONFIDENCE_FACTOR = {"high": 1.0, "reviewed": 1.0, "medium": 0.5, "low": 0.5}   # decision D2: medium / low events at half strength
# Register matches made on an exact name alone (CQC provider name, contract supplier name) are medium reliability: flagged
# "check match" until a person marks them in L.register_reviews (confirmed: flag cleared; rejected: the match is dropped).
# Columns: company_name, source (CQC | Find a Tender), notice (Find a Tender notice id; blank for CQC), verdict, reviewed_by,
# reviewed_on, note. A flagged match still scores until rejected.
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
HIRING_BANDS = [(1, "1–2"), (3, "3–5"), (6, "6–10"), (11, "11–20"), (21, "21+")]   # open roles (from) -> band, shown as a reason
# Roles we fill (roles.py): posted job titles matched to Staff Central's JP titles. Decision 2026-11-18: hiring points count
# only roles Cloudstaff fills; on-site roles (carers, nurses, cooks...) still show in the hiring chip as context
HIRING_SCORE = "roles_we_fill"                     # "roles_we_fill" or "all" (every open role, the main pipeline's rule)
TIER_GROUP = "lead_list"                           # decision 2026-11-18: tiers are ranked within each Apollo list (separate campaigns)
DUPLICATE = "Duplicate"                            # an Apollo account renamed to another lead in the same list ("X Now Y")
DISTRESS = r"administration|liquidation|strike|dissolved|insolvency|receivership"
# UK SIC that point to another trade. STRONG (furniture, building) always wins. WEAK codes are also how care groups and
# consultancies register their holding company (70100 head offices, 68209 property, 74990 non-trading, 70229 consulting,
# 71122 engineering, 78xxx staffing), so they decide only when there is no other evidence (18 Nov: ASHA Healthcare, Priority
# Care Group, Lab 1 and others are registered that way)
OTHER_TRADE_UK_STRONG = {"31", "41", "42", "43"}
OTHER_TRADE_UK_WEAK = {"68", "70", "71", "74", "78"}
# Competitor client (17 points): candidates' CVs name the lead as a competitor's client. Map from
# "Client Extraction (CS Jobs)/export_client_map.py"; company names only
COMPETITOR_MAP = paths.COMPETITOR_MAP
COMPETITOR_FUZZY = 0.95                           # close-name matches: shown for a person to check, no points
COUNTRY_WORDS = {"UK": "kingdom", "AU": "austral", "US": "united states", "NZ": "zealand", "CA": "canada", "IE": "ireland"}
BAND_EDGES = [(10, "1-10"), (50, "11-50"), (200, "51-200"), (500, "201-500"), (math.inf, "500+")]
FIT_SIZE_EDGES = [0, 10, 50, 200, math.inf]                 # = Client Propensity config.SIZE_BAND_EDGES / LABELS
FIT_SIZE_LABELS = ["1-10", "11-50", "51-200", "201+"]
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
