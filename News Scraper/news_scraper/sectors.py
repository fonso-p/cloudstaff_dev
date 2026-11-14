"""Reference data for sector x region news (segment mode). Everything here is meant to be edited.

SECTOR_TERMS  how each of the 18 industry groups is written about in the news. Used in the search (any one must
              appear in the article) and at export (does the headline or text name the sector?). Group names are
              checked against references/mystaff_industry, the repo's shared industry list.
COUNTRIES     each region: its Google/Bing News edition, GDELT country name, and the words that place an article there.
THEMES        what is happening in the sector, in Cloudstaff's terms. Each theme has:
                query   up to 4 search terms (see MAX_QUERY_WORDS: long queries are cut short by Google)
                rules   regexes that recognise the theme in a headline or article text
                weight  how much it counts towards the segment's tailwind for Cloudstaff (-1..1)
              The first theme whose rules match wins, so the specific ones come first.
"""
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- industry groups (shared taxonomy)
_REF = Path(__file__).resolve().parents[2] / "references" / "mystaff_industry"
try:
    sys.path.insert(0, str(_REF))
    from mystaff_industry import INDUSTRY_GROUPS, INDUSTRY_SECTOR   # group -> HubSpot labels / sector, from industry_mapping.csv
except Exception:                                   # the scraper still runs if the reference folder is missing
    INDUSTRY_GROUPS, INDUSTRY_SECTOR = {}, {}
finally:
    if sys.path and sys.path[0] == str(_REF):
        sys.path.pop(0)

# Plain-English ways the press names each group. Keep them specific: a generic word ("services", "care") pulls in noise.
SECTOR_TERMS = {
    "Technology": ["tech sector", "tech industry", "technology sector", "software companies", "IT services", "SaaS",
                   "tech startups", "tech companies", "cybersecurity industry", "telcos"],
    "Marketing, Media & Creative": ["advertising industry", "marketing agencies", "media industry", "ad agencies", "creative agencies",
                                    "digital agencies", "publishers", "media companies"],
    "Real Estate": ["real estate agents", "real estate agencies", "real estate industry", "property management", "property managers",
                    "commercial property", "property market", "property developers"],
    "Construction & Engineering": ["construction industry", "construction sector", "construction companies", "builders",
                                   "engineering firms", "civil construction", "infrastructure projects", "home builders"],
    "Accounting": ["accounting firms", "accountants", "accountancy", "accounting profession", "accounting industry", "bookkeepers",
                   "audit firms", "tax practitioners", "Big Four accounting", "Big Four firms"],
    "Financial Services": ["financial services", "banks", "lenders", "mortgage brokers", "wealth management", "financial advisers",
                           "fintech", "banking sector"],
    "Insurance": ["insurance industry", "insurers", "insurance brokers", "insurance sector", "underwriters", "claims processing"],
    "Legal": ["law firms", "legal sector", "legal profession", "lawyers", "legal industry", "legal services"],
    "Professional Services": ["consulting firms", "professional services", "recruitment industry", "recruiters", "staffing agencies",
                              "consultancies", "recruitment agencies"],
    "Retail & Consumer Goods": ["retailers", "retail sector", "retail industry", "ecommerce", "online retail", "wholesalers",
                                "consumer goods", "supermarkets"],
    "Hospitality, Travel & Leisure": ["hospitality industry", "hospitality sector", "restaurants", "hotels", "tourism industry",
                                      "travel industry", "cafes", "pubs"],
    "Business & Consumer Services": ["facilities management", "cleaning industry", "security industry", "contact centres",
                                     "call centres", "contact centers", "call centers", "home services"],
    "Non-profit & Public Sector": ["charities", "not-for-profit", "non-profit", "nonprofits", "charity sector", "public sector",
                                   "local councils", "government agencies"],
    "Healthcare & Wellness": ["healthcare", "health care", "aged care", "hospitals", "GP clinics", "general practice", "allied health",
                              "dental practices", "pharmacies", "veterinary clinics"],
    "Education & Training": ["universities", "education sector", "schools", "vocational training", "higher education",
                             "early childhood education", "childcare", "edtech"],
    "Manufacturing & Industrial": ["manufacturing", "manufacturers", "manufacturing sector", "factories", "mining industry",
                                   "industrial sector", "automotive industry"],
    "Transport & Logistics": ["logistics", "freight", "trucking", "supply chain", "transport industry", "warehousing",
                              "shipping companies", "couriers"],
    "Energy & Environment": ["energy sector", "utilities", "renewable energy", "solar industry", "energy retailers", "oil and gas",
                             "waste management"],
}
GROUPS = list(SECTOR_TERMS)
if INDUSTRY_SECTOR and set(GROUPS) != set(INDUSTRY_SECTOR):     # keep in step with the shared taxonomy
    raise ValueError(f"sectors.py: SECTOR_TERMS groups differ from references/mystaff_industry: "
                     f"missing {sorted(set(INDUSTRY_SECTOR) - set(GROUPS))}, unknown {sorted(set(GROUPS) - set(INDUSTRY_SECTOR))}")


def sector_of(group):
    return INDUSTRY_SECTOR.get(group, "")


