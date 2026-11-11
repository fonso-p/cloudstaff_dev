# Review: 2026-10-10_Client_Growth_Dashboard.html
Verdict: CHANGES NEEDED
Reviewed: 2026-10-10, round 1 (cs-data-reviewer)

The data prep and the dashboard calculations reproduce exactly from the raw files. One requester question is not answered: whether USTL's monthly hiring pattern differs from the company pattern.

## Verified
- Row tie-out (reviewer's own rule code): used 12,469 + excluded 18,234 = 30,703. Excluded list matches the dashboard shortcode by shortcode. 1,870 clients in scope.
- Monthly table (71,492 rows): starts, churned, active at month end and months since start match the reviewer's recount. 0 differences.
- Region, division, industry and status per client: 0 differences (APAC 990, AMER 588, OPTI 292; 898 / 267 / 705).
- Profile fields (peak, time to 5, day 90, starting seats, tenure, net, peak net month, function fields): 0 differences; role match 83.94%.
- Overview KPIs at the default settings match the rendered page. The Lifecycle and size-bucket "All" rows match.
- Kruskal-Wallis by region and by segment match scipy. verify_stats.py PASS (1.3e-12). check_page.py: no errors. The Wilson ranges match.
- MyStaff differences: 62 staff-count, 1 start-month; never staffed 253 (22 Active = Yes). Embedded JSON = data/client_monthly.json.
- No causal words. Every test shows n per group, a p < 0.05 reading and a warning for groups under 20.

## Must fix
- dashboard_template.html:646, seasonality division table: divisions under 20 clients are dropped, so USTL (19 clients, 1,310 starts) is never shown or tested against the company pattern.

## Should fix
- Segment tests include a "0 staff" group (4,393 of 11,184 windows), which drives the result. Test 1-4, 5-10 and 10+ only, or label it.
- The region chi-square uses "hit in any window", which favours older clients. Say so, or test per window.
- The seasonality caveat (starts are not independent) is only on the Stats page.
- Lifecycle-by-division cells and movement-by-window rates with n under 20 are shown without n or a flag.
- No 95% range on the Overview share or the division and industry hit rates.
- cProf1 says "with 95% range" but shows none and no n. The 5+ starting seats bar is 100% by definition.
- "Added a 2nd function" counts clients with an Unknown initial function in the denominator. Role match by year (20% in 2020) is not shown.
- prep.py:167-168: one client is excluded for "No valid stint", which is not an agreed treatment.
- prep.py:139-140: "Not in MyStaff" excludes clients instead of tagging them Unknown region and flagging them (0 rows today).
- The 18 name pairs on different shortcodes are not listed in QA.
- The never-staffed count reads 1,048,569 MyStaff rows without first dropping blank shortcodes.
- README refresh steps leave out the billed-report path and role tabs in icp_prep.py, and phase4_checks.py. Dates are hard-coded in the template.

## Nice to have
- 183 clients have an any-day peak above their highest month-end staff; 7 reach 5 only that way.
- Peak net month is the start month for 85% of clients.
- Size bucket table: add counts and "stayed".
- client_reference.csv has no ref_source column. The MyStaff first-date difference is shown in months, not days.
- State on the Lifecycle page that September 2026 is a partial month.

## Could not verify
- Mapping role titles to function families (icp_prep.role_function was used as the lookup).
- EMEA folding (MyStaff (2) has 0 EMEA rows).
- Branding against the Morpheus screenshot.

---
# Round 2 (focused, after fixes and two requester decisions)
Verdict: APPROVED WITH NOTES
Reviewed: 2026-10-10, round 2 (cs-data-reviewer)

Requester decisions applied: (A) window 1 and the Lifecycle months 1-3 stage measure growth after launch, from the end of month 1; (B) CIB187, whose only stint ends before it starts, is counted with the never-staffed clients (254).

## Verified (reviewer recomputed independently)
- Row tie-out 12,469 + 18,234 = 30,703; 1,870 clients; monthly table, embedded arrays and tags: 0 differences.
- Overview at 6 months / 5+: 111 hitting, 6.5% of 1,718 (95% 5.4% to 7.7%), net 1,875, starts 9,171, churn 7,296, active now 4,741, active with 0 staff 267. Also matches at 12 / 10+ and 3 / 3+.
- Hits by window by region, segment and region tests vs scipy (three settings), Lifecycle "All" rows, size buckets, Wilson ranges: match.
- Decision A is applied the same way in buildWindows, stageNet, verify_stats.py, the notes and the README. Decision B: 254 never staffed, and the row tie-out holds.
- Items 1-14 from round 1: fixed (item 11 partly fixed).

## Must fix
- None.

## Should fix
- prep.py name pairs use MyStaff names only for staffed shortcodes. 6 same-name groups whose second code has no staff are missing (OPACHEMPACK/OPICHEMPACK, ENVIS/ENVISION, JASONRECML/JASONRECOMM, TIMALTASSRE/TIMALTASS, OPACEDARWEST/OPA, USYELLOWSTONELA/usyellowstonel). Build the list from every MyStaff (2) shortcode and flag these in the never-staffed note.

## Nice to have
- Movement by window: the "More than 10 staff: % up" column is always 0%, and there is no note saying grey means n under 20.
- Windows after a client leaves (0 staff) count as non-hit windows; say so on the Divisions page.
- Label the Lifecycle stage "Months 1-3 (after launch)".
- Still open from round 1: ref_source column, MyStaff first-date difference in days, peak net month after month 3.

---
# Round 3 (focused)
Verdict: APPROVED WITH NOTES
Reviewed: 2026-10-10, round 3 (cs-data-reviewer)

- The four changes since round 2 are confirmed: the name list is built from every MyStaff (2) shortcode (19 groups, 38 shortcodes), the "Months 1-3 (after launch)" label, the Movement by window column and note, and the Divisions note.
- Calculations are unchanged. All 1,870 client records are identical to round 2, and 0 rendered numbers changed. Tie-out 30,703, never staffed 254, and the Overview at 6 / 5+ (111, 6.5%, 1,875 net) all match the reviewer's recomputation.
- Must fix: none.
- Should fix: the QA tile said 9 never-staffed clients share a name with a staffed client; the correct count is 8 (AUBLAHDORK's only namesake has no staff).
- Nice to have: AUBLAHDORK may itself be a test record; check_page.py only worked from the project root. Still open from round 1: ref_source column, first-date difference in days, peak after month 3.

## Fix after round 3 (analyst, verified by independent recount, no further review round: the three-round limit is reached)
- prep.py: share_name_with_staffed_client now keeps only name groups that have at least one staffed shortcode. The recount from data/qa_name_pairs.csv gives the same list.
- check_page.py: finds the dashboard from the script's own location, so it works from any folder.
