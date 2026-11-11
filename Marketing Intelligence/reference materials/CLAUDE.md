# Marketing Intelligence & Prioritization

Account prioritization for Sales, Marketing and Account Management. Brings buying and growth
signals together per account, scores them, and routes prioritized lists to SDR / BDM / AM.
The full proposal is in `docs/Marketing_Intelligence___Prioritization_Proposal.docx`.

## Current state

Everything so far is a **mock** with fictional data, built to agree the design with stakeholders.
Nothing connects to real systems yet.

| Path | What it is |
|---|---|
| `docs/…Proposal.docx` | The original proposal, including the Data Catalogue |
| `mock/Priority_Score_Mock_Dataset.xlsx` | 400 fictional accounts, scoring done with live Excel formulas. Sheets: How It Works, Priority List, Data Gaps, Settings |
| `mock/Account_Priority_Dashboard_Mock.html` | Standalone dashboard (data embedded; d3 from CDN). Tabs: Priorities, Data glossary, How the score works |
| `data/accounts.csv` | The 400 scored accounts exported from the workbook (what the dashboard reads) |
| `data/scoring_settings.json` | Weights, baselines, thresholds, news strengths, recency factors (matches the Settings sheet) |
| `scripts/generate_mock_workbook.py` | Generates the workbook (random seed 42). openpyxl writes formulas but does not compute them; open in Excel or recalc with LibreOffice before reading values |

The Excel formulas are currently the reference implementation of the scoring logic.

## Scoring model (agreed design)

Two goals, scored separately, each out of 100 points before the industry nudge:

| Component | New Logo | Organic Growth |
|---|---|---|
| Website activity | 35 | 50 |
| News / jobs / social | 35 | 50 |
| Diamond referral (flag) | 15 | not used |
| Prior BPO experience (flag) | 15 | not used |

**Signals (0–1):**
- Website = 0.4 × Team Builder visit + 0.3 × form fill (last 30 days) + 0.3 × min(visits_30d / 20, 1)
- News/jobs = 0.6 × (strongest news strength × recency factor) + 0.4 × hiring
  - hiring = 1 if hiring spike, else min(job_postings / 20, 1)
  - news strength: Funding round 1.0, PE buyout 1.0, M&A 0.8, Expansion 0.7, Restructuring 0.5,
    Leadership change 0.3, Other/Unclassified 0.3, None 0
  - recency: 0–30 days 1.0, 31–90 0.7, 91–180 0.4, >180 0
- Points = signal × component max.

**Missing data — three kinds of "empty" (important):**
1. Not applicable (flags on Organic Growth) → excluded from that goal's formula.
2. Checked, found nothing → real zero.
3. Unknown (never collected) → use a **baseline**: 35% of max for website, 30% for news/jobs.
   Diamond / BPO blanks count as "No". Unknown components are flagged as "estimated".
   (We moved away from rescaling over available components because it inflated scores for
   accounts with a single known signal.)

**Industry nudge:** score × (0.9 + 0.2 × industry trend), trend 0–1; unknown industry → ×1.0.
Industry is a multiplier, not points, so it cannot create a high score on its own. Final score capped at 100.

**Tiers:** Tier 1 ≥ 70, Tier 2 ≥ 40, else Tier 3. Optional coverage cap for Tier 1 exists but is off.

**Act now (hot) triggers**, pinned above score order: Diamond referral (New Logo), form fill in
last 30 days, Team Builder visit (Organic Growth only), funding round or PE buyout within 30 days.

**Routing:** Organic Growth → AM. New Logo with Diamond referral, any hot trigger, or score ≥ 60 → BDM.
Other New Logo → SDR. Each account on exactly one list.

**Deliberately excluded for now:** Department Growth Path, Client Research, assigned owner.

## End-user design principles (Sales / Marketing / AM audience)

- The priority score is the only number reps see by default; tier is shown by colour.
- Component points become chips with strength dots (●●● ≥ 66% of max, ●●○ ≥ 33%, ●○○ > 0); zero signals are hidden.
- Flags are shown as labelled chips; estimated components show a "No website/news data" chip.
- News chips show the event type (and in a real build, the headline). "Other / Unclassified" is
  unhelpful to reps; plan to show the headline or rename it "Other news".
- Organic Growth rows can show the current relationship (staff with us, departments).
- Plain language everywhere; full point breakdown available on demand.

## Open ideas, not yet built

- **Fit score:** score accounts on resemblance to best historical clients (same analysis as the
  priority profile). Define "good client" with Sales/AM first. Use only traits visible for prospects
  (industry, size, region, prior BPO) for New Logo; a separate expansion-fit model for clients.
  Start with smoothed segment rates, later logistic regression. Include lost deals if available.
  Combine either as a multiplier on the Priority Score (may absorb industry trend) and/or a
  fit × timing grid for Marketing.
- **Production pipeline (on hold):** Python ingest → entity resolution (account master + identifier
  crosswalk) → NLP extraction into a long `signal_events` table (category, confidence, evidence) →
  `source_coverage` table (what was checked) → daily features → one scoring module with versioned
  config → reason codes → assignments respecting HubSpot ownership → write back to HubSpot + dashboard
  → outcomes feedback loop. Use the mock workbook's accounts as golden test cases for the scoring module.
- Gaps vs. industry practice: third-party intent data, contacts / buying committee, champion tracking
  (former client contacts moving companies), success metrics and a pilot baseline, rep feedback
  ("not relevant"), execution layer (account briefs, suggested openers).

## Conventions

- All mock data is fictional; never mix it with real client data.
- Keep weights and thresholds in settings/config, not hard-coded in display code.
- Resumes (CS Jobs) are personal data: extract company names and dates only.