# ---------------------------------------------------------------- industry evidence (export checks only, not searched)
# The jobs, bodies and jargon of each group. Weaker than SECTOR_TERMS (2 points in a headline, 1 in the lead) because
# they also turn up in other stories. HubSpot's own industry labels for the group are added automatically below.
INDUSTRY_EVIDENCE = {
    "Technology": ["software", "cybersecurity", "cloud computing", "data centres", "data centers", "IT", "developers", "tech", "startups", "MSP"],
    "Marketing, Media & Creative": ["advertising", "advertisers", "marketers", "media agency", "PR agency", "broadcasters", "newsrooms", "adtech"],
    "Real Estate": ["real estate", "rental market", "landlords", "REIA", "REINSW", "estate agents", "conveyancing", "property sales"],
    "Construction & Engineering": ["construction", "tradies", "tradespeople", "civil works", "contractors", "subcontractors", "building approvals",
                                   "Master Builders", "HIA", "engineers", "architects"],
    "Accounting": ["accounting", "CPA", "CPA Australia", "CA ANZ", "Chartered Accountants", "ICAEW", "ACCA", "AICPA", "BAS agents",
                   "tax agents", "auditors", "audit", "bookkeeping", "Tax Practitioners Board", "TPB", "practice owners"],
    "Financial Services": ["banking", "lending", "superannuation", "super funds", "wealth managers", "asset managers", "APRA",
                           "credit unions", "payments", "neobanks", "brokers"],
    "Insurance": ["insurance", "premiums", "claims", "underwriting", "reinsurers", "insurtech", "Insurance Council", "policyholders"],
    "Legal": ["lawyers", "solicitors", "barristers", "law firm", "Law Society", "SRA", "Law Council", "legal practitioners",
              "conveyancers", "paralegals", "legal tech", "legal profession"],
    "Professional Services": ["consultants", "consulting", "recruitment", "HR", "human resources", "staffing", "advisory firms"],
    "Retail & Consumer Goods": ["retail", "shoppers", "stores", "online shopping", "e-commerce", "brands", "FMCG", "grocery"],
    "Hospitality, Travel & Leisure": ["hospitality", "venues", "chefs", "hotel", "tourism", "travel", "accommodation", "bars", "airlines"],
    "Business & Consumer Services": ["facility services", "cleaners", "security guards", "customer service", "contact centre", "call centre",
                                     "BPO", "outsourced services"],
    "Non-profit & Public Sector": ["charity", "volunteers", "donations", "councils", "public servants", "ACNC", "Charity Commission",
                                   "community sector", "government department"],
    "Healthcare & Wellness": ["health", "patients", "GPs", "nurses", "clinicians", "medical", "NDIS", "Medicare", "NHS", "CQC",
                              "AHPRA", "dental", "pharmacy", "care homes", "hospital"],
    "Education & Training": ["education", "students", "teachers", "TAFE", "university", "RTOs", "Ofsted", "early learning", "enrolments"],
    "Manufacturing & Industrial": ["manufacturing", "factory", "production", "mining", "miners", "industrial", "fabrication"],
    "Transport & Logistics": ["logistics", "freight", "transport", "trucking", "trucks", "haulage", "hauliers", "warehouse", "ports",
                              "shipping", "rail freight", "last-mile", "3PL", "fleet"],
    "Energy & Environment": ["energy", "electricity", "gas", "renewables", "solar", "wind farms", "grid", "batteries", "emissions", "recycling"],
}
# HubSpot labels that are too generic to count as evidence on their own
_GENERIC_LABELS = {"design", "research", "internet", "entertainment", "sports", "publishing", "printing", "photography", "events services",
                   "consumer services", "individual", "family services", "executive office", "think tanks", "public safety",
                   "information services", "online media", "oil", "leisure", "textiles", "ranching", "maritime", "import", "export",
                   "consumer goods", "food production", "information technology", "media production", "performing arts", "arts",
                   "crafts", "machinery", "chemicals", "automotive", "cosmetics", "wholesale", "translation", "localization"}
for _g, _labels in INDUSTRY_GROUPS.items():
    for _l in _labels:
        for _part in re.split(r"\s*(?:/|,|&|\band\b|\bor\b)\s*", _l):
            _part = _part.strip().lower()
            if len(_part) > 3 and _part not in _GENERIC_LABELS and _g in INDUSTRY_EVIDENCE:
                INDUSTRY_EVIDENCE[_g].append(_part)
INDUSTRY_EVIDENCE = {g: list(dict.fromkeys(v)) for g, v in INDUSTRY_EVIDENCE.items()}

