"""Step 3b: gathered facts per lead: service lines, roles we fill, job recency, CQC and contract registers, sub-sectors,
ownership, owners and officers who are Apollo contacts."""

import json
import re

import pandas as pd

from cloudstaff_dev.common import paths

from .config import L
from .events import _codes
from .helpers import blank, jsonable
from .rules import DUPLICATE, OFFICER_ORDER, OWNERSHIP_EVENT_DAYS, OWNERSHIP_PRIVATE


def add_service_lines(leads, db):
    """Service lines found on the company's website card (L.service_lines for its list). No points: targeting and pitch."""
    if not db.exists():
        return leads.assign(service_lines=None)
    import sqlite3
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as con:
        cards = dict(con.execute("SELECT company_id, data FROM company_profiles WHERE company_id LIKE 'apollo-%'").fetchall())
    def tags(r):
        raw = cards.get("apollo-" + r["account_id"][3:])
        if not raw:
            return None
        c = json.loads(raw)
        text = " ".join([c.get("site_name") or "", c.get("description") or "", " ".join(c.get("keywords") or []), r["company_name"]]).lower()
        found = [k for k, rx in L.service_lines.get(r["lead_list"], {}).items() if re.search(rx, text)]
        return "; ".join(found) or None
    return leads.assign(service_lines=leads.apply(tags, axis=1))


def add_roles(leads, db):
    """Each lead's posted job titles matched to the roles Cloudstaff fills (roles.py), and the per-title list for the page."""
    cols = ["roles_listed", "roles_we_fill", "roles_we_fill_30d", "roles_possible", "roles_onsite", "roles_we_fill_categories", "roles_we_fill_titles"]
    report = paths.staff_report()
    if not db.exists() or not report:
        return leads.assign(**{k: None for k in cols}), {}, "no Staff Central report found: hiring counts every open role"
    import sqlite3
    from cloudstaff_dev.common.roles import RoleMatcher
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as con:
        jp = pd.read_sql("SELECT company_id, title, posted_at FROM job_postings WHERE company_id LIKE 'apollo-%'", con)
    jp["account_id"] = "AP-" + jp["company_id"].str.slice(7)
    jp["posted"] = pd.to_datetime(jp["posted_at"], errors="coerce")
    m = RoleMatcher(report).match(jp["title"].unique())
    jp = jp.merge(m, on="title", how="left")
    today = pd.Timestamp.today().normalize()
    jp["_fill"] = jp["verdict"] == "we fill"
    jp["_fill30"] = jp["_fill"] & (jp["posted"] >= today - pd.Timedelta(days=30))
    g = jp.groupby("account_id").agg(roles_listed=("title", "size"), roles_we_fill=("_fill", "sum"), roles_we_fill_30d=("_fill30", "sum"),
                                     roles_possible=("verdict", lambda s: int((s == "possible").sum())),
                                     roles_onsite=("verdict", lambda s: int((s == "on-site").sum())),
                                     roles_we_fill_categories=("jp_category", lambda s: "; ".join(sorted(set(s[jp.loc[s.index, "_fill"]].dropna())))),
                                     roles_we_fill_titles=("clean", lambda s: "; ".join(sorted(set(s[jp.loc[s.index, "_fill"]])))))
    per_lead = {k: [{"title": x.clean, "posted": jsonable(x.posted), "verdict": x.verdict, "jp_title": jsonable(x.jp_title),
                     "jp_category": jsonable(x.jp_category), "similarity": jsonable(x.similarity)} for x in d.sort_values("posted", ascending=False).itertuples()]
                for k, d in jp.groupby("account_id")}
    return leads.merge(g, on="account_id", how="left"), per_lead, f"{report.name} (JP titles only)"


def job_recency(leads, db):
    """Per lead: roles posted in the last 30 / 90 days and the newest posting date, from the scraper's per-role table."""
    cols = ["jobs_new_30d", "jobs_new_90d", "jobs_newest"]
    if not db.exists():
        return leads.assign(**{k: None for k in cols})
    import sqlite3
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as con:
        jp = pd.read_sql("SELECT company_id, posted_at FROM job_postings", con)
    jp["posted"] = pd.to_datetime(jp["posted_at"], errors="coerce")
    jp["account_id"] = "AP-" + jp["company_id"].str.replace("^apollo-", "", regex=True)
    today = pd.Timestamp.today().normalize()
    g = jp.groupby("account_id")["posted"].agg(jobs_new_30d=lambda s: int((s >= today - pd.Timedelta(days=30)).sum()),
                                                jobs_new_90d=lambda s: int((s >= today - pd.Timedelta(days=90)).sum()), jobs_newest="max")
    return leads.merge(g, on="account_id", how="left")


