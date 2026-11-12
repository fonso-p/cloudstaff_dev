"""Industry and region mappings, identical to the Account Priority Dashboard's
(Marketing Intelligence/format data/format_priority_data.ipynb §0b, BUSINESS_RULES.md §6 and §8), so this
analysis and the dashboard describe a client the same way. The shared copy of the industry rules, with the
reasoning behind each bucket, is references/mystaff_industry/ at the repo root (same values).

Industry: 18 groups under 6 sectors. MyStaff 'Industry Hubspot' first; if it isn't in the taxonomy,
'Industry Roll Up' via ROLLUP_MAP; placeholder roll-ups stay blank.
Region: office address country + state -> 'AU-NSW', 'US', 'UK', 'NZ', 'CA', ... or 'Other'."""
import pandas as pd

INDUSTRY_GROUPS = {   # group -> HubSpot industry values
    "Technology": ["Information Technology and Services", "Computer Software", "Software Development", "Information Services",
                   "Information Technology", "Internet", "Computer Networking", "Computer & Network Security",
                   "Computer Hardware", "Telecommunications"],
    "Real Estate": ["Real Estate", "Commercial Real Estate"],
    "Accounting": ["Accounting"],
    "Construction & Engineering": ["Construction", "Building Materials", "Civil Engineering", "Architecture & Planning",
                                   "Mechanical or Industrial Engineering"],
    "Financial Services": ["Financial Services", "Banking", "Capital Markets", "Investment Management",
                           "Venture Capital & Private Equity", "Mortgage Broker"],
    "Insurance": ["Insurance"],
    "Legal": ["Legal Services", "Law Practice"],
    "Professional Services": ["Management Consulting", "Human Resources", "Staffing and Recruiting", "Executive Office",
                              "Translation and Localization", "Market Research", "Research", "Think Tanks"],
    "Marketing, Media & Creative": ["Marketing and Advertising", "Online Media", "Media Production", "Publishing", "Printing",
                                    "Graphic Design", "Design", "Photography", "Broadcast Media", "Entertainment",
                                    "Performing Arts", "Arts and Crafts"],
    "Healthcare & Wellness": ["Hospital & Health Care", "Medical Practice", "Medical Devices", "Mental Health Care",
                              "Pharmaceuticals", "Alternative Medicine", "Veterinary", "Health, Wellness and Fitness"],
    "Education & Training": ["Education Management", "E-Learning", "Higher Education", "Primary/Secondary Education",
                             "Professional Training & Coaching"],
    "Retail & Consumer Goods": ["Retail", "Ecommerce", "Wholesale", "Apparel & Fashion", "Textiles", "Consumer Goods",
                                "Consumer Electronics", "Cosmetics", "Luxury Goods & Jewelry", "Sporting Goods",
                                "Food & Beverages", "Wine and Spirits", "Food Production", "Ranching"],
    "Hospitality, Travel & Leisure": ["Hospitality", "Leisure, Travel & Tourism", "Restaurants", "Events Services", "Sports"],
    "Business & Consumer Services": ["Facilities Services", "Security and Investigations", "Consumer Services",
                                     "Individual & Family Services"],
    "Manufacturing & Industrial": ["Machinery", "Industrial Automation", "Electrical/Electronic Manufacturing",
                                   "Motor Vehicle Manufacturing", "Automotive", "Chemicals", "Packaging and Containers",
                                   "Mining & Metals"],
    "Transport & Logistics": ["Logistics and Supply Chain", "Transportation/Trucking/Railroad", "Package/Freight Delivery",
                              "Maritime", "Airlines/Aviation", "Import and Export"],
    "Energy & Environment": ["Oil & Energy", "Utilities", "Renewables & Environment", "Environmental Services"],
    "Non-profit & Public Sector": ["Non-Profit Organization Management", "Civic & Social Organization", "Public Safety"],
}

INDUSTRY_SECTOR = {
    "Technology": "Technology & Media", "Marketing, Media & Creative": "Technology & Media",
    "Real Estate": "Property & Construction", "Construction & Engineering": "Property & Construction",
    "Accounting": "Financial & Professional Services", "Financial Services": "Financial & Professional Services",
    "Insurance": "Financial & Professional Services", "Legal": "Financial & Professional Services",
    "Professional Services": "Financial & Professional Services",
    "Retail & Consumer Goods": "Consumer, Hospitality & Services", "Hospitality, Travel & Leisure": "Consumer, Hospitality & Services",
    "Business & Consumer Services": "Consumer, Hospitality & Services", "Non-profit & Public Sector": "Consumer, Hospitality & Services",
    "Healthcare & Wellness": "Health & Education", "Education & Training": "Health & Education",
    "Manufacturing & Industrial": "Industrial, Logistics & Energy", "Transport & Logistics": "Industrial, Logistics & Energy",
    "Energy & Environment": "Industrial, Logistics & Energy",
}

# Values that mean "unknown". Outsourcing/Offshoring is Cloudstaff's own industry stamped on clients by default.
UNCLASSIFIED_INDUSTRY = {"-", "Other", "Outsourcing/Offshoring"}

# Roll Up labels on real clients that carry no industry
PLACEHOLDER_ROLLUP = {"CLOUDSTAFF", "Test Record - No Category", "Cloudstaff Test Account", "-", "No Info Available", "Others"}

