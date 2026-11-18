# Churn warning signs: how they are calculated and how to read them

*Guide to the dashboard `<date>_Churn_Warning_Signs.html` (saved locally in `Desktop/Projects/Churn Analysis/Dashboards/`), built from the notebook `churn_analysis_raw.ipynb` (Part 2). Figures are from the run on 18 November 2026, with data to 13 November 2026.*

## Part 1 · How the numbers are calculated

```
Source files → timeline (client × day) → monthly snapshots → features (looking back)
           → yes/no signs → compare churn with vs without → dashboard
```

### 1. Gather the sources

| Source file · tab | What it gives |
|---|---|
| Churn Analysis workbook · Engagement Raw (SC Engagement List) | every staff start and end, by client; client type and region |
| PB-4108.xlsx · UB Staff Disengagement | the reason for each exit, whether the seat was replaced, when notice was given |
| NCNS.xlsx · NCNS, Tardiness.xlsx · Tardiness, Absences.xlsx · Absences | each attendance incident |
| Late Payments.xlsx · 2023–2026 | which months each client paid late, and why |

### 2. Build the timeline

The timeline has one row per client per day that has an event. Each column counts one kind of event, for example `seat_exit`, `exit_replaced`, `exit_client_business_reasons`, `absence_incidents` and `late_payment`, and `active_staff` gives the headcount that day.

The rules that decide what lands where:
- **Exits** take their reason and replacement status from the matching disengagement ticket. A ticket is matched to an engagement on Client ShortCode, Engagement ID and CS Username.
- **Attendance incidents** count only while that staff member was on that client's engagement.
- **Late payments** are placed on the 15th of the month, and only if the client had active staff then.

The Data dictionary page shows, for every timeline column, the **source file and tab**, the **source columns** it reads, and **how it is tied to the client**.

### 3. Take monthly snapshots

On the 1st of every month from April 2024 to August 2026, each client becomes one row, a **client-month**.

Each client-month records:
- **Its size** that day: 1–4 staff or 5+ staff.
- **What happened over the next 3 months (the outcome).**
  - **Seats lost** are exits that were not record-only, not replaced, and not for business reasons. Business reasons are restructures, slowdowns, downsizing and budget cuts: market churn, outside Cloudstaff's control.
  - **Churn 20%+ of their seats:** the client lost at least 20% of its staff.
  - **Churn to 0:** the client had no staff left at the end of the 3 months.

Size and outcome together make the three segments on the dashboard:

| Segment | Churn means | Typical client (the 1x baseline) | Clients that churned |
|---|---|---|---|
| Clients with 5+ staff (churn 20%+ of their seats) | lose 20%+ of seats within 3 months | 5.6% of client-months | 123 of 348 |
| Clients with 5+ staff (churn to 0) | lose every seat within 3 months | 0.6% | 18 of 348 |
| Clients with 1–4 staff (churn to 0) | lose every seat within 3 months | 4.8% | 352 of 1,342 |

### 4. Work out features, looking back from each snapshot

- **Window:** 3 months, or 6 for payments, always ending the day before the snapshot. Nothing from the 3 months being predicted leaks in.
- **Per 10 staff:** counts are scaled by headcount, so large and small clients compare fairly.
- **Attendance index:** each attendance rate is divided by the average of same-size clients that month (1.0 = average). This also absorbs the 2026 change in how NCNS was recorded.
- **Missing data:** months where a source has no records are left blank, not counted as zero. For example, absences after February 2026.

### 5. Turn features into yes/no signs

Each code on the dashboard is one test on one feature:
- **A1:** absence index ≥ 2, meaning twice the normal rate.
- **P1:** headcount down 10%+ over 6 months.
- **L1:** at least one client-initiated notice in the last month.

The Data dictionary page lists every code.

### 6. Single warning signs: two numbers, two jobs