# Trade press: a publisher that writes for one industry is strong evidence (3 points). Publishers whose name contains one
# of the group's words ("Accountants Daily", "Logistics Manager") count automatically; these are the ones whose name
# doesn't say so. Add the trade press you see in segment_review.csv.
TRADE_PRESS = {
    "Technology": ["iTnews", "CRN", "CRN Australia", "Computer Weekly", "The Register", "TechCrunch", "ZDNet", "Computerworld",
                   "CIO", "ARN", "iTWire", "TechRadar", "Startup Daily", "Information Age"],
    "Marketing, Media & Creative": ["Mumbrella", "B&T", "AdNews", "Campaign", "Campaign Brief", "Marketing Week", "The Drum", "Adweek",
                                    "Ad Age", "Mediaweek", "Press Gazette", "PRWeek", "PR Week"],
    "Real Estate": ["Elite Agent", "Property Industry Eye", "Estate Agent Today", "The Negotiator", "Inman", "The Real Deal", "Property Week",
                    "EG", "Estates Gazette", "realcommercial.com.au", "Real Commercial", "The Urban Developer", "Domain", "realestate.com.au",
                    "Property Update", "The Property Tribune"],
    "Construction & Engineering": ["Building", "The Fifth Estate", "Architecture & Design", "ArchitectureAU", "Construction Enquirer",
                                   "Sourceable", "New Civil Engineer", "Build Australia", "Infrastructure Magazine", "Construction Owners"],
    "Accounting": ["AccountingWEB", "CPA Practice Advisor", "INTHEBLACK", "Acuity", "ICAEW", "ICAEW Insights", "ACCA Global",
                   "Going Concern", "International Accounting Bulletin"],
    "Financial Services": ["Mortgage Business", "Australian Broker", "Money Management", "Investor Daily", "Financial Newswire", "ifa",
                           "FTAdviser", "The Banker", "Finextra", "Fintech Futures", "Banking Day", "Financial Standard", "American Banker"],
    "Insurance": ["Insurance News", "Reinsurance News", "Artemis", "Post Online", "Insurance Insider", "Captive Review"],
    "Legal": ["Lawyers Weekly", "Legal Futures", "Law Gazette", "Law Society Gazette", "Law.com", "Legal Cheek", "Law Society Journal", "LSJ",
              "Proctor", "QLS Proctor", "Law360", "Bloomberg Law", "Legal Business", "Law Society of Scotland", "Legal Insider",
              "Australasian Lawyer", "The Lawyer", "Legal IT Insider", "Artificial Lawyer"],
    "Professional Services": ["HR Leader", "HRD", "Human Resources Director", "HRD Australia", "Personnel Today", "People Management", "SHRM",
                              "Consultancy.uk", "Consultancy.com.au", "Staffing Industry Analysts", "HR Dive", "Recruiter", "HRM Online"],
    "Retail & Consumer Goods": ["The Grocer", "Ragtrader", "Drapers", "Food & Drink Business", "Retail Week", "Power Retail", "Modern Retail"],
    "Hospitality, Travel & Leisure": ["The Caterer", "Skift", "TTG", "Travel Weekly", "Hospitality Net", "Hotel Management", "Bars and Clubs",
                                      "Big Hospitality", "Restaurant Business", "Nation's Restaurant News", "Executive Traveller"],
    "Business & Consumer Services": ["FM Magazine", "Facilities Management Journal", "Inside FM", "Security Info Watch", "CX Today",
                                     "Cleaning & Maintenance Management", "FM Media"],
    "Non-profit & Public Sector": ["Pro Bono Australia", "Third Sector", "Civil Society", "Chronicle of Philanthropy", "Charity Times",
                                   "Government News", "The Mandarin", "Local Government News", "Civil Service World", "Public Finance"],
    "Healthcare & Wellness": ["HSJ", "Health Service Journal", "Pulse Today", "Nursing Times", "Australian Ageing Agenda", "Medical Republic",
                              "newsGP", "Australian Doctor", "InSight+", "BMJ", "The BMJ", "Care Home Professional", "Homecare Insight",
                              "Pharmacy Daily", "AJP", "Dentistry.co.uk", "Nuffield Trust", "The King's Fund", "MobiHealthNews",
                              "Digital Health", "HTN", "Health Tech Newspaper", "PharmaDispatch", "Healthcare IT News", "Hospital + Healthcare"],
    "Education & Training": ["Times Higher Education", "Campus Morning Mail", "EducationHQ", "Schools Week", "FE Week", "Tes",
                             "Inside Higher Ed", "EdSurge", "The Sector", "Education Review", "University World News"],
    "Manufacturing & Industrial": ["Manufacturers' Monthly", "Mining Weekly", "IndustryWeek", "Machine Maker", "Australian Mining",
                                   "Mining.com", "The Manufacturer", "Manufacturing Today"],
    "Transport & Logistics": ["Big Rigs", "Freightwaves", "FreightWaves", "Transport Topics", "Lloyd's List", "The Loadstar", "Container News",
                              "Port Technology", "Prime Mover", "Owner//Driver", "Fully Loaded", "Motor Transport", "Transport Intelligence",
                              "Splash247", "Air Cargo News", "Rail Business UK", "Railway Gazette", "WorldCargo News", "The Maritime Executive",
                              "Inside Logistics", "Logistics Business", "MHD Supply Chain", "Supply Chain Dive"],
    "Energy & Environment": ["RenewEconomy", "Energy Voice", "Recharge", "PV Magazine", "pv magazine", "Current±", "Inside Waste",
                             "Energy Live News", "Energy Magazine", "Utility Magazine", "Waste Management Review", "Energy-Storage.news"],
}
_TRADE = {n.lower(): g for g, names in TRADE_PRESS.items() for n in names}
_TRADE["real estate"] = "Real Estate"          # realestate.com.au's news section appears as "Real Estate"