# Fallback only: Cloudstaff 'Industry Roll Up' -> industry group
ROLLUP_MAP = {
    "Advanced Technology Services": "Technology", "Software & Technology Development": "Technology",
    "Telecommunications & Information Technology": "Technology", "Information Technology": "Technology", "Internet": "Technology",
    "Real Estate Services": "Real Estate", "Real Estate": "Real Estate",
    "Accounting Services": "Accounting",
    "Comprehensive Financial Services": "Financial Services", "Financial Services": "Financial Services",
    "Construction & Infrastructure": "Construction & Engineering", "Specialized Engineering & Technical Services": "Construction & Engineering",
    "Professional Advisory": "Professional Services", "Business Operations & Enterprise Solutions": "Professional Services",
    "Professional Services": "Professional Services", "Research, Development & Innovation": "Professional Services",
    "Human Resources": "Professional Services",
    "Legal & Security Services": "Legal", "Legal Services": "Legal",
    "Digital Marketing & Advertising": "Marketing, Media & Creative", "Marketing & Advertising": "Marketing, Media & Creative",
    "Marketing Services": "Marketing, Media & Creative", "Creative and Digital Media": "Marketing, Media & Creative",
    "Design, Arts & Entertainment": "Marketing, Media & Creative", "Media & Entertainment": "Marketing, Media & Creative",
    "Publishing, Editing & Literature": "Marketing, Media & Creative",
    "Health & Welfare Services": "Healthcare & Wellness", "Healthcare & Medical Services": "Healthcare & Wellness",
    "Healthcare Services": "Healthcare & Wellness", "Health & Wellness Services": "Healthcare & Wellness",
    "Pharmaceuticals & Life Sciences": "Healthcare & Wellness", "Health & Safety Products": "Healthcare & Wellness",
    "Education & Knowledge Services": "Education & Training", "Professional Coaching & Development": "Education & Training",
    "Retail & Commerce": "Retail & Consumer Goods", "Retail & Consumer Services": "Retail & Consumer Goods",
    "Retail & Consumer Goods": "Retail & Consumer Goods", "Apparel, Fashion & Textiles": "Retail & Consumer Goods",
    "Consumer Products & Electronics": "Retail & Consumer Goods", "Wholesale & Distribution": "Retail & Consumer Goods",
    "Food, Beverage & Agriculture": "Retail & Consumer Goods", "Food & Beverage": "Retail & Consumer Goods",
    "Hospitality, Travel & Leisure": "Hospitality, Travel & Leisure", "Event Management & Services": "Hospitality, Travel & Leisure",
    "Sports, Fitness & Recreation": "Hospitality, Travel & Leisure", "Arts, Entertainment & Recreation": "Hospitality, Travel & Leisure",
    "Personal Care Products & Services": "Business & Consumer Services", "Consumer Services": "Business & Consumer Services",
    "Facilities Management": "Business & Consumer Services",
    "Manufacturing & Industrial Products": "Manufacturing & Industrial", "Manufacturing & Industrial Services": "Manufacturing & Industrial",
    "Automotive & Motor Vehicles": "Manufacturing & Industrial", "Raw Material Extraction & Processing": "Manufacturing & Industrial",
    "Transportation & Logistics": "Transport & Logistics", "Transportation & Logistics Services": "Transport & Logistics",
    "Energy & Environmental Services": "Energy & Environment", "Environmental Services": "Energy & Environment",
    "Social & Civic Organizations": "Non-profit & Public Sector", "Non-Profit Organizations": "Non-profit & Public Sector",
}

INDUSTRY_MAP = {raw: group for group, raws in INDUSTRY_GROUPS.items() for raw in raws}   # HubSpot value -> group

assert len(INDUSTRY_MAP) == sum(map(len, INDUSTRY_GROUPS.values())), "a raw value is in two industry groups"
assert not set(INDUSTRY_MAP) & UNCLASSIFIED_INDUSTRY
assert set(INDUSTRY_GROUPS) == set(INDUSTRY_SECTOR)
assert set(ROLLUP_MAP.values()) <= set(INDUSTRY_GROUPS)

# ---------------------------------------------------------------- region (MyStaff office address)
COUNTRY_CODE = {
    "australia": "AU", "united states of america": "US", "united states": "US", "usa": "US",
    "united kingdom of great britain and northern ireland": "UK", "united kingdom": "UK", "jersey": "UK",
    "new zealand": "NZ", "canada": "CA", "singapore": "SG", "hong kong": "HK", "ireland": "IE",
    "united arab emirates": "AE", "philippines": "PH",
}
AU_STATE = {
    "new south wales": "NSW", "nsw": "NSW", "victoria": "VIC", "vic": "VIC", "queensland": "QLD", "qld": "QLD",
    "south australia": "SA", "sa": "SA", "western australia": "WA", "wa": "WA",
    "australian capital territory": "ACT", "act": "ACT", "tasmania": "TAS", "tas": "TAS",
    "northern territory": "NT", "nt": "NT",
}

# Region code -> the country level our models use (small countries pooled as "Other")
REGION_COUNTRY = {"US": "United States", "UK": "United Kingdom", "NZ": "New Zealand", "CA": "Canada"}

def region_code(country, state):
    """Same rule as the dashboard's mystaff_region(): AU-<state> (or AU), a short country code, or Other."""
    if pd.isna(country) or str(country).strip() in ("", "-", "0"):
        return None
    c = COUNTRY_CODE.get(str(country).strip().lower(), "Other")
    if c == "AU":
        s = AU_STATE.get(str(state).strip().lower())
        return f"AU-{s}" if s else "AU"
    return c

def region_to_country(region):
    if pd.isna(region):
        return "Unknown"
    return "Australia" if str(region).startswith("AU") else REGION_COUNTRY.get(str(region), "Other")