Every chart measures risk against **one baseline: the typical client in the segment**. That is the segment's overall churn rate, the same number as its headline tile (5.6% for clients with 5+ staff, churn 20%+). Separately, a with-versus-without test decides whether each sign is a real signal.

**Worked example: A1, clients with 5+ staff (churn 20%+ of their seats)**

| | Share that churned | Use |
|---|---|---|
| Client-months with high absences (604) | 12.3% | |
| Typical client in the segment | 5.6% | **Shown on the chart:** 12.3 ÷ 5.6 = **2.2x the typical client's risk**, labelled "2.2x · 12%" |
| Client-months without high absences | 5.0% | **The verdict test:** 12.3 ÷ 5.0 = 2.4x, 95% range 1.3x to 3.8x, which does not cross 1, so the signal is clear |

- **The 95% ranges** come from resampling whole clients 500 times and recalculating each ratio. Whole clients are used because one client contributes many months that are not independent.
- **Why two numbers:** the typical client is one baseline that everyone can picture and that matches the headline tile. The with-versus-without test is the stricter test of whether the sign makes a difference at all.
- **The verdict:**

| Verdict | Rule | On the chart |
|---|---|---|
| **Clear** | the range does not cross 1x | coloured bar |
| **Unclear** | the range crosses 1x: the difference could be chance | grey bar, labelled "unclear" |
| **Too few** | fewer than 30 client-months had the sign, or fewer than 5 of them churned | grey bar, labelled "too few" |

Grey bars still show their ratio, for completeness, but they are not findings.

### 7. Two signs together: four groups instead of two

For each pair of signs, the client-months are split into *both signs*, *only the first*, *only the second*, and *neither*. The chart shows each group against **the same baseline as the single signs, the typical client**.

**Worked example: A2 (late arrivals at 2x normal) + A6 (exit for service dissatisfaction), clients with 5+ staff (churn 20%+); typical client 5.6%**

| Group | Share that churned | × the typical client's risk |
|---|---|---|
| Late arrivals only | 7.7% | 1.4x |
| Service-dissatisfaction exit only | 5.6% | 1.0x |
| **Both** (235 client-months) | **17.4%** | **3.1x** |
| Neither sign | 4.6% | 0.8x (in the tooltip) |

**"Stronger together"** means "both" is clearly above the stronger sign on its own. Here 17.4% ÷ 7.7% = 2.3x, with a range of 1.2x to 3.5x, tested by the same client resampling.

A pair is shown only when:
- the two signs were seen together in at least 30 client-months, with at least 5 churned;
- at least one sign is something Cloudstaff can act on;
- neither sign is present in more than half of client-months, because a sign most clients have is the normal state, not a warning (for example, "paid an invoice late" applies to 77% of 5+ client-months).

**For clients with 5+ staff (churn to 0), no pair passes.** Only 18 clients churned to 0. The chart instead shows the pairs with the highest churn (at least 3 churned client-months with both), in pale pink and marked **inconclusive**.

### 8. Onto the page

The notebook's export cell writes the rates, ratios, ranges and counts to `churn_warning_signs.json` in the local dashboards folder. The file has no client names or shortcodes. It also includes the dictionary that links each code to its feature, its timeline columns, and their source files and columns. A check script confirms that every number ties out and every code traces to a source, and the dashboard is then built from that file.

## Part 2 · How to read the dashboard

### Headline tiles (one per segment)

| Part of the tile | What it means |
|---|---|
| **Big number** (for example 5.6%) | The share of client-months that went on to churn within 3 months, as the segment defines churn: **the typical client**. This is the 1x baseline in every chart. |
| **"123 of 348 clients did"** | How many different clients churned at least once in the period. |
| **"Clearest early sign"** | The strongest *clear* sign Cloudstaff can act on for that segment, as a multiple of the typical client's risk. For churn to 0 among 5+ staff it is a profile sign (headcount down, 2.5x), the only clear one. |
| **"Too few exits for a model: warning signs only"** | Shown on churn to 0 among 5+ staff. Treat its signs as indicative. |