# Scoring only (not searched): the industry's own workers and bodies, specific enough to count as the sector in a headline
# (3 points). Found by spot checks: "Calls for national response to truck driver shortage" scored only 2 on "truck".
SECTOR_STRONG = {
    "Transport & Logistics": ["truck drivers", "truckies", "truckie", "road freight", "road transport industry", "heavy vehicle operators",
                              "transport operators", "freight operators", "logistics providers"],
    "Healthcare & Wellness": ["GPs", "nurses", "nursing homes", "care homes", "aged care providers", "pharmacists", "dentists", "NDIS providers"],
    "Legal": ["solicitors", "barristers", "law society", "legal aid"],
    "Accounting": ["auditors", "tax agents", "accounting firm", "accountancy firm", "chartered accountants"],
    "Real Estate": ["landlords", "real estate agent", "estate agents", "property managers", "rental market", "housing market", "home prices",
                    "house prices"],
}

# Other meanings of a group's words. Text matching these is removed before the sector and evidence words are counted,
# so "taken to hospital" is not healthcare news and "his lawyer said" is not legal-sector news.
SECTOR_EXCLUDE = {
    "Accounting": [r"big (four|4) banks?", r"\baccountab", r"\bpublic accounts committee\b"],
    "Financial Services": [r"\b(food|blood|river|sperm|seed|data|memory|power|tissue|toy|clothing|milk) banks?\b", r"\bbanks? of the\b",
                           r"\bbank(s|ing)? on\b", r"\bpiggy bank"],
    "Legal": [r"\b(his|her|their|its|the|a|defen[cs]e|prosecution|family'?s?|families'?|victim'?s?|accused'?s?)\s+(lawyers?|solicitors?|legal team|barristers?)\b",
              r"\b(lawyers?|solicitors?|barristers?) (for|representing|acting for|acting on behalf of)\b",
              r"\blegal (action|challenge|battle|fight|bid|proceedings|threat)s?\b",
              r"\b(court|judge|jury|magistrate|tribunal) (heard|told|found|ruled|was told)\b"],
    "Healthcare & Wellness": [r"\b(taken|rushed|admitted|airlifted|flown|transported|died|dies|treated) (to|in|at) (a |the )?(local )?hospital\b",
                              r"\bin hospital\b", r"\bhospitali[sz]", r"\bin (a )?(stable|critical|serious) condition\b", r"\bhealth (and|&) safety\b",
                              r"\bfinancial health\b", r"\beconomic health\b"],
    "Real Estate": [r"\bintellectual property\b", r"\bproperty (rights|damage|crime)\b"],
    "Construction & Engineering": [r"\b(confidence|team|muscle|community|nation|brand|bridge|relationship)[- ]build(ers?|ing)\b",
                                   r"\bsocial engineering\b", r"\bfinancial engineering\b"],
    "Transport & Logistics": [r"\b(event|wedding|military|election) logistics\b", r"\blogistics (of|behind|involved)\b", r"\blogistical\b"],
    "Manufacturing & Industrial": [r"\bmanufactur(ed|ing) (consent|crisis|outrage|evidence)\b"],
    "Education & Training": [r"\bschools? of (thought|fish)\b", r"\bold school\b", r"\bschool run\b"],
    "Retail & Consumer Goods": [r"\bretail (investors?|traders?|banking|bank|electricity|energy|price|prices|bonds?)\b"],
    "Insurance": [r"\bnational insurance\b"],
    "Hospitality, Travel & Leisure": [r"\bhotel quarantine\b", r"\btravel (ban|bans|restrictions|warning|advice)\b"],
    "Energy & Environment": [r"\b(gas|energy) (lighting|drinks?)\b"],
}
_EXCLUDE_RX = {g: re.compile("|".join(f"(?:{p})" for p in pats), re.I) for g, pats in SECTOR_EXCLUDE.items()}


def strip_other_meanings(group, text):
    rx = _EXCLUDE_RX.get(group)
    return rx.sub(" ", text) if rx and text else (text or "")


def trade_press_group(publisher):
    """The group a publisher writes for: the TRADE_PRESS list, else a group word in its name. None for general press."""
    name = (publisher or "").strip()
    if not name:
        return None
    if name.lower() in _TRADE:
        return _TRADE[name.lower()]
    for g in GROUPS:                       # "Accountants Daily", "Logistics Manager", "Aged Care Insite"
        if _NAME_RX[g].search(name):
            return g
    return None


