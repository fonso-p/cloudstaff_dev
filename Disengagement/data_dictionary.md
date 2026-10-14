# Engagement Summary: Data Dictionary

One row per account (`Shortcode`) in the `summary` table, built by `engagement_pipeline.py`. Only four columns come straight from the raw sources; everything else is calculated. A few columns are added later by the Kaplan-Meier cell (`km_curves_cell.py`), and some only appear once `ROLE_COL` is set.

**Source tables**

- `sc_engagement`: one row per hire, with `engagement_date`, `disengagement_date` and `Employment Status`. The pipeline adds an `is_active` column to it (see below).
- `mystaff`: account attributes (Region, Industry Roll Up, Industry Hubspot).

Hires with an `engagement_date` after today haven't started yet and are left out of every count. The raw `sc_engagement` columns are not in `summary`; they feed the calculations below.

**Who counts as active.** A hire is active if its `disengagement_date` is blank, today or later (for example staff serving notice), equal to `ACTIVE_FILL_DATE` if set, or its status is in `ACTIVE_STATUSES`. Every other hire is treated as having left on its disengagement date.

**Column names and definitions follow the config.** Settings at the top of the pipeline control names and rules:

| Setting | Current value | Controls |
|---|---|---|
| `LAUNCH_DAYS` | 14 | Launch-team window (`hc_14d`, `launch_size`, "Launched at 5+") |
| `EARLY_WINDOWS` | 0, 14, 30, 60, 90 | Early-signal `_Nd` columns |
| `HEADCOUNT_MILESTONES` | 5, 10, 20 | `days_till_N_headcount` columns |
| `RAMP_WINDOWS` | see Ramp flags | `reached_N_in_Xd` flags |
| `SMALL_START` | 1–2 | Launch size that counts as a small starter |
| `GROWTH_DAYS` | 730 | Growth tier and high-growth target window |
| `ACTIVE_FILL_DATE` | None (today) | Date the extract uses for still-active staff |
| `ACTIVE_STATUSES` | none | Status values that always mean active |
| `CHURN_GRACE_DAYS` | 30 | How long a zero-headcount gap must last to count as churn |
| `MILESTONE_HOLD_DAYS` | 30 | How long headcount must stay at N+ for a milestone to count |

---

## Raw fields

| Column | Source | Description |
|---|---|---|
| Shortcode | `sc_engagement` | Client/account identifier. One row per account in `summary`. |
| Region | `mystaff` | Account region (e.g. APAC, AMER). |
| Industry Roll Up | `mystaff` | Grouped industry category. Includes placeholder values ("-" and "0") for accounts without a real industry. |
| Industry Hubspot | `mystaff` | Industry as recorded in HubSpot. |

---

## Calculated fields

### Lifecycle

| Column | Definition |
|---|---|
| start_cohort | Quarter of `start_date`. |
| start_date | Earliest date on the account's headcount timeline (first hire date). |
| start_year | Year of `start_date`. |
| engagement_active | 1 if the account has staff today, or dropped to 0 staff within the last 30 days (`churn_pending`). 0 otherwise. |
| end_date | Date the account dropped to 0 staff, for inactive accounts only. Blank for active and pending accounts. |
| engagement_timespan_days | `end_date` − `start_date` in days. Blank for active accounts. |
| days_observed | Today − `start_date`. Measured to today even for churned accounts, so it is the account's age, not its lifespan. |

### Churn and reactivation

A "zero-headcount gap" starts when headcount drops from above 0 to 0 and ends when the account hires again. A same-day start and exit at the very beginning is not a gap. Gaps longer than 30 days are churn; shorter ones that end with a rehire are backfills.

