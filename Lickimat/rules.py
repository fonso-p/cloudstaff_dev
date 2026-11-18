"""Replenishment rules and their assumed settings.

Everything a reviewer may want to change lives at the top of this file. The numbers are placeholders until
Ramin and Mich confirm them (see TO_CONFIRM). prep.py imports this module; the dashboard shows these values
on its Rules & assumptions page, so the page and the code cannot drift apart.
"""
import math

MARKETS = ["UK", "US", "AU"]          # markets with Amazon inventory data. DE has sales economics only.

# ---- settings (assumed, to confirm)
LEAD_TIME_WEEKS = {"UK": 4, "US": 4, "AU": 4}   # weeks from deciding to ship until stock is available at Amazon
BUFFER_WEEKS = {"UK": 4, "US": 4, "AU": 4}      # extra weeks of cover on top of the lead time
MAX_COVER_WEEKS = 26                            # above this, stock risks Amazon's aged-inventory fees (from 181 days)
SLOW_SELLER_PER_WEEK = 1.0                      # selling less than this per week = slow seller
SLOW_MIN_UNITS = 5                              # slow seller: reorder only when stock falls below this ...
SLOW_TOPUP_UNITS = 10                           # ... then top up to this

RULES = [
    ("Weekly demand", "Units sold in the last 30 days ÷ 4.3. If the SKU has no available stock, the higher of that and units sold in 90 days ÷ 12.9, so a stockout does not hide demand.", "Plan (stockout-adjusted demand)"),
    ("Stock", "Available at Amazon + inbound (working, shipped and receiving).", "Plan (count stock already on the way)"),
    ("Weeks of cover", "Stock ÷ weekly demand.", "Standard"),
    ("Target cover", "Lead time + buffer: 4 + 4 = 8 weeks in every market.", "Assumed"),
    ("Recommended quantity", "Target cover × weekly demand − stock, rounded up, never below 0.", "Plan"),
    ("Slow sellers", "Under 1 unit a week: reorder only when stock is below 5, then top up to 10.", "Mich (AU), applied to all markets"),
    ("Cap", "More than 26 weeks of cover is marked Excess: stock that old starts to attract Amazon's aged-inventory fees.", "Mich plus the fee columns in the Amazon report"),
    ("Order of the list", "Out of stock, then Urgent, then Below target; within each, lowest weeks of cover first, then highest demand.", "Assumed (no weighted score yet)"),
]

STATUSES = [  # in priority order
    ("Out of stock", "No available stock and sold in the last 90 days"),
    ("Urgent", "Cover is below the lead time: will run out before new stock can arrive"),
    ("Below target", "Cover is below the target"),
    ("OK", "Cover is between the target and the cap"),
    ("Excess", "Cover is above the 26-week cap"),
    ("No activity", "No stock, nothing inbound and no sales in 90 days"),
]

FLAGS = [
    ("Out of stock", "No available stock and sold in the last 90 days."),
    ("Unfulfillable units", "Amazon holds units it cannot sell, e.g. unscannable barcodes (Mich)."),
    ("Aged stock", "Units over 180 days old, which attract aged-inventory fees."),
    ("Price check", "Featured offer is below our price with no sale running: possible unauthorised reseller (Mich)."),
    ("Losing money", "Negative net proceeds over the economics window, but the rules recommend restocking."),
    ("Several SKUs on one ASIN", "Another SKU on the same ASIN also has stock or sales: check labels before shipping."),
    ("Inbound not moving", "The same units have been shown as shipped-inbound in two snapshots 10+ days apart."),
    ("Amazon alert", "Amazon's own Low traffic or Low conversion alert."),
]

TO_CONFIRM = [
    ("Lead time and buffer per market", "4 weeks lead time + 4 weeks buffer (8-week target) in every market", "Ramin / Mich"),
    ("Cap on weeks of cover", "26 weeks, since aged-inventory fees start from 181 days. Mich said 'no more than a year'", "Ramin / Mich"),
    ("Slow-seller rule scope", "Applied to all markets (Mich described it for AU only)", "Mich"),
    ("What Ramin actually sent", "Approximated as the rise in inbound units since the previous snapshot. Replace with his pick lists", "Ramin"),
    ("SKU base code", "Base code = the leading LM product code (LM3001GN-DR-FBA-UK → LM3001GN); bundles and test SKUs left unmapped", "Mich (check against the master file)"),
    ("Canada SKUs in the US export", "Kept under US (13 SKUs ending -CA in the latest snapshot)", "Mich"),
    ("Where the data lives", "Raw files stay in the Desktop project folder; built files are written there too, never to the repo", "You"),
]


def weekly_demand(available, s30, s90):
    """Units per week. Uses the better of the 30- and 90-day rate when the SKU is out of stock."""
    d = s30 / (30 / 7)
    if available <= 0:
        d = max(d, s90 / (90 / 7))
    return d


def assess(m, available, inbound, s30, s90):
    """Return (weekly demand, weeks of cover, status, recommended units, reason)."""
    lead, target = LEAD_TIME_WEEKS[m], LEAD_TIME_WEEKS[m] + BUFFER_WEEKS[m]
    dem = weekly_demand(available, s30, s90)
    stock = available + inbound
    cover = stock / dem if dem > 0 else None
    if dem == 0 and stock == 0:
        return dem, cover, "No activity", 0, "No stock, nothing inbound, no sales in 90 days."

    if dem < SLOW_SELLER_PER_WEEK:
        reco = SLOW_TOPUP_UNITS - stock if stock < SLOW_MIN_UNITS else 0
        if available <= 0 and s90 > 0:
            status = "Out of stock"
        elif stock < SLOW_MIN_UNITS:
            status = "Below target"
        elif cover is not None and cover > MAX_COVER_WEEKS and stock > SLOW_TOPUP_UNITS:
            status = "Excess"
        else:
            status = "OK"
        why = f"Slow seller ({dem:.1f}/wk). Stock {stock:.0f}: " + (
            f"below {SLOW_MIN_UNITS}, top up to {SLOW_TOPUP_UNITS}." if reco else f"at or above {SLOW_MIN_UNITS}, no order.")
        return dem, cover, status, max(0, reco), why

    reco = max(0, math.ceil(target * dem - stock))
    if available <= 0:
        status = "Out of stock"
    elif cover < lead:
        status = "Urgent"
    elif cover < target:
        status = "Below target"
    elif cover > MAX_COVER_WEEKS:
        status = "Excess"
    else:
        status = "OK"
    why = f"{cover:.1f} weeks of cover vs {target}-week target, selling {dem:.1f}/wk."
    if status == "Excess":
        why += f" Above the {MAX_COVER_WEEKS}-week cap."
    return dem, cover, status, reco, why
