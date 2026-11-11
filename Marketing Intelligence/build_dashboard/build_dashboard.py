"""Build the Account Priority Dashboard (a single HTML file) from the processed data.

Part 2 of the Marketing Intelligence pipeline:
    1. format data/format_priority_data.ipynb   merges, formats and scores HubSpot + MyStaff and saves the processed data
                                                (account_priority_dashboard_data*.json) to the LOCAL data folder
    2. build_dashboard/build_dashboard.py       (this script) reads that JSON and writes the dashboard to the same LOCAL data folder

Everything the page needs is in this folder:
    dashboard_template.html          the page (layout, charts, filters, text); data goes in at /*__DATA__*/
    assets/tokens.css                Cloudstaff design tokens        -> /*__TOKENS__*/
    assets/cloudstaff-logo-landscape.svg  Cloudstaff logo            -> <!--__LOGO__-->

The built page embeds every account row, so it contains confidential client data. It is written next to the raw and
processed data, outside the repo. Don't use --out to write it inside the repo.

Usage (from the "Marketing Intelligence" folder or anywhere):
    python build_dashboard/build_dashboard.py                     # newest processed JSON in the local data folder
    python build_dashboard/build_dashboard.py --data path/to/account_priority_dashboard_data.json
    python build_dashboard/build_dashboard.py --out "C:/somewhere/local/{date}_My_Dashboard.html"
{date} in --out becomes today's date (YYYY-MM-DD).
"""
import argparse
import datetime as dt
import html as htmlmod
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path.home() / "Desktop/Projects/Marketing Intelligence Priority/Data"   # local, outside the repo
DATA_GLOB = "account_priority_dashboard_data*.json"
DEFAULT_OUT = DATA_DIR / "{date}_Account_Priority_Dashboard.html"     # local, next to the data (it embeds client data)
TEMPLATE = HERE / "dashboard_template.html"
TOKENS = HERE / "assets/tokens.css"
LOGO = HERE / "assets/cloudstaff-logo-landscape.svg"

# what the page reads; checked before building so a format change fails here, not in the browser
REQUIRED_META = ["title", "subtitle", "source", "extract", "generated", "shown_teams", "roles", "band_order", "default_example",
                 "notice", "trigger_teams"]
REQUIRED_SETTINGS = [   # settings keys the page reads by name (every weight and threshold it shows comes from the data)
    "web_max_nl", "web_max_og", "news_max_nl", "news_max_og", "dia_max", "competitor_max", "seat_max_og", "tb_share", "ff_share",
    "vol_share", "vol_cap", "news_share", "jobs_share", "jobs_cap", "base_web", "base_news", "base_seats", "mod_min", "mod_max",
    "bdm_min", "hot_days", "hot_bonus", "hot_bonus_diamond", "seat_0", "seat_1_5", "seat_6_10", "seat_11",
    "hiring_min_postings", "heavy_visits_min", "campaign_news_days",
    *[f"news_{i}" for i in range(1, 9)], *[f"rec_{i}" for i in range(1, 5)],     # news strength and recency tables
]
REQUIRED_ROW_FIELDS = [
    "account_id", "company_name", "goal", "industry", "employee_band", "region", "web_visits_30d", "team_builder_visit",
    "form_fill_30d", "news_signal", "news_signal_date", "job_postings_30d", "hiring_spike", "diamond_referral",
    "competitor_client", "industry_trend", "seats_added_6m", "industry_modifier", "web_signal", "news_jobs_signal",
    "seat_signal", "seat_band", "web_pts", "news_jobs_pts", "seat_pts", "diamond_pts", "competitor_pts", "base_points",
    "workbook_score", "workbook_tier", "priority_score", "tier", "hot_trigger", "estimated_fields", "estimated",
    "sort_key", "csv_score", "csv_tier", "role", "team", "industry_lbl", "band_lbl", "profile", "chips",
]


def newest_data_file():
    files = sorted(DATA_DIR.glob(DATA_GLOB), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No {DATA_GLOB} in {DATA_DIR}. Run format data/format_priority_data.ipynb with SAVE_OUTPUT = True first.")
    return files[-1]


def validate(data):
    missing_top = [k for k in ["meta", "settings", "qa", "rows"] if k not in data]
    assert not missing_top, f"data is missing {missing_top}"
    missing_meta = [k for k in REQUIRED_META if k not in data["meta"]]
    assert not missing_meta, f"meta is missing {missing_meta}"
    missing_settings = sorted(set(REQUIRED_SETTINGS) - {r["key"] for r in data["settings"]})
    assert not missing_settings, f"settings are missing {missing_settings} (re-run the format_priority_data notebook)"
    keys = {r["key"] for r in data["settings"]}   # tiers: by rank within each goal (dashboard_v2) or by fixed scores (older data)
    assert {"tier1_share", "tier2_share"} <= keys or {"tier1", "tier2"} <= keys, "settings have no tier rule (tier1_share/tier2_share or tier1/tier2)"
    assert data["rows"], "no rows"
    missing_fields = sorted({f for r in data["rows"] for f in REQUIRED_ROW_FIELDS if f not in r})
    assert not missing_fields, f"rows are missing {missing_fields}"
    assert all(r["team"] in data["meta"]["shown_teams"] for r in data["rows"]), "a row is on a list the page doesn't show"
    ids = [r["account_id"] for r in data["rows"]]
    assert len(ids) == len(set(ids)), "duplicate account_id"
    assert data["meta"]["default_example"] in ids, "default_example is not an account in the data"


def build(data_path, out):
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    validate(data)
    page = TEMPLATE.read_text(encoding="utf-8")
    logo = re.sub(r"<\?xml.*?\?>", "", LOGO.read_text(encoding="utf-8")).strip()
    # allow_nan=False: NaN is not valid JSON and would break JSON.parse in the page; "</" is escaped so the data can't close the <script>
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    for marker, value in [("/*__TOKENS__*/", TOKENS.read_text(encoding="utf-8")), ("<!--__LOGO__-->", logo), ("/*__DATA__*/", payload)]:
        assert page.count(marker) == 1, f"template must contain {marker} exactly once"
        page = page.replace(marker, value)
    page = page.replace("__TITLE__", htmlmod.escape(data["meta"]["title"]))

    out = Path(str(out).replace("{date}", f"{dt.date.today():%Y-%m-%d}"))
    if data["meta"].get("mock_signals") and "MOCK" not in out.stem:   # a page with mock signals must never look like a real one
        out = out.with_name(out.stem + "_MOCK_SIGNALS" + out.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"data:  {data_path} ({len(data['rows'])} accounts, generated {data['meta'].get('generated', '?')})")
    print(f"wrote: {out} ({out.stat().st_size / 1e6:.2f} MB)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=None, help=f"processed JSON (default: newest {DATA_GLOB} in {DATA_DIR})")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output HTML path; {date} = today")
    a = ap.parse_args()
    build(a.data or newest_data_file(), a.out)