| Column | Definition |
|---|---|
| churn_pending | 1 if the account is at 0 staff today but has been for 30 days or less. Counted as active until the grace period passes. |
| first_churn_date | Start of the first zero-headcount gap longer than 30 days. Blank if the account never churned. |
| days_to_first_churn | `first_churn_date` − `start_date` in days. |
| reactivated | True if the account churned (gap over 30 days) and later hired again. |
| n_reactivations | Number of times the account came back after a churn. Backfill gaps are not counted. |
| n_backfill_gaps | Zero-headcount gaps of 30 days or less that ended with a rehire. |
| first_zero_date | First date headcount dropped to 0, including short backfill gaps. Kept for comparison with `first_churn_date`. |
| days_to_first_zero | `first_zero_date` − `start_date` in days. |
| churned | 1 if `engagement_active` is 0 (built in Step 1). Pending accounts and reactivated accounts with staff today count as 0. |
| churned_after_5 | 1 if the account reached 5 seats and is churned. |
| tenure_days | `engagement_timespan_days` for ended accounts, `days_observed` for active ones. |

### Headcount

| Column | Definition |
|---|---|
| employee_count_at_start | Net active staff on the first timeline date (hires minus exits on that date). |
| start_size_bucket | `employee_count_at_start` binned into "1 to 2", "3 to 5", "6+". Based on day 0 only; prefer `launch_size_bucket`. |
| current_headcount | Active staff today. |
| peak_headcount | Highest headcount the account ever reached, even briefly (not subject to the 30-day hold). |
| peak_date | Date the peak was first reached. |
| days_to_peak | `peak_date` − `start_date` in days. |
| days_till_5_headcount | Days from start to the first day of the first run at 5+ staff that lasted at least 30 days. Brief spikes, such as a replacement overlapping with the person leaving, don't count. Blank if never reached and held. |
| days_till_10_headcount | Same, for 10. |
| days_till_20_headcount | Same, for 20. |

### Hires, exits and attrition volume

| Column | Definition |
|---|---|
| total_hires | Hires in `sc_engagement` for the account that have already started (gross hires). |
| total_exits | Hires that have left: not active by the rule above. Future-dated exits are not counted yet. |
| attrition_exits | Exits where status is Resigned, AWOL or Dismissed. |
| attrition_rate | `attrition_exits` / `total_hires`. |
| exits_Resigned, exits_AWOL, exits_Dismissed | Attrition exits split by status. |

### Early attrition / disengagement timing

| Column | Definition |
|---|---|
| days_to_first_attrition | Days from start to the first attrition exit. |
| days_to_first_disengagement | Days from start to the first exit of any kind. |
| eligible_30d / 60d / 90d | 1 if `days_observed` ≥ the window, else 0. |
| attrition_within_30d / 60d / 90d | 1 if any attrition exit occurred within N days of start. Includes day 0. |
| disengaged_within_30d / 60d / 90d | 1 if any exit of any kind occurred within N days of start. |
| attr_30d_elig / 60d_elig / 90d_elig | `attrition_within_Nd`, set to blank if not eligible. Use these for rates. |
| disengaged_30d_elig / 60d_elig / 90d_elig | Same, for disengagement. |

### Ramp flags

Each flag is 1 if the account reached and held the seat count (see `days_till_N_headcount`) within N days of start, 0 if it didn't, and blank if the account hasn't been observed for N days.

| Column | Windows (days ≈ months) |
|---|---|
| reached_5_in_90d / 180d / 270d / 365d | 3, 6, 9, 12 months |
| reached_10_in_90d / 180d / 365d / 730d | 3, 6, 12, 24 months |
| reached_20_in_365d / 730d / 1095d | 12, 24, 36 months |

### Seat-path cohorts (Step 1)

| Column | Definition |
|---|---|
| seat_path | Mutually exclusive path, based on when 5 seats were reached and held: `0 Launched at 5+` (≤14 days), `1 Fast` (≤90), `2 Slow` (≤365), `3 Very slow` (>365), `4 Never reached - churned`, `5 Never reached - active` (365+ days observed), `6 Too early to tell`. |
| ask_cohort | `seat_path` mapped to the original four groups plus two exclusion buckets: Launched at 5+, Reached 5 quickly, Reached 5 slowly, Churned before 5, Never reached 5, Too early. |
| date_reached_5 | `start_date` + `days_till_5_headcount`. |
| days_after_5 | (`end_date`, or today if active) − `date_reached_5`. |

