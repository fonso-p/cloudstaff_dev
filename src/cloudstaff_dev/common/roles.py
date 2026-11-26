"""Match a lead's open job titles to the roles Cloudstaff fills (Staff Central's JP Title / JP Category catalogue).

Turns "Hiring 6-10 roles" into "2 roles we fill (Accounting, Administrative)". Three outcomes per posted title:
  on-site       a role that has to be done in person (carers, nurses, cooks, cleaners...): ONSITE, checked first
  we fill       the cleaned title is close in meaning to a Cloudstaff JP title (MiniLM embeddings, cosine >= MIN_SIM): counted
  possible      a looser match (MIN_POSSIBLE to MIN_SIM): shown with the nearest JP title for a person to judge, not counted
  no match      neither: shown as such, never guessed

Only the JP Title and JP Category columns of the Staff Central export are read (no staff data). Titles are cleaned
with common/jp_titles.py (typos, seniority and level stripped) on both sides, so "Accounts Payable Officer Level 1" and
"Senior AP Officer" compare as title bases. The newest Staff Central report is found by paths.staff_report().
"""
import html
import re

import pandas as pd

from .jp_titles import strip_title

MODEL = "sentence-transformers/all-MiniLM-L6-v2"     # the News Scraper's embedding model (already cached)
# Checked by hand on the 18 Nov 2026 postings: >= 0.80 were all right (Finance Manager, Management Accountant, Sales
# Executive, Security Analyst); 0.62-0.80 were mixed ("Care Coordinator" -> Training Coordinator, "Quality and Support
# Planning Assistant" -> Financial Planning Assistant), so they are shown as "possible" and not counted
MIN_SIM = 0.80                                       # "we fill": counted
MIN_POSSIBLE = 0.62                                  # "possible": shown with the nearest JP title, not counted
ONSITE = re.compile(r"\b(care assistant|carer|care worker|support worker|healthcare assistant|hca\b|nurse|rgn\b|rmn\b|nursing|"
                    r"clinical|cook|chef|kitchen|domestic|cleaner|housekeep|laundry|ancillary|maintenance|handyman|driver|"
                    r"activit(y|ies)|lifestyle and wellbeing|deputy manager|home manager|registered manager|team lead|"
                    r"physiotherap|occupational therap|receptionist)", re.I)


def clean_title(t):
    """'Night Health Care Assistant &amp;#8211; The New Wycliffe' -> 'Night Health Care Assistant'."""
    t = html.unescape(html.unescape(str(t)))
    t = re.split(r"\s+[–—-]\s+|\s+at\s+|\s*\(", t)[0]
    return re.sub(r"\s+", " ", t).strip(" -–")


def catalogue(staff_report):
    """Cloudstaff's role catalogue: JP title base -> JP category and how many staff have held it."""
    df = pd.read_excel(staff_report, usecols=["JP Title (All)", "JP Category (All)"]).dropna()
    df["title_base"] = strip_title(df["JP Title (All)"]).astype(str)
    cat = (df.groupby("title_base").agg(jp_category=("JP Category (All)", lambda s: s.mode().iloc[0]), n_staff=("JP Title (All)", "size"))
           .reset_index())
    return cat[cat["title_base"].str.len() > 2]


class RoleMatcher:
    def __init__(self, staff_report):
        from sentence_transformers import SentenceTransformer
        self.cat = catalogue(staff_report)
        self.model = SentenceTransformer(MODEL, device="cpu")
        self.emb = self.model.encode(self.cat["title_base"].tolist(), normalize_embeddings=True, batch_size=256)

    def match(self, titles):
        """DataFrame per title: clean, verdict (on-site / we fill / no match), matched JP title base, JP category, similarity."""
        out = pd.DataFrame({"title": list(titles)})
        out["clean"] = out["title"].map(clean_title)
        out["base"] = strip_title(out["clean"]).astype(str)
        onsite = out["clean"].str.contains(ONSITE)
        out["verdict"], out["jp_title"], out["jp_category"], out["similarity"] = "on-site", None, None, None
        rest = out[~onsite]
        if len(rest):
            q = self.model.encode(rest["base"].tolist(), normalize_embeddings=True)
            sims = q @ self.emb.T
            best = sims.argmax(axis=1)
            for (i, _), b, s in zip(rest.iterrows(), best, sims.max(axis=1)):
                verdict = "we fill" if s >= MIN_SIM else "possible" if s >= MIN_POSSIBLE else "no match"
                out.loc[i, ["verdict", "jp_title", "jp_category", "similarity"]] = [
                    verdict, self.cat["title_base"].iat[b] if verdict != "no match" else None,
                    self.cat["jp_category"].iat[b] if verdict != "no match" else None, round(float(s), 3)]
        return out
