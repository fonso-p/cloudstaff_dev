"""Build the Marketing Intelligence dashboards: one single-file HTML page per dashboard, data embedded.

    python -m cloudstaff_dev.dashboards.build lead_grades [--list apollo_emea] [--data J] [--out H] [--check]
    python -m cloudstaff_dev.dashboards.build account_priority [--data J] [--out H] [--check]

Dashboards (templates/ next to this file; the house style, tokens.css and the logo, comes from the cs-dashboard
skill in .claude/skills/cs-dashboard/assets, the one copy every Cloudstaff dashboard uses):
  lead_grades       template: the list's list.toml `template` (its own folder first, else templates/lead_grades.html)
                    data: the list's lead_grades_<list>.json + MI outputs/industry_trends/industry_trends.json
                    page: MI dashboards/<list title>/<date>_<list title>.html   (e.g. EMEA_Lead_Grades)
  account_priority  data: newest MI outputs/account_priority/account_priority_dashboard_data*.json (the notebook's)
                    page: MI dashboards/Account_Priority/<date>_Account_Priority_Dashboard[_MOCK_SIGNALS].html

Template markers, each exactly once: /*__TOKENS__*/, <!--__LOGO__-->, /*__DATA__*/; __TITLE__ becomes meta.title.
The pages embed client data: they are written to the local Projects folder, never into the repo.
--check opens every page of the result in a headless browser (the skill's check_page.py): each must say errors: [].
"""
import argparse
import datetime as dt
import html as htmlmod
import json
import re
import subprocess
import sys
from pathlib import Path

from cloudstaff_dev.common import paths

HERE = Path(__file__).resolve().parent
SKILL = paths.REPO / ".claude" / "skills" / "cs-dashboard"
TOKENS = SKILL / "assets" / "tokens.css"
LOGO = SKILL / "assets" / "cloudstaff-logo-landscape.svg"
CHECK_PAGE = SKILL / "scripts" / "check_page.py"

# ---------------------------------------------------------------- Account Priority: what the page reads, checked first
AP_META = ["title", "subtitle", "source", "extract", "generated", "shown_teams", "roles", "band_order", "default_example",
           "notice", "trigger_teams"]
AP_SETTINGS = [   # settings keys the page reads by name (every weight and threshold it shows comes from the data)
    "web_max_nl", "web_max_og", "news_max_nl", "news_max_og", "dia_max", "competitor_max", "seat_max_og", "tb_share", "ff_share",
    "vol_share", "vol_cap", "news_share", "jobs_share", "jobs_cap", "base_web", "base_news", "base_seats", "mod_min", "mod_max",
    "bdm_min", "hot_days", "hot_bonus", "hot_bonus_diamond", "seat_0", "seat_1_5", "seat_6_10", "seat_11",
    "hiring_min_postings", "heavy_visits_min", "campaign_news_days",
    *[f"news_{i}" for i in range(1, 9)], *[f"rec_{i}" for i in range(1, 5)],     # news strength and recency tables
]
AP_ROW_FIELDS = [
    "account_id", "company_name", "goal", "industry", "employee_band", "region", "web_visits_30d", "team_builder_visit",
    "form_fill_30d", "news_signal", "news_signal_date", "job_postings_30d", "hiring_spike", "diamond_referral",
    "competitor_client", "industry_trend", "seats_added_6m", "industry_modifier", "web_signal", "news_jobs_signal",
    "seat_signal", "seat_band", "web_pts", "news_jobs_pts", "seat_pts", "diamond_pts", "competitor_pts", "base_points",
    "workbook_score", "workbook_tier", "priority_score", "tier", "hot_trigger", "estimated_fields", "estimated",
    "sort_key", "csv_score", "csv_tier", "role", "team", "industry_lbl", "band_lbl", "profile", "chips",
]


def validate_account_priority(data):
    missing_top = [k for k in ["meta", "settings", "qa", "rows"] if k not in data]
    assert not missing_top, f"data is missing {missing_top}"
    missing_meta = [k for k in AP_META if k not in data["meta"]]
    assert not missing_meta, f"meta is missing {missing_meta}"
    missing_settings = sorted(set(AP_SETTINGS) - {r["key"] for r in data["settings"]})
    assert not missing_settings, f"settings are missing {missing_settings} (re-run the format_priority_data notebook)"
    keys = {r["key"] for r in data["settings"]}   # tiers: by rank within each goal (dashboard_v2) or by fixed scores (older data)
    assert {"tier1_share", "tier2_share"} <= keys or {"tier1", "tier2"} <= keys, "settings have no tier rule (tier1_share/tier2_share or tier1/tier2)"
    assert data["rows"], "no rows"
    missing_fields = sorted({f for r in data["rows"] for f in AP_ROW_FIELDS if f not in r})
    assert not missing_fields, f"rows are missing {missing_fields}"
    assert all(r["team"] in data["meta"]["shown_teams"] for r in data["rows"]), "a row is on a list the page doesn't show"
    ids = [r["account_id"] for r in data["rows"]]
    assert len(ids) == len(set(ids)), "duplicate account_id"
    assert data["meta"]["default_example"] in ids, "default_example is not an account in the data"


