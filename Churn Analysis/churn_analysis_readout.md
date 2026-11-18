# Client churn: what comes before it

*Readout, updated 18 November 2026. Ratios are against the typical client in each segment, as on the dashboard. Source: `churn_analysis_raw.ipynb`, Part 2.*

## Bottom line

- **Controllable churn is uncommon in any one month but adds up.** We count churn here as seats lost for any reason except Business Reasons, which we treat as market churn. In a typical month, about **6% of clients with 5+ staff** go on to lose 20% or more of their seats within 3 months. About **5% of clients with 1–4 staff** leave entirely within 3 months.
- **Attendance is the clearest warning sign we can act on.** At clients with 5+ staff, absences or late arrivals at twice the normal rate bring about **twice the typical client's risk** (2.2x and 1.8x). The signal is visible **4–6 months ahead**, well before the client gives notice.
- **The warning is much stronger when attendance problems come with a second sign of strain.** When high late arrivals coincide with a shrinking headcount, a recent seat loss or a staff exit for service dissatisfaction, the risk is **about three times the typical client's**: 16–18% of these clients churn, against 5.6% for the typical client.
- **Late payments are not a churn signal.** About three in four clients with 5+ staff paid at least one invoice late in the last 6 months, so a late payment is normal, not a warning.
- **For small clients (1–4 staff), a staff resignation is the key moment.** After one, the risk of a full exit is 1.7 times the typical small client's, and higher still when the client is also not replacing staff.
- **The model is good enough to decide where to look first, not to name the clients who will leave.** It is a prioritisation tool for account teams. It is not ready to run as an automatic alert.

## What we measured

| | Clients with 1–4 staff | Clients with 5+ staff |
|---|---|---|
| **Churn means** | the client loses **all** its seats within 3 months | the client loses **20%+** of its seats within 3 months |
| **How often** | 4.8% of client-months | 5.6% of client-months |
| **Clients in the analysis** | 1,342 | 348 |

- **A third segment, clients with 5+ staff that lose every seat ("churn to 0"),** is the most severe form of the 20%+ churn above. It is rare: 0.6% of client-months, about 18 clients over the whole window. That is enough to describe what came before those exits, but too few to build a model. The only clear sign is a **shrinking headcount**: clients down 10%+ over 6 months had 2.5 times the typical client's risk of churning to 0 (range 1.2x to 4.1x). The attendance signs are not clear for this group.
- **Seats lost** are exits that weren't replaced. Exits for **Business Reasons** are not counted as churn: restructures, business slowdowns, downsizing, budget cuts and roles being moved. They are largely outside Cloudstaff's control. They are still used as a warning sign of further churn.
- **Small clients are measured differently** because a percentage is misleading for them: one exit at a 2-person client is 50%.

## Data used

| Source | What it gives us |
|---|---|
| SC Engagement List | every staff start and exit, and so each client's headcount over time |
| Disengagement tickets (PB-4108) | why each exit happened, whether the seat was replaced, and when notice was given |
| No call no show, Tardiness, Absences logs | attendance problems, matched to the client the staff member was working for at the time |
| Late Payments report | which months each client paid late |

The analysis takes a snapshot of every client on the 1st of each month, from April 2024 to August 2026. That is 24,795 client-months from 1,489 clients. Each snapshot records what the client looked like in the months before, and whether it churned in the 3 months after.

## How the model works, and why we chose it

- **Two questions, two kinds of evidence.** First, a straight comparison: for each event, how much more often did clients churn after it happened? This is the main answer and needs no model. Second, a predictive model that weighs all the signals together and scores each client.
- **Three models, compared side by side,** each predicting the share of a client's seats lost in the next 3 months:
  - **LightGBM** and **XGBoost** (gradient-boosted decision trees) cope with missing data and pick up combinations of factors that a simple scorecard would miss.
  - **Logistic regression** gives each factor one fixed weight, so it is the simplest to explain.
  - All three explain each client's score in terms of the factors behind it.
- **One set of factors for every model:** attendance, payments, staff events, client profile, region, and late-stage warnings such as client notices and recent seat losses. The late-stage warnings predict well, but by then the client has usually decided.
- **How it was tested:** trained on April 2024 to October 2025, then tested on January to August 2026, months the model had never seen. We repeated the test on clients the model had never seen. Results were almost the same, so the model is learning general patterns, not memorising particular clients.

## What we found

### Warning signs, ranked

Risk after each event, as a multiple of the **typical client** in the segment: 5.6% churn for 5+ staff (20%+ of seats) and 4.8% for 1–4 staff (all seats). Only clear signals are listed: those unlikely to be chance.