**Churn to 0 among 5+ staff is part of churn 20%+, not separate from it.** A 5+ client that loses every seat counts in both tiles; they are two levels of severity.

### Warning signs, ranked

- **Legend:** shown at the top of the card.

  | Colour | Meaning |
  |---|---|
  | Blue | early sign we can act on (attendance, staff events, payments) |
  | Dark grey | client profile (headcount trend, client age) |
  | Orange | late stage: the client has usually already decided (notice given, seats already lost) |
  | Light grey | not a clear signal ("unclear") or too few churned clients to tell ("too few") |

- **Bar length** shows the risk for clients with the sign as a multiple of the **typical client** in the segment. The black line (1x) is the typical client, and its rate is printed on the line. The bar label gives both numbers: "2.2x · 12%" means 2.2 times the typical client's risk, and 12% of those clients churned.
- **Layout:** the three panels list the same signs in the same order, so you can read across a row to compare segments.
- **Hover** over a bar for its churn rates, 95% range and number of client-months. **Click** a bar to open its definition.

### Two signs together

- **Bars:** for each pair, the risk with the first sign alone, the second alone, and **both together** (red), each as a multiple of the **typical client**, the same 1x baseline as the ranked chart.
- **Pale pink with "inconclusive" in the card header:** no pair was clearly stronger together. These are shown for completeness.
- **Hover** over a bar to see the underlying churn rates.

### Data dictionary page

You can trace any bar from left to right:

| Table | What it tells you |
|---|---|
| **What counts as churn** | each segment's definition, its client and churn counts, and whether it has a model |
| **1 · Indicators** | each code's test, the feature it uses, where it appears, and **how common** it is (the share of client-months with the sign) |
| **2 · Features** | how each feature is built and which timeline columns it uses |
| **3 · Timeline columns and their sources** | for each column: the **source file and tab**, the **source columns** read, how the rows are **tied to the client**, and how it is derived. The last rows are client details read straight from the engagement list (client age, region, client type). |
| **4 · Source files** | rows loaded and the date range of each file |

Clicking a code or a column name jumps to its row.

### Method & QA page

- **Method** defines every term on the page.
- **Reconciliation** follows every exit in the period down to the seats counted as churn. Exits that were record-only, replaced, or for business reasons are each listed separately, and they add up to the total.

## Part 3 · Reading the numbers correctly

- **A ratio is relative, not absolute.** "2.2x" on a 5.6% typical client means about 12% of those client-months churned, and most clients with the sign did not churn. That is why each bar label also shows the rate. For churn to 0 among 5+ staff, even 2.5x on a 0.6% typical client is only about 1.6%.
- **Before, not because.** These signs come before churn; the analysis does not show that they cause it. Late-stage signs mostly confirm a decision the client has already made.
- **Grey means "we can't tell", not "no effect".** A grey sign may matter, but the data cannot separate it from chance. This applies to most signs for churn to 0 among 5+ staff.
- **One baseline everywhere.** In both charts, 1x is the typical client in the segment, the headline-tile rate, so every number on the page can be compared with every other. The verdict test behind the colours compares with versus without the sign, which is why a sign can show, for example, 1.4x the typical client and still be grey.
- **Signs show where to look, not who will leave.** Three models that combine the signs (LightGBM, logistic regression, XGBoost) score 0.63–0.71 for 5+ staff (churn 20%+) and 0.60–0.69 for 1–4 staff (churn to 0), measured by AUC (0.5 = coin flip, 1 = perfect). That is enough to prioritise attention, not to predict individual clients.
- **Business-reason exits are excluded on purpose.** Including them would raise every churn rate and mix in churn that Cloudstaff cannot influence.
- **Data gaps:**
  - The absence log ends in February 2026, and NCNS and tardiness in September 2026, so the latest months lack some attendance data.
  - NCNS recording changed in 2026, which the attendance index adjusts for.
  - Detailed exit reasons are often blank before 2023.