def load_reviews():
    """{(company_name, source, notice): (verdict, reviewed_by)} from L.register_reviews."""
    if not L.register_reviews.exists():
        return {}
    rv = pd.read_csv(L.register_reviews, dtype=str, keep_default_na=False)
    return {(r.company_name.strip(), r.source.strip(), r.notice.strip()): (r.verdict.strip().lower(), r.reviewed_by.strip())
            for r in rv.itertuples() if r.company_name.strip()}


def review_of(reviews, company, source, notice=""):
    """'confirmed' / 'rejected' (with who) or None, for one register match."""
    return reviews.get((company, source, notice or ""))


def register_events(leads):
    """CQC and Find a Tender events in the manual-events shape, keyed by account (not by name). `match` says how the lead
    was found in the register; rejected name matches are dropped, confirmed ones say so."""
    cols = ["account_id", "date", "category", "headline", "url", "publisher", "labelled_by", "note", "kind", "source", "match"]
    frames = [pd.read_csv(p, dtype=str, keep_default_na=False).assign(labelled_by=name) for name, p in L.register_files.items() if p.exists()]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=cols)
    d = pd.concat(frames, ignore_index=True)
    if L.cqc_providers.exists():                      # a CQC event is as good as the lead's CQC match
        basis = pd.read_csv(L.cqc_providers, dtype=str, keep_default_na=False).set_index("company_id")["cqc_match"]
        cq = d["source"] == "cqc"
        d.loc[cq, "match"] = d.loc[cq, "company_id"].map(basis)
    d["match"] = d["match"].fillna("")
    out = pd.DataFrame({"account_id": "AP-" + d["company_id"].str.replace("^apollo-", "", regex=True), "date": d["date"],
                        "category": d["category"], "headline": d["headline"], "url": d["url"], "publisher": d["publisher"],
                        "labelled_by": d["labelled_by"], "note": d["detail"], "kind": "register", "source": d["source"], "match": d["match"]})
    reviews, names = load_reviews(), dict(zip(leads["account_id"], leads["company_name"]))
    keep = []
    for r in out.itertuples():
        notice = r.url.rsplit("/", 1)[-1] if r.source == "fts" else ""
        rv = review_of(reviews, names.get(r.account_id, ""), r.labelled_by, notice) if r.match.startswith("name") else None
        keep.append(not (rv and rv[0] == "rejected"))
        if rv and rv[0] == "confirmed":
            out.loc[r.Index, "match"] = f"name, confirmed by {rv[1]}"
    return out[keep]


def add_cqc(leads):
    """CQC profile per lead (cqc.py): providers, locations, beds, service types, ratings. England care providers only."""
    if not L.cqc_providers.exists():
        leads["cqc_match"] = None
        return leads
    c = pd.read_csv(L.cqc_providers, dtype=str, keep_default_na=False, na_values=[""])
    c["account_id"] = "AP-" + c.pop("company_id").str.replace("^apollo-", "", regex=True)
    for k in ("cqc_locations", "cqc_care_homes", "cqc_beds", "cqc_homecare_locations", "cqc_needs_improvement",
              "cqc_needs_improvement_180d", "cqc_new_locations", "cqc_closed_locations"):
        c[k] = pd.to_numeric(c[k], errors="coerce")
    return leads.merge(c, on="account_id", how="left")


def review_flags(leads):
    """Apply L.register_reviews to the CQC match, and write match_review: what still needs a person's check."""
    reviews = load_reviews()
    cqc_cols = [c for c in leads.columns if c.startswith("cqc_")]
    flags = []
    for i, r in leads.iterrows():
        items = []
        if isinstance(r.get("cqc_match"), str) and r["cqc_match"].startswith("name"):
            rv = review_of(reviews, r["company_name"], "CQC register")
            if rv and rv[0] == "rejected":
                leads.loc[i, cqc_cols] = None
            elif rv and rv[0] == "confirmed":
                leads.loc[i, "cqc_match"] = f"name, confirmed by {rv[1]}"
            else:
                items.append(f"CQC matched by provider name ({r.get('cqc_providers')})")
        if isinstance(r.get("_contract_review"), str):
            items.append(r["_contract_review"])
        flags.append("; ".join(items) or None)
    leads["match_review"] = flags
    return leads


