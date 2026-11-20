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
KEEP_ALIVE_UNITS = 2                            # no sales in 90 days: keep this many units at Amazon so the listing stays live (Mich)
FX_TO_GBP = {"UK": 1.0, "US": 0.8, "AU": 0.5}  # fixed rates, used ONLY to order SKUs when several markets are shown together

ACTION_STATUSES = ["Out of stock", "Urgent", "Below target"]   # statuses 1-3: "needs action"

# Requirements set by the client. Not assumptions: the rules must meet these, and verify.py checks them.
REQUIREMENTS = [
    ("Under 4 weeks of cover gets a quantity", "Every SKU with less than 4 weeks of stock cover (available + inbound) must show a recommended replenishment quantity.", "Ramin (via Mich, 2026-11-19)", "Met: the 8-week target and the slow-seller top-up both give these SKUs a quantity above 0."),
]

RULES = [
    ("Weekly demand", "Units sold in the last 30 days, as a weekly rate. If the SKU is out of stock, the 90-day weekly rate when that is higher, so an empty shelf does not look like no demand.", "Plan (stockout-adjusted demand)"),
    ("Stock", "Available at Amazon + inbound (working, shipped and receiving).", "Plan (count stock already on the way)"),
    ("Weeks of cover", "Stock ÷ weekly demand.", "Standard"),
    ("Target cover", "Lead time + buffer: 4 + 4 = 8 weeks in every market.", "Assumed"),
    ("Restock recommendation", "Target cover × weekly demand − stock, rounded up, never below 0 (for SKUs selling 1+ a week; see the two rules below for the others).", "Plan"),
    ("Keep listing alive", "No sales in 90 days: top stock up to 2 units so the listing stays live and in stock; never more. Applies to every listing in the export.", "Mich (her reco sheets: mostly 2 units for SKUs with no sales)"),
    ("Slow sellers", "Selling, but under 1 unit a week: reorder only when stock is below 5, then top up to 10.", "Mich (AU), applied to all markets"),
    ("Cap", "More than 26 weeks of cover is marked Excess: stock that old starts to attract Amazon's aged-inventory fees.", "Mich plus the fee columns in the Amazon report"),
    ("Profit per unit", "Net proceeds ÷ net units sold over the economics window (LICKIMAT TABLE). No match, or 0 units sold: the market's median, marked 'est.'.", "Economics file"),
    ("Profit at stake per week", "Weekly demand × profit per unit. Uses only sales and economics, so it does not depend on the assumed lead time, buffer or cap.", "Plan"),
    ("Loss-making SKUs", "Restocked like any other SKU: an Amazon presence keeps knockoffs and hijackers off the listing. They keep the 'Losing money' flag so the cost stays visible.", "Mich (she restocks them)"),
    ("Order of the list", "Not shown as a number. Status first, numbered by priority (1 Out of stock, 2 Urgent, 3 Below target, 4 OK, 5 Excess, 6 Keep listing alive, 7 No recent sales); within a status, highest profit at stake per week (a loss counts as 0, so loss-makers are not pushed down for losing money); ties go to the lowest cover. With several markets shown, profit is converted to GBP at fixed rates for ordering only.", "Assumed (simple, no weights)"),
]

STATUSES = [  # in priority order
    ("Out of stock", "No available stock and sold in the last 90 days"),
    ("Urgent", "Cover is below the lead time: will run out before new stock can arrive"),
    ("Below target", "Cover is below the target"),
    ("OK", "Cover is between the target and the cap"),
    ("Excess", "Cover is above the 26-week cap"),
    ("Keep listing alive", "No sales in 90 days and under 2 units at Amazon (incl. inbound): send enough to reach 2"),
    ("No recent sales", "No sales in 90 days, 2 or more units already there: no order"),
]