### Early-signal windows (Step 2)

Each metric exists at day 0, 14, 30, 60 and 90, and is blank if the account hasn't lived through that window. "Hire day" means days since `start_date`. These are point-in-time counts and are not affected by the grace period or the 30-day hold.

| Column pattern | Definition |
|---|---|
| hc_Nd | Headcount at day N: hires by day N who have not left by day N. |
| hires_Nd | Cumulative gross hires with hire day ≤ N. |
| new_hires_Nd | Hires after day 0 and by day N (seats added post-start). Always 0 at day 0. |
| exits_Nd | Of hires by day N, those who left by day N. |
| attr_exits_Nd | Of those exits, the ones with a Resigned, AWOL or Dismissed status. |
| hire_waves_Nd | Number of distinct hiring dates by day N. |
| net_growth_Nd | `hc_Nd` − `hc_0d` (14/30/60/90 only). |
| added_seat_Nd | 1 if `new_hires_Nd` > 0 (14/30/60/90 only). |
| early_attr_rate_Nd | `attr_exits_Nd` / `hires_Nd` (14/30/60/90 only). |

### High-growth framing (Step 3)

| Column | Definition |
|---|---|
| launch_size | Headcount at day 14 (`hc_14d`), so staggered onboarding in the first two weeks counts as one launch. Blank for accounts younger than 14 days. |
| launch_size_bucket | `launch_size` binned into "0 (no staff)", "1 to 2", "3 to 4", "5+". |
| small_starter | 1 if `launch_size` is 1–2, 0 otherwise, blank if `launch_size` is blank. |
| growth_tier_730d | Highest milestone reached and held within 730 days (~24 months): "1 Under 5", "2 Reached 5+", "3 Reached 10+", "4 Reached 20+". All accounts; blank if observed less than 730 days. |
| high_growth_10_in_730d | Main modelling target: 1 if a small starter reached and held 10 seats within 730 days, 0 if not. Blank for accounts that aren't small starters or haven't been observed 730 days. |
| top_tier_20_in_730d | Same, for 20 seats. Expect few accounts; use for description rather than modelling. |

### Role / function features (only when `ROLE_COL` is set)

| Column | Definition |
|---|---|
| initial_function | Most common function among launch hires (first 14 days); ties go to the earliest hired. |
| launched_multi_function | 1 if launch hires span more than one function. |
| n_functions_14d / 30d / 60d / 90d | Distinct functions hired by day N. Blank if not observed that long. |
| days_to_2nd_function | Days from start to the first hire in a second function. Outcome, not an early feature. |
| post_launch_hires | Hires after day 14. Outcome. |
| same_fn_hires | Post-launch hires in the initial function. Outcome. |
| pct_expansion_same_function | `same_fn_hires` / `post_launch_hires`. Outcome. |

### Added by the Kaplan-Meier cell

| Column | Definition |
|---|---|
| t5_event | 1 if the account ever reached and held `SEAT_TARGET` (5), else 0. |
| t5_days | `days_till_5_headcount` if reached, otherwise `tenure_days` (the point the account stopped being observed). |
| churn_event | With `CHURN_EVENT = "final"`: same as `churned`. With `"first"`: 1 if the account ever had a zero-headcount gap longer than 30 days. |
| churn_days | With `"final"`: `tenure_days`. With `"first"`: `days_to_first_churn`, or `days_observed` if the account never churned. |

---

## Output tables