| Warning sign | 5+ staff | 1–4 staff | When it shows |
|---|---|---|---|
| Absences at twice the normal rate | **2.2x** | 1.4x | 4–6 months ahead, both sizes |
| Late arrivals at twice the normal rate | **1.8x** | 1.2x | 4–6 months ahead for 5+; only just before for 1–4 |
| Cloudstaff-initiated staff exit (AWOL, behaviour, fraud) | **2.3x** | not clear | 4–6 months ahead (5+) |
| Headcount down 10%+ over 6 months | 1.8x | 1.7x | |
| Client for less than a year | 1.6x | 1.2x | |
| Staff member resigned | not clear | **1.7x** | 4–6 months ahead (1–4) |
| No call no shows at twice the normal rate | not clear on its own | 1.4x | |
| Exit for service dissatisfaction | 1.4x | not clear | |
| Late payment | **not a signal on its own** | slightly *less* churn (0.9x) | |
| *Late-stage:* client gave notice in the last month | 1.7x | 4.2x | weeks ahead |
| *Late-stage:* already lost 20%+ of seats recently | 3.2x | 1.8x | |

### Combinations matter more than single signs

The same comparison, run on pairs of events:

| Combination (5+ staff) | Churn when both happen | × the typical client's risk | Either one alone |
|---|---|---|---|
| High late arrivals **and** headcount down 10%+ | 18% | **3.2x** | 8% |
| High late arrivals **and** a staff exit for service dissatisfaction | 17% | **3.1x** | 6–8% |
| High late arrivals **and** a seat lost recently | 16% | **2.9x** | 6–7% |
| High no call no shows **and** the client not replacing staff (pulling out, budget) | 15% | **2.7x** | 7% |

Signs that most clients have, such as any late payment, are left out of this comparison, because they are the normal state rather than a warning.

For small clients, a **resignation where the client is also not replacing staff** leads to a full exit 22% of the time (4.7x the typical small client's risk), against 5–8% for either one alone.

### How well we can predict it

We score accuracy with a measure called AUC, where 0.5 is a coin flip and 1.0 is perfect; about 0.7 is generally useful.

Three models, each predicting the share of a client's seats lost in the next 3 months from the same factors:

| | LightGBM | Logistic regression | XGBoost |
|---|---|---|---|
| Clients with 1–4 staff | 0.67 | 0.69 | 0.60 |
| Clients with 5+ staff | 0.63 | 0.71 | 0.68 |

- **Small clients:** the top 10% of scores contain 27–29% of the clients that went on to leave.
- **5+ staff:** logistic regression ranks best; its top 10% contain 26% of the clients that went on to lose 20%+ of their seats.
- **What this means:** the model narrows where to look, but many clients that churn show no clear warning in the data we have today.

## What this means for action

1. **Watch attendance trends at client level every month, compared with similar-sized clients.** A sustained rise is the earliest sign we have.
2. **Escalate when attendance problems coincide with a second strain:** a shrinking headcount, a recent seat loss, or a service-dissatisfaction exit. Together these roughly triple the risk.
3. **Treat the first resignation at a small client as a retention moment.** This matters most when the client hasn't replaced a previous exit.
4. **Give clients in their first year extra attention after any service-dissatisfaction exit.**
5. **Don't use late payments as a churn alert.**

The charts for these findings are in section 2.11 of the notebook.

## Not ready yet

- **The automatic watch list.** The threshold for flagging clients is not yet reliable, especially for 5+ staff. It should be set by how many clients the team can review each month, then re-tested.
- **Correlation, not cause.** These events come before churn; we have not shown that they cause it.

## Gaps in the data

- Absence records stop in February 2026.
- No call no show recording changed in 2026, so volumes rose about tenfold. We compare each client with others in the same month to allow for this.
- Detailed exit reasons are often blank before 2023.

## Next steps

| Step | Why |
|---|---|
| Agree definitions with Finance and Sales: how the 5+ group is set, and how exit reasons map to the three headline buckets | so these figures reconcile with the monthly churn report |
| Add Client NPS and Staff NPS | the most direct measures of dissatisfaction, and the data is available |
| Predict service-dissatisfaction exits and resignations separately | these are the controllable reasons, and their early signs may differ |
| Build a staff-level resignation view: an individual's attendance trend before they resign | resignation signals are personal, not client-wide |
| Split results for Cloudstaff and Opti | requested; the patterns may differ |
| Set the flag threshold from team capacity | to turn the model into a usable monthly list |

## Appendix: what the model looks at

| Group | Factors |
|---|---|
| Attendance (last 3 months) | no call no shows, late arrivals and absences, each compared with similar-sized clients that month; whether any occurred at all |
| Payments (last 6 months) | months paid late, share of invoices paid late, whether the client was unresponsive about payment |
| Staff events (last 3 months) | resignations, Cloudstaff-initiated exits |
| Client profile | headcount, headcount change over 6 months, years as a client, region |
| Late-stage warnings | client notices in the last month; exits for service dissatisfaction or business reasons; staff not replaced because the client is pulling out, cutting budget or moving onshore; seats lost in the last 3 months |