# ---------------------------------------------------------------- regions (countries)
# query:   region words added to the search (any one must appear in the article)
# places:  words that place a headline in the country at export (case-sensitive where marked by capitals)
# tlds:    publisher domains in the country
# gdelt:   GDELT sourcecountry name
COUNTRIES = {
    "AU": {"name": "Australia", "query": ["Australia", "Australian", "Sydney", "Melbourne"],
           "places": ["Australia", "Australian", "Australians", "Aussie", "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Canberra",
                      "Hobart", "Darwin", "Gold Coast", "NSW", "New South Wales", "Victoria", "Victorian", "Queensland", "WA",
                      "Western Australia", "South Australia", "Tasmania", "ACT", "ASX", "ATO", "RBA", "ASIC", "ACCC", "Fair Work"],
           "tlds": [".au"], "gdelt": "australia"},
    "NZ": {"name": "New Zealand", "query": ["New Zealand", "NZ", "Auckland", "Wellington"],
           "places": ["New Zealand", "NZ", "Kiwi", "Kiwis", "Auckland", "Wellington", "Christchurch", "Hamilton", "Tauranga", "Dunedin",
                      "Aotearoa", "NZX"],
           "tlds": [".nz"], "gdelt": "newzealand"},
    "UK": {"name": "United Kingdom", "query": ["UK", "Britain", "British", "England"],
           "places": ["UK", "U.K.", "Britain", "British", "England", "English", "London", "Scotland", "Scottish", "Wales", "Welsh",
                      "Northern Ireland", "Manchester", "Birmingham", "Leeds", "Glasgow", "Edinburgh", "Bristol", "NHS", "FTSE", "HMRC",
                      "Ofsted", "Ofgem", "FCA"],
           "tlds": [".uk"], "gdelt": "unitedkingdom"},
    "US": {"name": "United States", "query": ["US", "U.S.", "United States", "American"],
           "places": ["US", "U.S.", "USA", "United States", "America", "American", "Americans", "New York", "California", "Texas",
                      "Florida", "Chicago", "Washington", "Wall Street", "Silicon Valley", "Nasdaq", "NYSE", "SEC", "IRS", "Medicare",
                      "Medicaid"],
           "tlds": [".us"], "gdelt": "unitedstates"},
    "CA": {"name": "Canada", "query": ["Canada", "Canadian", "Toronto", "Ontario"],
           "places": ["Canada", "Canadian", "Canadians", "Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa", "Ontario", "Quebec",
                      "Alberta", "British Columbia", "TSX"],
           "tlds": [".ca"], "gdelt": "canada"},
    "PH": {"name": "Philippines", "query": ["Philippines", "Filipino", "Manila", "Cebu"],
           "places": ["Philippines", "Philippine", "Filipino", "Filipinos", "Manila", "Cebu", "Davao", "Makati", "Taguig", "PSE"],
           "tlds": [".ph"], "gdelt": "philippines"},
    "SG": {"name": "Singapore", "query": ["Singapore", "Singaporean"],
           "places": ["Singapore", "Singaporean", "SGX", "MAS"], "tlds": [".sg"], "gdelt": "singapore"},
    "IE": {"name": "Ireland", "query": ["Ireland", "Irish", "Dublin"],
           "places": ["Ireland", "Irish", "Dublin", "Cork", "Galway"], "tlds": [".ie"], "gdelt": "ireland"},
}
# Publishers whose home country is clear but whose domain doesn't say so (.com). Matched on the publisher name Google or
# Bing gives. A starter list: add the trade press you see in segment_review.csv ("publisher not known").
PUBLISHERS = {
    "AU": ["AFR", "Australian Financial Review", "The Australian", "news.com.au", "SmartCompany", "Accountants Daily", "Accounting Times",
           "Lawyers Weekly", "Mortgage Business", "Real Estate Business", "Inside Retail", "Retail World", "Aged Care Insite",
           "Australian Ageing Agenda", "InDaily", "Crikey", "The Conversation Australia", "SBS", "9News", "7NEWS", "Sky News Australia",
           "HR Leader", "Human Resources Director Australia", "Insurance Business Australia", "Mirage News", "Startup Daily",
           "ABC News (Australia)", "ABC (Australian Broadcasting Corporation)", "Sydney Morning Herald", "The Age", "Herald Sun",
           "The Courier-Mail", "The West Australian", "Canberra Times", "Construction Owners", "Big Rigs", "Food & Drink Business"],
    "NZ": ["Stuff", "RNZ", "NZ Herald", "New Zealand Herald", "Newsroom", "BusinessDesk", "1News", "The Post", "Otago Daily Times",
           "interest.co.nz", "National Business Review", "NBR", "The Spinoff", "Scoop", "NZ Adviser"],
    "UK": ["BBC", "Financial Times", "The Times", "The Telegraph", "Sky News", "City AM", "City A.M.", "Accountancy Age", "AccountingWEB",
           "Evening Standard", "The Independent", "Personnel Today", "Retail Gazette", "The Grocer", "Law Gazette", "Legal Futures",
           "Construction News", "Building", "Nursing Times", "HSJ", "Health Service Journal", "Pulse Today", "Care Home Professional",
           "Insurance Times", "Property Industry Eye", "The Caterer", "Big Hospitality", "Manchester Evening News", "This is Money",
           "Daily Mail", "The Guardian", "Yorkshire Post", "The Scotsman", "Herald Scotland", "Business Live", "Insider Media"],
    "US": ["CNBC", "Wall Street Journal", "WSJ", "New York Times", "Fortune", "Business Insider", "Axios", "CPA Practice Advisor",
           "Accounting Today", "Becker's Hospital Review", "Fierce Healthcare", "Modern Healthcare", "Law.com", "Bloomberg Law",
           "Inman", "The Real Deal", "Supply Chain Dive", "Retail Dive", "HR Dive", "Restaurant Business", "Nation's Restaurant News",
           "Freightwaves", "FreightWaves", "Los Angeles Times", "Washington Post", "USA Today", "NPR", "Fox Business", "CBS News",
           "NBC News", "ABC News", "Insurance Journal"],
    "CA": ["CBC", "Globe and Mail", "The Globe and Mail", "Financial Post", "CTV News", "Toronto Star", "BNN Bloomberg", "Global News",
           "National Post", "Canadian Accountant", "Benefits Canada"],
    "PH": ["Inquirer", "Philstar", "BusinessWorld", "Rappler", "GMA News", "Manila Bulletin", "BusinessMirror", "Manila Times", "ABS-CBN",
           "Philippine News Agency", "Daily Tribune", "Malaya Business Insight"],
    "SG": ["Straits Times", "The Straits Times", "Business Times", "CNA", "TODAY"],
    "IE": ["Irish Times", "The Irish Times", "Irish Independent", "RTE", "RTÉ", "Business Post", "Silicon Republic", "TheJournal.ie"],
}
_PUB = {n.lower(): c for c, names in PUBLISHERS.items() for n in names}