def add_subsectors(leads):
    """Sub-sector(s) from CQC service types (when matched), else from the activity codes. See L.subsectors."""
    subs, basis = [], []
    for r in leads.itertuples():
        rules = L.subsectors.get(r.lead_list, {})
        st = getattr(r, "cqc_service_types", None)
        st = st if isinstance(st, str) else ""
        if st and any("cqc" in v for v in rules.values()):
            found = [k for k, v in rules.items() if v.get("cqc") and re.search(v["cqc"], st, re.I)]
            if found:
                subs.append("; ".join(found)); basis.append("CQC service types"); continue
        sic, naics = [c[:4] for c in _codes(r.sic_us)], [c[:4] for c in _codes(r.naics)]
        uk = re.findall(r"\b(\d{5})\b", str(getattr(r, "uk_sic", "") or ""))
        found = [k for k, v in rules.items() if set(sic) & v["sic"] or set(naics) & v["naics"]
                 or any(u.startswith(tuple(v["uk"])) for u in uk)]
        subs.append("; ".join(found) or None); basis.append("activity codes" if found else None)
    leads["sub_sectors"], leads["sub_sector_basis"] = subs, basis
    return leads


def add_ownership(leads, ev, as_of):
    """Who owns the lead (ownership.py), cross-checked with Apollo's parent and the news. Writes `ownership` (one of
    OWNERSHIP_ORDER), `ownership_evidence` and `ownership_check` (a conflict for a person to look at)."""
    cols = ["ownership", "ownership_evidence", "ownership_number", "ownership_number_source", "ownership_number_name",
            "company_numbers", "company_type", "owner_chain", "owner_chain_steps", "top_owner", "group_companies", "owners_named",
            "owner_roles", "ownership_route", "cqc_charity_number", "cqc_provider_sector", "website_number_page", "psc_snapshot",
            "charity_number", "charity_name", "charity_status", "charity_income", "charity_match", "charity_note"]
    if L.ownership.exists():
        o = pd.read_csv(L.ownership, dtype=str, keep_default_na=False, na_values=[""])
        o["account_id"] = "AP-" + o.pop("company_id").str.replace("^apollo-", "", regex=True)
        o["group_companies"] = pd.to_numeric(o["group_companies"], errors="coerce")
        leads = leads.merge(o[["account_id"] + [c for c in cols if c in o.columns]], on="account_id", how="left")
    for c in cols:
        if c not in leads.columns:
            leads[c] = None
    leads["ownership"] = leads["ownership"].fillna("Not checked")
    recent = ev[(ev["published"] >= as_of - pd.Timedelta(days=OWNERSHIP_EVENT_DAYS))] if len(ev) else ev
    pe = recent[recent["category"] == "PE buyout"].groupby("account_id")["published"].max() if len(ev) else pd.Series(dtype=object)
    ma = recent[recent["category"] == "M&A"].groupby("account_id")["published"].max() if len(ev) else pd.Series(dtype=object)
    checks = []
    for i, r in leads.iterrows():
        cls, evid, notes = r["ownership"], r["ownership_evidence"], []
        if r["account_id"] in pe.index and cls in OWNERSHIP_PRIVATE | {"Unknown", "Not checked"}:
            cls, evid = "Investor-backed", f"PE buyout in the news ({pe[r['account_id']]:%b %Y})" + ("" if blank(evid) else f"; register: {evid}")
        if not blank(r.get("parent_company")):
            if cls in ("Unknown", "Not checked"):
                cls, evid = "Part of a corporate group", f"Apollo names a parent: {r['parent_company']}" + ("" if blank(evid) else f"; {evid}")
            elif cls in OWNERSHIP_PRIVATE:
                notes.append(f"Apollo names a parent ({r['parent_company']}) but Companies House shows individuals at the top")
        if r["account_id"] in ma.index and cls in OWNERSHIP_PRIVATE:
            notes.append(f"M&A in the news ({ma[r['account_id']]:%b %Y}): check who bought whom; the owner may have changed")
        if not blank(r.get("charity_note")):
            notes.append(r["charity_note"])
        if r.get("ownership_number_source") == "website":
            notes.append(f"company number read from its website ({r.get('ownership_number_name')}): confirm it is the same business")
        leads.at[i, "ownership"], leads.at[i, "ownership_evidence"] = cls, evid
        checks.append("; ".join(notes) or None)
    leads["ownership_check"] = checks
    leads["ownership_target"] = leads["ownership"].eq("Owner-managed")
    # how the controlling owner holds it (ownership.py): directly (named on the lead's own register entry) or through a
    # holding company. Shown for privately owned leads only
    leads.loc[~leads["ownership"].isin(OWNERSHIP_PRIVATE), "ownership_route"] = None
    return leads