def validate_lead_grades(data):
    missing_top = [k for k in ["meta", "qa", "rows"] if k not in data]
    assert not missing_top, f"data is missing {missing_top}"
    assert data["rows"], "no rows"
    ids = [r["account_id"] for r in data["rows"]]
    assert len(ids) == len(set(ids)), "duplicate account_id"


# ---------------------------------------------------------------- build
def render(template: Path, data: dict, out: Path) -> Path:
    page = template.read_text(encoding="utf-8")
    logo = re.sub(r"<\?xml.*?\?>", "", LOGO.read_text(encoding="utf-8")).strip()
    # allow_nan=False: NaN is not valid JSON and would break JSON.parse in the page; "</" is escaped so the data can't close the <script>
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    for marker, value in [("/*__TOKENS__*/", TOKENS.read_text(encoding="utf-8")), ("<!--__LOGO__-->", logo), ("/*__DATA__*/", payload)]:
        assert page.count(marker) == 1, f"template must contain {marker} exactly once"
        page = page.replace(marker, value)
    page = page.replace("__TITLE__", htmlmod.escape(data.get("meta", {}).get("title", "Dashboard")))
    out = Path(str(out).replace("{date}", f"{dt.date.today():%Y-%m-%d}"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote: {out} ({out.stat().st_size / 1e6:.2f} MB, {len(data.get('rows', []))} rows)")
    return out


def lead_grades(list_name="apollo_emea", data_path=None, out=None) -> Path:
    from cloudstaff_dev.leads.config import LeadList
    lst = LeadList(list_name)
    data_path = Path(data_path or lst.grades_json)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    trends = paths.INDUSTRY_TRENDS_OUT / "industry_trends.json"     # the Industry trends page; refreshed monthly on its own
    if trends.exists():
        data["trends"] = json.loads(trends.read_text(encoding="utf-8"))
    validate_lead_grades(data)
    slug = lst.title.replace(" ", "_")
    return render(lst.template, data, out or lst.dashboards / f"{{date}}_{slug}.html")   # list.toml `template`


def account_priority(data_path=None, out=None) -> Path:
    if data_path is None:
        files = sorted(paths.ACCOUNT_PRIORITY_OUT.glob("account_priority_dashboard_data*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            raise SystemExit(f"No account_priority_dashboard_data*.json in {paths.ACCOUNT_PRIORITY_OUT}. Run "
                             "Marketing Intelligence/account_priority/format_priority_data.ipynb with SAVE_OUTPUT = True first.")
        data_path = files[-1]
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    validate_account_priority(data)
    out = Path(out or paths.MI_DASHBOARDS / "Account_Priority" / "{date}_Account_Priority_Dashboard.html")
    if data["meta"].get("mock_signals") and "MOCK" not in out.stem:   # a page with mock signals must never look like a real one
        out = out.with_name(out.stem + "_MOCK_SIGNALS" + out.suffix)
    print(f"data:  {data_path} (generated {data['meta'].get('generated', '?')})")
    return render(HERE / "templates" / "account_priority.html", data, out)


def check(page: Path) -> bool:
    """Every page of the built file in a headless browser (cs-dashboard check_page.py). True when all say errors: []."""
    r = subprocess.run([sys.executable, str(CHECK_PAGE), str(page)], capture_output=True, text=True, encoding="utf-8")
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode == 0 and "errors: [" in r.stdout and all(x.strip().endswith("errors: []")
                                                                 for x in r.stdout.splitlines() if "errors:" in x)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dashboard", choices=["lead_grades", "account_priority"])
    ap.add_argument("--list", default="apollo_emea", help="lead_grades only: the lead list")
    ap.add_argument("--data", help="data JSON (default: see above)")
    ap.add_argument("--out", help="output HTML; {date} = today (default: see above)")
    ap.add_argument("--check", action="store_true", help="open the result in a headless browser and check every page")
    a = ap.parse_args(argv)
    page = lead_grades(a.list, a.data, a.out) if a.dashboard == "lead_grades" else account_priority(a.data, a.out)
    if a.check and not check(page):
        raise SystemExit("page check failed")


if __name__ == "__main__":
    main()