def publisher_country(name):
    return _PUB.get((name or "").strip().lower())


# Places outside the segment countries, so a headline or dateline about them counts against every segment ("elsewhere").
OTHER_PLACES = ["China", "Beijing", "Shanghai", "Hong Kong", "Taiwan", "Japan", "Tokyo", "Korea", "Seoul",
                "India", "Mumbai", "Delhi", "Bengaluru", "Bangalore", "Pakistan", "Bangladesh", "Sri Lanka", "Malaysia",
                "Kuala Lumpur", "Indonesia", "Jakarta", "Vietnam", "Thailand", "Bangkok", "Germany",
                "Berlin", "France", "Paris", "Spain", "Italy", "Netherlands", "Amsterdam",
                "Belgium", "Sweden", "Norway", "Denmark", "Finland", "Poland", "Switzerland", "Europe", "EU", "Brussels",
                "Russia", "Moscow", "Ukraine", "Kyiv", "Israel", "Gaza", "Iran",
                "Saudi", "UAE", "Dubai", "Abu Dhabi", "Qatar", "Egypt", "Turkey", "Nigeria", "Kenya", "Uganda", "Ghana",
                "South Africa", "Brazil", "Mexico", "Argentina", "Chile", "Colombia", "Africa", "Middle East", "Latin America",
                "Uzbekistan", "Kazakhstan", "Azerbaijan",
                # added after spot checks ("Sudan's healthcare system on brink of collapse" counted for Healthcare x UK via BBC)
                "Sudan", "Zimbabwe", "Ethiopia", "Somalia", "Tanzania", "Rwanda", "Zambia", "Morocco", "Algeria", "Tunisia", "Libya",
                "Lagos", "Nairobi", "Cairo", "Lebanon", "Syria", "Iraq", "Afghanistan", "Yemen", "Karachi", "Lahore", "Dhaka", "Nepal",
                "Myanmar", "Cambodia", "Fiji", "Portugal", "Greece", "Austria", "Hungary", "Czech", "Romania", "Bulgaria", "Serbia",
                "Croatia", "Peru", "Venezuela", "Caribbean", "Asia"]
# Wire services and global outlets: they write about everywhere, so their home country is never "learned" from headlines.
GLOBAL_PUBLISHERS = ["Reuters", "Bloomberg", "Bloomberg.com", "AP News", "Associated Press", "AFP", "Yahoo", "Yahoo Finance", "Yahoo News",
                     "MSN", "Business Wire", "PR Newswire", "GlobeNewswire", "Globe Newswire", "EIN Presswire", "Forbes", "CNN", "Al Jazeera",
                     "The Economist", "Financial Times", "Fortune", "TradingView", "Investing.com", "MarketScreener", "Morningstar",
                     "Seeking Alpha", "Simply Wall St", "Kalkine", "Kalkine Media", "Medianet News Hub", "Mirage News", "LinkedIn", "Medium",
                     "Google News", "The Business Times", "Euronews", "Devdiscourse", "Barchart", "Benzinga", "Zawya", "Law.asia"]
_GLOBAL = {p.lower() for p in GLOBAL_PUBLISHERS}


def is_global_publisher(name):
    return (name or "").strip().lower() in _GLOBAL


COUNTRY_ALIAS = {"GB": "UK", "USA": "US", "AUS": "AU", "NZL": "NZ"}


def country_code(c):
    c = (c or "").strip().upper()
    return COUNTRY_ALIAS.get(c, c)


# Google News reads only about the first 32 words of a query (OR and the date filter count) and silently drops the rest,
# so segment queries are kept under this many words: the sector terms are split across several queries when needed.
MAX_QUERY_WORDS = 28

# ---------------------------------------------------------------- themes
STAFF = (r"(staff|staffing|workers?|workforce|labou?r|talent|skills?|employees?|nurses?|teachers?|accountants?|drivers?|truckies|chefs?|"
         r"carers?|tradies|engineers?|doctors?|GPs?|pharmacists?|lawyers?|solicitors?|auditors?|agents?|people|personnel)")