| Table | Built in | What it shows |
|---|---|---|
| by_year, by_region, by_industry, by_size, by_reg_ind | Pipeline (rollup) | Account counts, activity, reactivation, ramp and attrition rates by group. Groups under 20 accounts (30 for region × industry) are dropped. |
| reactivation_by_status, reactivation_by_region | Pipeline | Reactivated accounts against active status, and reactivation rate by region. |
| cohort_counts, cohort_mix | Pipeline (Step 1) | Accounts in each `ask_cohort` by region, as counts and shares. |
| path_by_year | Pipeline (Step 1) | `seat_path` by start year; recent years should be heavy on "Too early". |
| path_profile | Pipeline (Step 1) | Churn, reactivation, size and timing medians by region and `seat_path`. |
| early_by_cohort | Pipeline | Early-signal medians and rates by region and `ask_cohort`. |
| conv_by_hc30, conv_by_add30 | Pipeline | Share reaching 5 within 365 days, by day-30 headcount and by early seat adds. |
| tier_by_launch | Pipeline (Step 3) | Growth tier counts by launch size, for accounts observed 730+ days. |
| small_starter_growth | Pipeline (Step 3) | Among small starters: share reaching 5, 10 and 20 by each window, by region plus "All", with eligible and reached counts. |
| km_t5, km_churn, km_landmark, km_ramp | Kaplan-Meier cell | Milestone tables (share and n at risk at 30/90/180/365 days) for the four curves. |
| industry_table, industry_table_num | Industry table cell | Ramp and retention by industry; the `_num` version keeps estimate, low and high as separate columns. |

The pipeline also prints data checks: the most common disengagement dates, counts of active hires, future-dated exits, blank dates and excluded future starts; a warning if a likely fill date is being treated as a real exit; how many accounts touched versus held each milestone; and how many zero-headcount gaps were backfills, churns or pending.

---

## Things to know when using these

- **Check the active-staff data check first.** If the most common disengagement date is the extract's "still active" fill date and isn't today, set `ACTIVE_FILL_DATE`. Otherwise active staff are treated as exits. The grace period can hide this problem by making those accounts look "pending", so read the warning even if churn looks normal.
- **Three levels of churn.** `first_zero_date` records any drop to 0, including backfills. `first_churn_date` records the first drop lasting over 30 days. `churned` and `engagement_active` look at today only, so a reactivated account with staff today counts as retained. The KM cell's `CHURN_EVENT` setting chooses between `first_churn_date` and today's status.
- **Milestones must be held.** `days_till_N_headcount`, the ramp flags, `seat_path`, the growth tiers and the high-growth targets all require 30 days at N+. An account that reached N less than 30 days ago doesn't count yet, so very recent growth is slightly undercounted. `peak_headcount` is not held and can reflect a brief spike.
- **"Attrition" is a defined subset.** It means Resigned, AWOL or Dismissed. Any other status (contract end, transfer, etc.) counts only as a disengagement. Resigned is typically voluntary, so decide what to call this group.
- **Headcount is net, not gross.** `employee_count_at_start`, `days_till_N_headcount`, `seat_path` and the growth tiers use net active staff, while `hires_Nd` is gross hires. They can disagree when people join and leave quickly.
- **Use launch size, not day-0 size, for starting size.** `launch_size` (day 14) handles staggered onboarding; `employee_count_at_start` and `start_size_bucket` don't.
- **Always use masked columns for rates.** The `_elig` columns, ramp flags, growth tiers and high-growth targets are blank for accounts too young to judge. The unmasked `attrition_within_Nd` and `disengaged_within_Nd` columns are 0 for those accounts, which understates rates.
- **Averages of time-to-N are biased.** `days_till_N_headcount` only exists for accounts that got there, so averaging it ignores accounts still growing or that churned first, and makes ramp look faster. Use the ramp flags or Kaplan-Meier curves instead.
- **Outcome columns leak if used as model features.** The pipeline's `OUTCOMES` list holds all of them (including the churn and reactivation columns, growth tier, high-growth targets and every `reached_` flag), and `EARLY_FEATURES` holds only what is known by day 90.
- **Bucket labels avoid Excel date conversion.** Labels use "1 to 2" rather than "1-2" so Excel and Google Sheets don't turn them into dates.