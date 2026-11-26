"""The lead list being graded: its settings, target markets and every file it reads or writes.

A list is a folder, Marketing Intelligence/lead_lists/<name>/: list.toml (settings, steps, target markets) and the
hand-kept CSVs. Nothing list-specific lives in the package. The grading modules read the list through `L`
(e.g. `L.cqc_providers`, `L.subsectors`), never through constants, so a second list can't pick up the first list's
files or rules. `use(name)` switches lists; the pipeline calls it first.
"""

import tomllib
from pathlib import Path

from cloudstaff_dev.common import paths

LISTS_ROOT = paths.REPO / "Marketing Intelligence" / "lead_lists"
TEMPLATES = Path(__file__).resolve().parents[1] / "dashboards" / "templates"


def available() -> list[str]:
    return sorted(p.parent.name for p in LISTS_ROOT.glob("*/list.toml"))


class LeadList:
    def __init__(self, name: str):
        self.rules = LISTS_ROOT / name                       # the list's folder: list.toml + hand-kept CSVs (git)
        f = self.rules / "list.toml"
        if not f.exists():
            raise SystemExit(f"no lead list {name!r}: expected {f} (lists: {', '.join(available())})")
        self.settings = s = tomllib.loads(f.read_text(encoding="utf-8-sig"))   # -sig: Notepad / PowerShell may add a BOM
        self.name = name
        d = paths.lead_list(name)
        self.inputs, self.work, self.collected, self.grades = d["inputs"], d["work"], d["collected"], d["grades"]
        if s.get("inputs"):                                   # the export folder, relative to <MI>/inputs (list.toml `inputs`)
            self.inputs = paths.MI_INPUTS / s["inputs"]
        self.title = s.get("title", name)
        self.subtitle = s.get("subtitle", "")
        self.source = s.get("source", "")
        self.dashboards = paths.MI_DASHBOARDS / self.title.replace(" ", "_")
        t = s.get("template", "lead_grades.html")             # the list's own template if it has one, else the shared one
        self.template = self.rules / t if (self.rules / t).exists() else TEMPLATES / t
        # ------------------------------------------------ who works it, how fit is looked up, target markets
        self.team = s.get("team", "BDM Marketing")
        self.fit_country = s.get("fit_country", "Unknown")
        self.supplier_groups = set(s.get("supplier_groups", []))
        mk = s.get("markets", {})                             # {market: {...}}, in file order (first apollo_list match wins)
        self.list_target = {m["apollo_list"]: (n, set(m.get("industry_groups", []))) for n, m in mk.items()}
        self.list_target_groups = {n: set(m.get("industry_groups", [])) for n, m in mk.items()}
        self.target_codes = {n: {k: set(v) for k, v in m.get("target_codes", {}).items()} for n, m in mk.items()}
        self.service_lines = {n: dict(m.get("service_lines", {})) for n, m in mk.items()}
        self.subsectors = {n: {sub: {k: (v if isinstance(v, str) else set(v)) for k, v in r.items() if k != "pitch"}
                               for sub, r in m.get("subsectors", {}).items()} for n, m in mk.items()}
        self.subsector_pitch = {sub: r["pitch"] for m in mk.values() for sub, r in m.get("subsectors", {}).items()
                                if "pitch" in r}

    # ------------------------------------------------ work (local, not synced)
    companies = property(lambda s: s.work / "companies.csv")
    parents = property(lambda s: s.work / "parents.csv")
    jobs_db = property(lambda s: s.work / "news.db")           # read-only here: per-role posted dates, company cards
    # ------------------------------------------------ collected (scraper + register outputs)
    company_summary = property(lambda s: s.collected / "company_summary.csv")
    signal_events = property(lambda s: s.collected / "signal_events.csv")
    cqc_events = property(lambda s: s.collected / "cqc_events.csv")
    contract_awards = property(lambda s: s.collected / "contract_awards.csv")
    cqc_providers = property(lambda s: s.collected / "cqc_providers.csv")
    cqc_locations = property(lambda s: s.collected / "cqc_locations.csv")
    ownership = property(lambda s: s.collected / "ownership.csv")
    officers = property(lambda s: s.collected / "officers.csv")
    register_files = property(lambda s: {"CQC register": s.cqc_events, "Find a Tender": s.contract_awards})
    # ------------------------------------------------ hand-kept rules (repo)
    prepare_overrides = property(lambda s: s.rules / "overrides.csv")
    manual_events = property(lambda s: s.rules / "manual_events.csv")
    register_reviews = property(lambda s: s.rules / "register_match_reviews.csv")
    event_overrides = property(lambda s: s.rules / "event_overrides.csv")
    # ------------------------------------------------ outputs
    grades_xlsx = property(lambda s: s.grades / f"lead_grades_{s.name}.xlsx")
    grades_json = property(lambda s: s.grades / f"lead_grades_{s.name}.json")

    def owners_csv(self, as_of):
        return self.grades / f"owners_to_find_{as_of:%Y-%m-%d}.csv"


class _Current:
    """Attribute access goes to the list chosen by use(); apollo_emea until then."""
    _list = None

    def __getattr__(self, k):
        if _Current._list is None:
            use("apollo_emea")
        return getattr(_Current._list, k)


def use(name: str) -> LeadList:
    _Current._list = LeadList(name)
    return _Current._list


L = _Current()