THEMES = [
    ("Offshoring / outsourcing", 1.0,
     ["offshoring", "outsourcing", "offshore staff", "offshore teams"],
     [r"\boffshor(e|ed|es|ing)\b(?! wind)(?! (oil|gas|drilling|rig|platform|field|account|trust|tax|bank|company|structure|detention|processing|investors?|buyers?|owners?|"
      r"business|entit(y|ies)|students?|purchasers?|capital|funds?))",
      r"\boutsourc", r"\bnearshor", r"\bvirtual assistants?\b", r"\bbpo\b", r"\bglobal (talent|workforce|teams?)\b",
      r"\bremote (staff|teams?|workers) (from|in|based in) (the )?(philippines|india|overseas|offshore)"]),
    ("Labour shortage", 1.0,
     ["skills shortage", "staff shortage", "workforce shortage", "labour shortage"],
     [STAFF + r" shortages?\b", r"\bshortages? of " + STAFF, r"\bshort-?staffed\b|\bunderstaffed\b|\bunderstaffing\b",
      r"\bstruggl\w* to (hire|recruit|fill|find (staff|workers|people|talent))", r"\bhard[- ]to[- ]fill\b|\bunfilled (roles|jobs|positions|vacancies)",
      r"\b(recruitment|hiring|retention|staffing) (crisis|challenges?|woes|struggles?|pressures?)\b", r"\b(burnout|burnt out|burned out)\b",
      r"\b(job )?vacancies (rise|rises|soar|soars|surge|surges|remain high|hit)"]),
    ("Cost pressure", 0.8,
     ["rising costs", "cost pressures", "wage increase", "margins"],
     [r"\b(rising|soaring|surging|higher|spiralling|ballooning) (costs?|wages|wage bills?|overheads|rents?|insurance premiums|energy (bills|prices))",
      r"\bcost (pressures?|blowouts?|squeeze|crisis|of doing business)\b", r"\bmargins? (squeeze|pressure|under pressure|shrink|shrinking|hit)\b|\bsqueezed? margins?\b",
      r"\b(minimum|award) wage (rise|rises|increase|increases|hike|hikes|decision)\b|\bwage (rise|rises|increases?|hikes?|growth|bill)\b",
      r"\bpayroll tax\b|\bnational insurance (rise|increase|hike)", r"\bprofits? (squeezed|hit|fall|falls|slump|slumps|plunge|plunges)\b"]),
    ("Restructuring / layoffs", 0.3,
     ["layoffs", "job cuts", "redundancies", "restructuring"],
     [r"restructur(?!ing (appointments?|partners?|teams?|practices?|advis\w*|specialists?|experts?|directors?|services|hires?))", r"lay-?offs?\b|lays off|laying off|laid\s*-?\s*off", r"\bjob (cuts?|losses)\b", r"redundanc", r"downsiz",
      r"\b(cuts?|cutting|slash(es|ed|ing)?|shed(s|ding)?|axe[sd]?|axing)\b.{0,40}\b(jobs?|roles?|staff|workers|employees|workforce|positions)\b"]),
    ("Consolidation / M&A", 0.5,
     ["acquisition", "merger", "consolidation", "private equity"],
     [r"\bacquires?\b|\bacquired\b|\bacquisitions?\b", r"\bmergers?\b|\bmerges?\b", r"takeover", r"\bconsolidat",
      r"private equity|\bpe[- ](backed|firms?|investors?|money)\b", r"\broll-?ups?\b", r"\b(buys|snaps up|swoops on)\b"]),
    ("Downturn", -0.3,
     ["downturn", "slump", "insolvency", "collapse"],
     [r"\bdownturn\b|\bslump(s|ed|ing)?\b|\brecession\b", r"\binsolvenc(?!y service)|\bliquidat|\bcollaps(e|es|ed|ing)\b|\b(enters?|into) administration\b|\bbankrupt",
      r"\b(falling|weak|weaker|weakening|slowing|softening|plunging) (demand|sales|activity|orders|bookings)\b",
      r"\b(clearance rates?|prices|values|sales|listings|volumes?|activity|demand|lending|approvals|enrolments|bookings|profits?|revenue) "
      r"(fall|falls|fell|drop|drops|dropped|plunge[sd]?|plummet(s|ed)?|nosedives?|nosedived|slides?|slid|slumps?|slumped|dips?|dipped|tumble[sd]?)\b",
      r"\bclosures?\b|\bclos(e|es|ing) (their|its) doors\b", r"\b(struggling|doing it tough)\b"]),
    ("Regulation / compliance", 0.4,
     ["regulation", "compliance", "reforms", "legislation"],
     [r"\bregulat(ion|ions|or|ors|ory)\b", r"\bcomplian(ce|t)\b", r"\breforms?\b", r"\blegislation\b|\b(new|proposed|draft) (law|laws|bill|rules|standards?)\b",
      r"\bcrackdown\b|\bmandatory\b|\bmandate[sd]?\b", r"\b(audit|reporting|licensing) (requirements|obligations|regime)\b"]),
    ("AI / automation", 0.2,
     ["artificial intelligence", "AI adoption", "automation", "generative AI"],
     [r"\bai\b|\bartificial intelligence\b|\bgen-?ai\b|\bgenerative\b|\bchatgpt\b|\bcopilot\b|\bagentic\b",
      r"\bautomat(e|es|ed|ing|ion)\b|\brobot(s|ics)?\b|\bdigitis|\bdigitiz"]),
    ("Growth / investment", 0.7,
     ["expansion", "record demand", "strong growth", "investment"],
     [r"\bexpan(d|ds|ded|ding|sion)\b", r"\brecord (demand|growth|revenue|profits?|sales|year|numbers|high)\b",
      r"\b(strong|rapid|surging|booming|robust) (growth|demand)\b|\bboom(s|ing)?\b", r"\bsurge in (demand|bookings|orders|sales)\b",
      r"\braise[sd]?\b.{0,40}(\$|£|€|\bm\b|million|billion|funding)|\bfunding round\b|\bseries [a-e]\b",
      r"\b(invest(s|ed|ing)?|investment)\b.{0,30}(\$|£|€|\bm\b|million|billion|\bbn\b)|(\$|£|€)\s?[\d.,]+\s?(m|bn|million|billion)?\s+"
      r"(investment|expansion|facility|hub|upgrade|development)\b",
      r"(\$|£|€)\s?[\d.,]+\s?(k|m|b|bn|million|billion)?\b.{0,25}\binvestment\b|\b(record|major|significant|multimillion|multi-million|"
      r"billion|million)[- ](dollar |pound )?investment\b|\binvestment (surges?|soars?|boosts?|booms?|ramps up|set for record)|"
      r"\b(secures?|attracts?|lands?|pours?|welcomes?) .{0,20}investment\b",
      r"\b(to create|creat(es|ing)) [\d,]+ (new )?jobs\b|\bhiring (spree|push|drive|blitz)\b|\bnew (office|offices|sites?|stores?|clinics?|hub)\b|\bopen(s|ed|ing)? (a |its |an )?(\w+ ){0,2}(office|branch|clinic|hub|practice|depot|warehouse)\b"]),
]
OTHER_THEME = "Other sector news"
THEME_WEIGHT = {name: w for name, w, _, _ in THEMES} | {OTHER_THEME: 0.0}
_THEME_RX = [(name, re.compile("|".join(f"(?:{p})" for p in rules), re.I)) for name, _, _, rules in THEMES]
# proper names that contain theme words: "Solicitors Regulation Authority", "Senate Economics Legislation Committee"
_THEME_NAMES = re.compile(r"\b(Regulation|Regulatory|Legislation|Reform|Compliance|Investment|Insolvency|Restructuring) "
                          r"(Authority|Committee|Commission|Service|Office|Council|Bank|Board|Agency|Act|Bill)\b")