PERSON_TITLE = r"^(mr|mrs|ms|miss|mx|dr|sir|dame|lord|lady|prof|professor|rev)\.?\s+"


def person_key(name):
    """'Mr Michael Charles Saunders' -> ('michael', 'saunders'): first and last word, titles and punctuation dropped."""
    w = [re.sub(r"[^a-z]", "", x) for x in re.sub(PERSON_TITLE, "", str(name or "").lower().strip()).replace("-", " ").split()]
    w = [x for x in w if x]
    return (w[0], w[-1]) if len(w) >= 2 else None


ROLE_ORDER = ["owner", "co-owner", "minority owner"]   # owner = controls it; co-owner = nobody controls it alone;


def match_owner_contacts(leads, contacts):
    """Apollo contacts who are named owners (Companies House register), matched on first + last name within the same
    lead. Marks contacts["is_owner"] and contacts["owner_role"] ("owner", "co-owner", "minority owner", with the stake);
    writes owner_contacts and owners_to_find (named owners with no Apollo contact, as JSON with role and stake).
    Only the name is used: never the register's birth date, nationality or address."""
    owners = {}
    for r in leads.itertuples():
        try:
            roles = json.loads(r.owner_roles) if isinstance(r.owner_roles, str) and r.owner_roles else []
        except ValueError:
            roles = []
        d = {}
        for x in roles:                                # a person on two routes keeps their strongest role
            k = person_key(x["name"])
            if k and (k not in d or ROLE_ORDER.index(x["role"]) < ROLE_ORDER.index(d[k]["role"])):
                d[k] = x
        owners[r.account_id] = d
    officers = load_officers()
    hit = [owners.get(a, {}).get(person_key(n)) for a, n in zip(contacts["account_id"], contacts["name"])]
    ohit = [officers.get(a, {}).get(person_key(n)) for a, n in zip(contacts["account_id"], contacts["name"])]
    contacts["is_owner"] = [h is not None for h in hit]
    contacts["owner_role"] = [None if h is None else h["role"] + (f" ({h['band']})" if h.get("band") else "") for h in hit]
    contacts["officer_role"] = [None if h is None else h["role"] for h in ohit]
    # best contact: owners first (owner, co-owner, minority owner), each with officers (directors) before the rest;
    # then officers who own nothing; then the others in Apollo's seniority order
    contacts["_role_rank"] = [ROLE_ORDER.index(h["role"]) if h else 9 for h in hit]
    contacts["_not_officer"] = [h is None for h in ohit]
    contacts.sort_values(["account_id", "_role_rank", "_not_officer"], kind="stable", inplace=True)
    contacts.drop(columns=["_role_rank", "_not_officer"], inplace=True)
    own = contacts[contacts["is_owner"]]
    leads["owner_contacts"] = leads["account_id"].map(own.groupby("account_id")["name"].agg("; ".join))
    leads["best_owner_role"] = leads["account_id"].map(own.groupby("account_id")["owner_role"].first())
    off = contacts[contacts["officer_role"].notna()]
    leads["officer_contacts"] = leads["account_id"].map(off.groupby("account_id")["name"].agg("; ".join))
    first = contacts.groupby("account_id").first()
    leads["best_officer_role"] = leads["account_id"].map(first["officer_role"])
    have = {a: {person_key(n) for n in g["name"]} for a, g in contacts.groupby("account_id")}
    # named owners with no Apollo contact; each says whether they are also an officer
    to_find = []
    for a in leads["account_id"]:
        miss = [{**v, **({"officer": officers[a][k]["role"]} if k in officers.get(a, {}) else {})}
                for k, v in owners.get(a, {}).items() if k not in have.get(a, set())]
        to_find.append(json.dumps(miss, ensure_ascii=False) if miss else None)
    leads["owners_to_find"] = to_find
    # current officers who own nothing and are not Apollo contacts (hired directors, family members)
    leads["officers_to_find"] = [json.dumps(m, ensure_ascii=False) if (m := [v for k, v in officers.get(a, {}).items()
                                 if k not in have.get(a, set()) and k not in owners.get(a, {})]) else None for a in leads["account_id"]]
    leads["officers_named"] = [len(officers.get(a, {})) or None for a in leads["account_id"]]
    return leads, contacts.reset_index(drop=True)


