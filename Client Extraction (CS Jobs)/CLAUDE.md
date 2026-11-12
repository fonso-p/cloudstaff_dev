# Client Extraction (CS Jobs): project handoff

(Formerly "Competitor Analysis (client scrape)"; the data folder still uses that name.)

## Goal

We have resumes from candidates who previously worked at competitor outsourcing/BPO companies.
When people list a competitor as their employer, they often add the overseas **client** they were
assigned to, in no fixed format, e.g. `Shore360- Infinite Energy`, `TOA Global (Trilogycare Australia)`,
`EMAPTA / Abbey Commercial Flooring (Virginia, United States of America)`.

We want to extract **competitor → client** pairs at scale (thousands of records), with a human review
step for uncertain cases. The end product is a competitor-to-client map with counts.

The user is Alfonso, working on Windows, CPU only (no GPU).

## Folder layout

Code and data are kept apart **on purpose**: the code is in the git repo, the resume data is not.

Code: `C:\Users\Alfonso(FonsoP)Panli\repos\cloudstaff_dev\Client Extraction (CS Jobs)\`

```
competitor_client_extraction.ipynb   # main pipeline (rule-based extraction + review loop)
qwen_client.py                       # reusable Ollama/Qwen client module (stdlib only)
review_suggestions.py                # uses qwen_client to pre-fill review suggestions
CLAUDE.md                            # this file
```

Data (`DATA_DIR`, hardcoded in notebook Step 1 and `review_suggestions.py`):
`C:\Users\Alfonso(FonsoP)Panli\Desktop\Projects\Competitor Analysis (client scrape)\data\`

```
candidate_tracker_report_extract.xlsx   # current input export (INPUT_FILE)
client_extraction_output.xlsx           # notebook output (overwritten every run)
client_extraction_reviewed.xlsx         # user's filled-in copy of the output (never overwrite)
client_terms_review.xlsx                # Step 9, edited IN PLACE: KEEP/IGNORE/rename per client name
accuracy_check.xlsx                     # Step 10, edited IN PLACE: random sample checked by human/LLM
backups/                                # dated copies of the two files above, made before each rewrite
client_extraction_llm_suggestions.xlsx  # review_suggestions.py output
qwen_cache.jsonl                        # LLM response cache
```

Paths with backslashes and parentheses must stay as raw strings: `Path(r"C:\...")`.

Resume data contains personal information:
- Keep processing local; don't send it to cloud APIs without asking the user.
- Never copy data files into the repo. `.gitignore` blocks data files in this folder as a safety
  net, but the real protection is keeping them in `DATA_DIR`.
- Commit the notebook with outputs cleared; cell outputs can contain resume text.

## Input data

Current export (18,302 rows, 15,718 distinct JXID, 3,640 distinct Company texts) has columns:
`JXID`, `JXURL`, `CS UserName`, `Email`, `Labels`, `Skills`, `Industry`, `Company`, `Job Title`,
`Work History Campaign`. `Client flag` / `Possible Client` are NOT in it, so Manual Label Check is
skipped. `Work History Campaign` is filled on ~3,250 competitor rows and looks like the client/account
name; it is not used yet (see Next steps). The older 1,005-row sample had columns
`Labels`, `Skills`, `Industry`, `Company`, `Client flag`, `Possible Client`.
Only `Company` is required. `Client flag` (1 = has client) and `Possible Client` are the user's
hand labels on a small number of rows. `Industry` values like
`Call Center / IT-Enabled Services / BPO` mean "worked at a BPO"; other industries hint at a client.

Competitor list (41): Outsourced.ph, Emapta, TOA Global (The Outsourced Accountant), Remote Employee,
KMC Solutions, Remote Staff (PH), MicroSourcing, Support Services Group (SSG), SupportNinja, Shore360,
Engaged Solutions, Cloud Accountant Staffing (CAS), Boomering Inc., DOXA Talent, ConnectOS,
Flatworld Solutions, Auxis, Connext (Connext Global Solutions), Virtual Latinos, hammerjack,
ATHENA BPO S.A.S, Cloudstaff, Penbrothers, Sourcefit, Booth & Partners, Staff Domain, Beepo, Infinit-O,
Magellan Solutions, Unity Communications, Peak Support, SixEleven Global, Hatchit Solutions, Cyberbacker,
MyOutDesk, Wing Assistant, Athena, Hire Horatio, Somewhere, Pearl Talent, Helpware.

## How the extraction works (notebook)

Core idea: we already know one half of the Company string (the competitor), so **subtract it and
inspect what's left**.

1. Strip descriptors ("Outsource Company", "Australian Account", "Seat Leasing"…) and capture
   region hints ("AU Clients", "US Clients", "New Zealand Clients") into `Region Hint`.
2. Match the competitor with regex aliases in `COMPETITORS`. Each match also eats trailing
   `SUFFIX_WORDS` (Inc, Philippines, Pampanga, Clark, WFH, Versatile Services…) so the competitor's
   legal-entity names and office locations are removed with it.
3. Split the residual on separators (`/ | ; ( ) , – —`, spaced hyphens, `Client:`), peel connector
   words (under, through, at, client), legal tails (Pty Ltd, Inc) and trailing geography
   (Australia, NSW, AU…, moved into `Client Location`). What remains = client candidates.
4. Canonicalise client spellings across rows (normalised key + prefix match ≥6 chars + difflib
   ratio > 0.9). Reviewer-typed names win as the display name.
5. Flag rows for review via `REVIEW_PATTERNS` (known traps) plus: no competitor matched, several
   candidates, former names ("formerly X").

6. Apply client-name decisions from the terms file (Step 6, after canonicalisation): IGNORE drops
   the name, KEEP keeps it, any other text renames it. Matched on the grouped name or any of its
   spellings. Names ≥5 letters within `SIMILAR_IGNORE` (0.88) of an IGNOREd name are ignored too
   (misspellings); an explicit decision on the name itself always wins. The "several candidates"
   flag is computed after this, so ignoring junk also shrinks Needs Review.

Notebook steps: 1 Settings · 2 Matching rules (the only cell normally edited) · 3 Extraction logic
and helpers (incl. `write_book`) · 4 Load · 5 Load review + term decisions · 6 Run · 7 Review list
and summaries · 8 Write main output · 9 Client terms file · 10 Accuracy check file.

Processing is per **distinct** Company string, then mapped back to rows.

### Output workbook sheets

- **Read Me**: reviewer instructions.
- **All Rows**: original data + `Competitor`, `Extracted Client`, `Client Location`, `Region Hint`,
  `Extraction Status`, `Review Notes`, `Client Implied by Industry`, `Matches Manual Label`.
  Status values: client found · region only · no client · needs review · reviewed · blank.
- **Needs Review**: one line per distinct Company text, sorted by `Rows` desc. Columns:
  `Company`, `Rows`, `Competitor`, `Extracted Client`, `Why Flagged`, and yellow input columns
  `Reviewer: Competitor`, `Reviewer: Client`, `Reviewer: Notes`.
- **Client Summary**: Competitor, Client, Confirmed Rows, Rows Pending Review, Client Locations.
- **Client Implied**: competitor rows with no client named but a non-BPO industry, grouped.
- **Manual Label Check**: rows where the user's hand label disagrees with the extraction.

### Review loop

Reviewer fills yellow columns: `OK` (accept), `NONE` (not a competitor / no client), or the
correct value; multiple clients separated by `;`. Blank competitor = accept. Both blank = skipped,
comes back next run. User saves under a new name (`client_extraction_reviewed.xlsx`), sets
`REVIEWED_FILE` in Step 1, and reruns. Decisions are keyed on the exact Company text and apply to
every row with that text. The notebook refuses to run if `REVIEWED_FILE == OUTPUT_FILE`.

### Client terms file (Step 9, `TERMS_FILE`)

One line per grouped client name, sorted by Rows (counted BEFORE decisions, so ignored names still
show their impact). Columns: Client, Rows, Candidates (distinct JXID), Hints, yellow `Decision` /
`Decided By` (Manual/LLM) / `Notes`, This Run (what was applied), Similar Names (≥ `SIMILAR_SHOW`
0.80, with row counts), Competitors, Spellings Seen, Example Company Text. Hints come from
`SUSPECT_WORDS` / `LINKING_WORDS` in Step 2 and never change results. The file is rewritten each
run with answers carried over (matched by name key or any spelling); answered names missing from
the current data are kept with Rows 0 ("not in current data"). Backup to `backups/` first.

### Accuracy check file (Step 10, `CHECK_FILE`)

Random sample of distinct Company texts (`CHECK_SAMPLE`: 40 "client found" + 10 "no client" kept
unchecked; seed `CHECK_SEED`). Texts whose names have a terms-file decision (incl. fuzzy ignore,
`p["term_decided"]`) are excluded from new samples. Yellow `Correct Competitor` / `Correct Client`
(OK / NONE / typed; blank = OK) / `Checked By` / `Notes`. Each run re-scores every checked line
against the current extraction (Current Competitor/Client, Result) and writes a Score sheet:
overall, by status, by checker, row-weighted. **Answers only measure; they never feed back into the
extraction**, otherwise the score would always be 100%.

## Design decisions (keep these)

- **Review can be done by a person or an LLM** (user decision, Nov 2026). The terms and check
  files record who answered in `Decided By` / `Checked By` so the two can be compared on the Score
  sheet. Whatever fills them must only use names present in the Company text.
- **The terms and check files are edited in place** (user asked for "mark it in the same file").
  The notebook must keep every answer when rewriting them and back them up first.
- **Manual Label Check is separate from Needs Review on purpose.** The user's hand labels may come
  from the resume body, which the Company text can't show. Review decisions apply to every row with
  the same text, so a client found in one "TOA Global" resume must not be copied to all of them.
- `review_suggestions.py` still only fills `LLM Suggested …` columns on Needs Review. Small local
  models have little world knowledge about obscure companies and answer confidently and wrongly,
  so measure an LLM on the accuracy check file before trusting its decisions.
- **Competitor brands and entities are aliases, not clients**: MyCloud People (TOA Global entity),
  ShoreAgent / ShoreSuite / ShoreRemote (Shore360 brands), KMC MAG / KMC Savills, Emapta Versatile
  Services. Add new ones to `COMPETITORS`.
- Original input columns are never modified; extracted columns are appended.

## Known traps found in the sample

- `TOA Corporation` is a Japanese construction company, not TOA Global.
- `REMOTE EMPLOYEE` on its own may describe the job, not the competitor Remote Employee.
- Generic competitor names (Athena, Somewhere) will cause false matches at scale; bare matches go to review.
- `TOA Global; Deloitte Philippines; Scrubbed.Net` is a list of employers, not clients (semicolon rule).
- Unverified, flagged for review: `DOXA7` (may not be DOXA Talent), `Salmat Services (Microsourcing)`
  (may be an acquired entity), `Jobs360/Shore360` and `Australian Outsource Desk (TOA Global)`
  (may be competitor brands).
- "Beepo Real Estate" is a vertical, not a client.

## Results on the 1,005-row sample

- ~7% of rows name a client; 56 distinct competitor-client pairs; 16 region-only rows; ~90% are
  just the competitor name.
- Naming rate varies: Emapta 19%, Shore360 9%, TOA Global 6%, Beepo 3%, Hammerjack 0%.
- Repeat clients: W.E. O'Neil Construction (4, via both Shore360 and Emapta), Vincents Chartered
  Accountants (3, TOA), Infinite Energy, CV Services Group, Parallaxx, HLB Mann Judd (2 each).
- 14 distinct strings went to review.
- The user's 4 hand-labelled rows all agreed with the extraction.

## LLM component (qwen_client.py + review_suggestions.py)

- Runs locally via **Ollama**, model `qwen3.5:4b` (CPU only; ~4–5 GB RAM at 4K context; 16 GB
  machine recommended). `gemma4:e4b` is the step-up option with 32 GB RAM.
- `qwen_client.py`: `QwenConfig` (all settings), `QwenClient.check()`, `ask()`, `ask_json(schema=…)`,
  `map(items, prompt_template_or_fn, system, schema)`, `QwenResult` (text, data, timings, error).
  Retries, JSONL cache, think-mode fallback, progress/ETA. **Stdlib only; keep it that way.**
  Job-specific prompts, schemas and settings must live outside the module.
- `review_suggestions.py`: reads the Needs Review sheet, sends each line to Qwen with a JSON schema
  (competitor, clients, confidence, reason), writes `client_extraction_llm_suggestions.xlsx`.
  Has a `LIMIT` setting for timing tests.
- `think=False` by default: thinking tokens are slow on CPU.
- Tested only against a mock Ollama server. **Not yet run against the real model.** First job:
  run with `LIMIT = 10` and check answers against the known cases above.

## Next steps (in rough priority)

0. Open items raised in the Nov 2026 review, not yet done:
   - Needs Review decisions don't accumulate: Step 5 reads ONE reviewed file, and reviewed texts
     drop off the next Needs Review sheet, so pointing at round 2's file loses round 1. Needs a
     persistent decisions ledger (like the terms file).
   - Use `Work History Campaign` as a second client source.
   - Client Summary counts rows, not distinct JXID.
   - Client Implied sheet is too big on the full export to act on.
   - Ollama is not installed on the user's machine yet.
1. Run `review_suggestions.py` on real Ollama; measure speed; check accuracy on the known traps
   and on the accuracy check file. Tune the SYSTEM prompt if needed. An LLM pass that fills the
   terms file / check file must set `Decided By` / `Checked By` = LLM.
2. Integrate the LLM step into the notebook as an **optional** step (off by default) that adds the
   LLM Suggestion columns to the Needs Review sheet. The user asked to hold off on changing the
   notebook until the module is proven.
3. **Resume-body extraction** (biggest expected gain): for rows whose Company is a competitor with
   no client named, read the work-experience text for that job and ask the LLM for the client.
   Longer prompts → slow on CPU; plan for batch/overnight runs, use the cache, raise `num_ctx`.
   Needs the resume text in the export; ask the user what's available.
4. Grow the accuracy check file to a few hundred checked lines; report its Score after rule changes.
5. Optional: validate/enrich canonical client names (country, industry) against company databases.

## Working conventions

- Prefer editing rules in notebook Step 2 over adding special cases in the logic.
- Don't overwrite the user's reviewed file; outputs go to new names.
- Explain changes in plain language; the user reviews results in Excel, not code.
- Test changes against the sample before handing back, and say what was and wasn't tested.