def classify_theme(text, min_hits=1):
    """The theme of a headline (min_hits=1: the first theme whose rules match) or of article text (min_hits=2: the theme with
    the most matches, at least min_hits of them; one stray "AI" or "acquisition" in a lead is not what the story is about)."""
    text = _THEME_NAMES.sub(" ", text or "")
    text = re.sub(r" - (latest )?investment news - [^.]*", " ", text, flags=re.I)     # API Magazine's title suffix
    if min_hits <= 1:
        for name, rx in _THEME_RX:
            if rx.search(text):
                return name
        return None
    best, best_n = None, 0
    for name, rx in _THEME_RX:
        n = sum(1 for _ in rx.finditer(text))
        if n > best_n:
            best, best_n = name, n
    return best if best_n >= min_hits else None


def _q(t):
    return f'"{t}"' if " " in t or not t.replace("-", "").isalnum() else t


def or_group(terms):
    terms = list(dict.fromkeys(t for t in terms if t))
    return _q(terms[0]) if len(terms) == 1 else "(" + " OR ".join(_q(t) for t in terms) + ")"


def _singular(t):
    """'accountants' -> 'accountant', 'charities' -> 'charity' (last word only)."""
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and not t.endswith(("ss", "us", "is")) and len(t) > 3 and t[-2].isalpha() and t[-2].islower():
        return t[:-1]
    return t


def term_regex(terms, case_sensitive=False):
    """Whole-word regex for a list of terms. Singular and plural both count: 'accountants' finds 'accountant',
    'bank' finds 'banks'."""
    alts = sorted({re.escape(v) for t in terms if t for v in (t, _singular(t))}, key=len, reverse=True)
    if not alts:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?<![\w])(?:" + "|".join(alts) + r")(?:s|es|'s)?(?![\w])", 0 if case_sensitive else re.I)


# for publisher names: the group's sector words and its multi-word or distinctive evidence words (not 'IT', 'health', 'plant')
_NAME_RX = {}


def _build_name_rx():
    for g in GROUPS:
        words = SECTOR_TERMS[g] + [w for w in INDUSTRY_EVIDENCE.get(g, []) if (" " in w or len(w) >= 8) and not w.isupper()]
        _NAME_RX[g] = term_regex(words)


def place_regex(country):
    """Place words for a country. All-capital words (UK, NSW, ASX) are matched case-sensitively so 'us' and 'act' don't count."""
    places = COUNTRIES[country]["places"]
    upper = [p for p in places if p.isupper() or "." in p]
    other = [p for p in places if p not in upper]
    return term_regex(other), term_regex(upper, case_sensitive=True)


_build_name_rx()