FLAGS = [
    ("Out of stock", "No available stock and sold in the last 90 days."),
    ("Unfulfillable units", "Amazon holds units it cannot sell, e.g. unscannable barcodes (Mich)."),
    ("Aged stock", "Units over 180 days old, which attract aged-inventory fees."),
    ("Price check", "Featured offer is below our price with no sale running: possible unauthorised reseller (Mich)."),
    ("Losing money", "Negative net proceeds over the economics window. Still restocked (brand presence); shown so the cost is visible."),
    ("Several SKUs on one ASIN", "Another SKU on the same ASIN also has stock or sales: check labels before shipping."),
    ("Inbound not moving", "The same units have been shown as shipped-inbound in two snapshots 10+ days apart."),
    ("Amazon alert", "Amazon's own Low traffic or Low conversion alert."),
]

TO_CONFIRM = [
    ("Lead time and buffer per market", "4 weeks lead time + 4 weeks buffer (8-week target) in every market", "Ramin / Mich"),
    ("Cap on weeks of cover", "26 weeks, since aged-inventory fees start from 181 days. Mich said 'no more than a year'", "Ramin / Mich"),
    ("Slow-seller rule scope", "Applied to all markets (Mich described it for AU only)", "Mich"),
    ("What Ramin actually restocked", "We have no record of what Ramin restocked, so the 'New inbound' column estimates it: inbound units now minus inbound units at the previous snapshot. It misses shipments that arrived between snapshots. His pick lists or shipment records would replace the estimate", "Ramin"),
    ("SKU base code", "Base code = the leading LM product code (LM3001GN-DR-FBA-UK → LM3001GN); bundles and test SKUs left unmapped", "Mich (check against the master file)"),
    ("Canada SKUs in the US export", "Kept under US (13 SKUs ending -CA in the latest snapshot)", "Mich"),
    ("Keep every listing alive", "Yes: 2 units for every listing with no sales in 90 days, including bundles, test and -CA SKUs. Ramin may want to retire some listings instead", "Ramin"),
    ("Keep-alive for unmapped SKUs", "Included for now: bundles, test listings ('TESTING ...') and new-item codes get the 2-unit top-up like any other listing (9 SKUs in the latest snapshot). Likely should be excluded", "Ramin / Mich"),
    ("Restock SKUs that lose money", "Yes, for brand presence (what Mich does). Ramin may want to stop some of them", "Ramin"),
    ("How to order SKUs that need action", "Status first, then profit at stake per week. Ramin may weigh other things (launches, hero SKUs, warehouse limits)", "Ramin"),
    ("Exchange rates for ordering across markets", "Fixed, rounded: 1 USD = 0.8 GBP, 1 AUD = 0.5 GBP. Only changes the order when several markets are shown", "You"),
    ("Profit per unit when there is no economics match", "The market's median profit per unit, marked 'est.'", "You"),
    ("Where the data lives", "Raw files stay in the Desktop project folder; built files are written there too, never to the repo", "You"),
]


def approx(v):
    """Round for reading: whole numbers, '<1' for small non-zero values. Calculations never use this."""
    if v is None:
        return "–"
    if v != 0 and abs(v) < 1:
        return "<1" if v > 0 else "-<1"
    return f"{v:,.0f}"


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
    if s90 <= 0 and s30 <= 0:   # no sales in 90 days: hold the listing with a few units, never more
        reco = max(0, math.ceil(KEEP_ALIVE_UNITS - stock))
        if reco:
            return dem, cover, "Keep listing alive", reco, f"No sales in 90 days. Stock {stock:.0f}: top up to {KEEP_ALIVE_UNITS} to keep the listing live."
        return dem, cover, "No recent sales", 0, f"No sales in 90 days. Stock {stock:.0f} already keeps the listing live; no order."

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
        why = f"Slow seller (under {SLOW_SELLER_PER_WEEK:.0f} a week). Stock {stock:.0f}: " + (
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
    why = (f"Sells about {approx(dem)} a week; {stock:.0f} there = about {approx(cover)} weeks. "
           f"Target {target} weeks ≈ {approx(target * dem)} units, so send {reco}.")
    if status == "Excess":
        why += f" Above the {MAX_COVER_WEEKS}-week cap."
    return dem, cover, status, reco, why
