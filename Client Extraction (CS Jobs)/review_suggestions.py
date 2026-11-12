"""
review_suggestions.py: uses qwen_client.py to pre-fill suggestions for the Needs Review sheet.

Everything specific to this job lives in this file: the settings, the prompts and the answer
shape. To use the Qwen module somewhere else, copy this file and change those three blocks.

Reads:  <DATA_DIR>/client_extraction_output.xlsx   (sheet "Needs Review", made by the notebook)
Writes: <DATA_DIR>/client_extraction_llm_suggestions.xlsx
        The same sheet with four LLM Suggestion columns added. Your yellow Reviewer columns
        are left blank on purpose: the model suggests, you decide.

Run:    python review_suggestions.py      (with qwen_client.py in the same folder)
"""
from pathlib import Path
import pandas as pd
from qwen_client import QwenClient, QwenConfig

# ============================================================ 1. Settings
DATA_DIR = Path(r"C:\Users\Alfonso(FonsoP)Panli\Desktop\Projects\Competitor Analysis (client scrape)\data")
INPUT_FILE = DATA_DIR / "client_extraction_output.xlsx"
INPUT_SHEET = "Needs Review"
OUTPUT_FILE = DATA_DIR / "client_extraction_llm_suggestions.xlsx"
LIMIT = None            # e.g. 10 for a quick timing test; None = every row

CONFIG = QwenConfig(
    model="qwen3.5:4b",
    num_ctx=4096,        # plenty for one short Company string per request
    temperature=0,       # same input -> same answer
    seed=7,
    think=False,         # faster on CPU; set True to compare quality
    timeout=300,
    cache_path=str(DATA_DIR / "qwen_cache.jsonl"),   # reruns skip rows already answered
)

# ============================================================ 2. Prompts
COMPETITORS = [
    "Outsourced.ph", "Emapta", "TOA Global (The Outsourced Accountant)", "Remote Employee", "KMC Solutions",
    "Remote Staff (PH)", "MicroSourcing", "Support Services Group (SSG)", "SupportNinja", "Shore360",
    "Engaged Solutions", "Cloud Accountant Staffing (CAS)", "Boomering Inc.", "DOXA Talent", "ConnectOS",
    "Flatworld Solutions", "Auxis", "Connext (Connext Global Solutions)", "Virtual Latinos", "hammerjack",
    "ATHENA BPO S.A.S", "Cloudstaff", "Penbrothers", "Sourcefit", "Booth & Partners", "Staff Domain", "Beepo",
    "Infinit-O", "Magellan Solutions", "Unity Communications", "Peak Support", "SixEleven Global",
    "Hatchit Solutions", "Cyberbacker", "MyOutDesk", "Wing Assistant", "Athena", "Hire Horatio", "Somewhere",
    "Pearl Talent", "Helpware",
]

SYSTEM = f"""You review the employer field from Philippine resumes. People who worked at an
outsourcing company sometimes add the overseas client they were assigned to, in any format.

Known outsourcing competitors: {", ".join(COMPETITORS)}.

For each employer text decide:
- competitor: which known competitor it refers to, or "" if none. Watch for different companies
  with similar names (e.g. "TOA Corporation" is not TOA Global).
- clients: the client companies named, as written. Not clients: the competitor's own legal
  entities or sub-brands, office locations (Clark, Pampanga, Makati), work arrangements (WFH),
  industries or descriptions ("Real Estate", "Australian Account"), or other employers in a list.
- confidence: "high", "medium" or "low". Use "low" whenever you would have to know facts about a
  specific company to be sure. Never invent a company name that is not in the text.
- reason: one short sentence."""

PROMPT = """Employer text: {Company}
The automatic extraction found competitor "{Competitor}" and client "{Extracted Client}".
It was flagged because: {Why Flagged}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "competitor": {"type": "string"},
        "clients": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": {"type": "string"},
    },
    "required": ["competitor", "clients", "confidence", "reason"],
}

# ============================================================ 3. Run
if __name__ == "__main__":
    qwen = QwenClient(CONFIG)
    qwen.check()

    df = pd.read_excel(INPUT_FILE, sheet_name=INPUT_SHEET, dtype=str).fillna("")
    if LIMIT:
        df = df.head(LIMIT)
    print(f"{len(df)} rows to suggest for")

    results = qwen.map(df.to_dict("records"), prompt=PROMPT, system=SYSTEM, schema=SCHEMA)

    def col(r, key, join=False):
        if not r.ok or not isinstance(r.data, dict):
            return ""
        v = r.data.get(key, "")
        return "; ".join(map(str, v)) if join and isinstance(v, list) else str(v)

    df["LLM Suggested Competitor"] = [col(r, "competitor") for r in results]
    df["LLM Suggested Client"] = [col(r, "clients", join=True) or ("NONE" if r.ok else "") for r in results]
    df["LLM Confidence"] = [col(r, "confidence") for r in results]
    df["LLM Reason"] = [col(r, "reason") if r.ok else f"ERROR: {r.error}" for r in results]

    df.to_excel(OUTPUT_FILE, sheet_name=INPUT_SHEET, index=False)

    live = [r for r in results if r.ok and not r.cached]
    if live:
        avg = sum(r.seconds for r in live) / len(live)
        print(f"Average {avg:.1f}s per row, {sum(r.tokens_per_second for r in live)/len(live):.1f} tokens/s")
    print(f"Errors: {sum(not r.ok for r in results)}  |  Saved {OUTPUT_FILE}")
