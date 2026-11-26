"""Lead lists: collect, grade and publish (python -m cloudstaff_dev.leads ...).

    run <list> [--from STEP] [--only a,b] [--skip a,b] [--download] [--dry-run]
                        every step in Marketing Intelligence/lead_lists/<list>/list.toml, in order (collect -> grade -> page + check)
    grade <list>        lead_grades_<list>.xlsx + .json from what is already collected
    build <list>        the dashboard page from the grades (+ industry trends), then a headless check
    trends [--download] the Industry trends data (monthly, after the 1st; --download fetches the new Companies House file)
    lists               the lead lists there are

Each step is run as its own process with the command printed first, so any step can be re-run by hand.
"""
import argparse
import subprocess
import sys
import time

from .config import LeadList, available

SIG = "cloudstaff_dev.signals"


def commands(lst: LeadList, download: bool) -> dict:
    s, name = lst.settings, lst.name
    co, par, db, out = str(lst.companies), str(lst.parents), str(lst.jobs_db), str(lst.collected)
    dl = lambda step: ["--download"] if download and s.get("downloads", {}).get(step) else []
    return {
        "prepare": ["-m", "cloudstaff_dev.leads.prepare", "--list", name],
        "filings": ["-m", SIG, "filings", "--companies", co, "--registers", s.get("registers", "uk"), "--db", db],
        "news": ["-m", SIG, "run", "--companies", co, "--db", db, "--read-articles", "--read-max-per-company", "5"],
        "jobs": ["-m", SIG, "jobs", "--companies", co, "--db", db],
        "parents": ["-m", SIG, "run", "--companies", par, "--db", db],
        "nlp": ["-m", SIG, "nlp", "run", "--db", db, "--scope", "company", "--stages", "entities,events"],
        "export": ["-m", SIG, "export", "--db", db, "--out", out, "--lookback-days", str(s.get("news_lookback_days", 365))],
        "cqc": ["-m", f"{SIG}.registers.cqc", "--list", name] + dl("cqc"),
        "contracts": ["-m", f"{SIG}.registers.contracts", "--list", name],
        "ownership": ["-m", f"{SIG}.registers.ownership", "--list", name] + dl("ownership"),
        "officers": ["-m", f"{SIG}.registers.officers", "--list", name],
        "adzuna": ["-m", f"{SIG}.jobs.adzuna", "--list", name],          # trial only: never in a list's steps by default
        "grade": ["-m", "cloudstaff_dev.leads", "grade", name],
        "build": ["-m", "cloudstaff_dev.dashboards.build", "lead_grades", "--list", name, "--check"],
    }


def run(a):
    lst = LeadList(a.list)
    cmds = commands(lst, a.download)
    steps = list(lst.settings["steps"])
    unknown = [x for x in steps if x not in cmds]
    if unknown:
        raise SystemExit(f"{a.list}.toml lists unknown steps {unknown}; known: {list(cmds)}")
    if a.only:
        steps = [x for x in a.only.split(",") if x]
    elif a.from_step:
        steps = steps[steps.index(a.from_step):]
    steps = [x for x in steps if x not in (a.skip or "").split(",")]
    if not a.dry_run:
        lst.work.mkdir(parents=True, exist_ok=True)
        lst.collected.mkdir(parents=True, exist_ok=True)
    print(f"lead list {lst.name}: {', '.join(steps)}  (exports from {lst.inputs})")
    for step in steps:
        cmd = [sys.executable] + cmds[step]
        print(f"\n=== {step}: python {' '.join(cmds[step])}", flush=True)
        if a.dry_run:
            continue
        t = time.time()
        r = subprocess.run(cmd)
        print(f"=== {step}: exit {r.returncode} ({time.time() - t:.0f} s)", flush=True)
        if r.returncode:
            raise SystemExit(f"step {step} failed: fix it, then `python -m cloudstaff_dev.leads run {lst.name} --from {step}`")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m cloudstaff_dev.leads", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="every step of a lead list, in order")
    r.add_argument("list")
    r.add_argument("--from", dest="from_step", help="start at this step")
    r.add_argument("--only", help="only these steps, comma-separated")
    r.add_argument("--skip", help="leave out these steps, comma-separated")
    r.add_argument("--download", action="store_true", help="monthly: fetch new CQC and PSC files (where the list's toml allows)")
    r.add_argument("--dry-run", action="store_true", help="print the commands only")
    g = sub.add_parser("grade", help="grade a list from what is collected")
    g.add_argument("list", nargs="?", default="apollo_emea")
    b = sub.add_parser("build", help="build and check a list's dashboard page")
    b.add_argument("list", nargs="?", default="apollo_emea")
    t = sub.add_parser("trends", help="the Industry trends data (monthly)")
    t.add_argument("--download", action="store_true")
    sub.add_parser("lists", help="the lead lists there are")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a)
    elif a.cmd == "grade":
        from .pipeline import main as grade_main
        grade_main([a.list])
    elif a.cmd == "build":
        from cloudstaff_dev.dashboards.build import main as build_main
        build_main(["lead_grades", "--list", a.list, "--check"])
    elif a.cmd == "trends":
        from .industry_trends import main as trends_main
        trends_main(["--download"] if a.download else [])
    else:
        print("\n".join(available()))


if __name__ == "__main__":
    main()