def load_officers():
    """{account_id: {person_key: {name, role, appointed}}}: current officers who are people, from officers.py
    (Companies House API). Only name, role and appointment date are kept there. A person on several of the lead's
    companies keeps their strongest role (OFFICER_ORDER) and earliest appointment."""
    if not L.officers.exists():
        return {}
    o = pd.read_csv(L.officers, dtype=str, keep_default_na=False)
    o["account_id"] = "AP-" + o["company_id"].str.replace("^apollo-", "", regex=True)
    rank = lambda r: OFFICER_ORDER.index(r) if r in OFFICER_ORDER else len(OFFICER_ORDER)
    out = {}
    for r in o.itertuples():
        k = person_key(r.name)
        if not k:
            continue
        d = out.setdefault(r.account_id, {})
        x = {"name": r.name, "role": r.role, "appointed": r.appointed_on}
        if k not in d or rank(r.role) < rank(d[k]["role"]):
            d[k] = x if k not in d else {**x, "appointed": min(filter(None, [x["appointed"], d[k]["appointed"]]), default="")}
        elif r.appointed_on and (not d[k]["appointed"] or r.appointed_on < d[k]["appointed"]):
            d[k]["appointed"] = r.appointed_on
    return out


def owners_export(leads, as_of):
    """owners_to_find_<date>.csv in the Data folder: named owners of owner-managed leads and owner-managed groups with no Apollo contact, one row
    per person, for an Apollo people search (name + company + website). Best leads first."""
    rows = []
    live = ~leads["grade"].astype(str).str.startswith("Excluded") & leads["grade"].ne(DUPLICATE)   # not distressed / duplicate
    for r in leads[leads["ownership"].isin(OWNERSHIP_PRIVATE) & leads["owners_to_find"].notna() & live].itertuples():
        for o in json.loads(r.owners_to_find):
            w = re.sub(PERSON_TITLE, "", o["name"].strip(), flags=re.I).split()
            rows.append({"first_name": w[0] if w else "", "last_name": w[-1] if len(w) > 1 else "",
                         "full_name": " ".join(w), "owner_role": o["role"], "stake": o.get("band", ""), "officer_role": o.get("officer", ""),
                         "held": "directly" if o.get("via") == "direct" else f"through {o.get('via')}",
                         "company_name": r.company_name, "website": r.website_domain,
                         "lead_list": r.lead_list, "grade": r.grade, "priority_score": r.priority_score,
                         "ownership": r.ownership, "ownership_route": r.ownership_route,
                         "registered_company": r.ownership_number_name, "company_number": r.ownership_number,
                         "companies_house": f"https://find-and-update.company-information.service.gov.uk/company/{r.ownership_number}"
                                            "/persons-with-significant-control" if isinstance(r.ownership_number, str) else ""})
    order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2}
    out = pd.DataFrame(rows)
    if len(out):
        # best leads first; within a lead, the person who controls it before co-owners and minority owners
        out = out.assign(_o=out["grade"].map(order).fillna(9), _r=out["owner_role"].map(ROLE_ORDER.index)).sort_values(
            ["_o", "priority_score", "company_name", "_r"], ascending=[True, False, True, True]).drop(columns=["_o", "_r"])
    path = L.owners_csv(as_of)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return path, len(out)
