"""Unit cases for identity.py: the examples the rules were written for. No database or models needed.

    ../.venv/Scripts/python.exe -m unittest discover -s tests -v        (from the News Scraper folder)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_scraper import identity  # noqa: E402
from news_scraper.identity import CONFIRM, Identity, NlpSignals, auto_ambiguous, common_name_flips, judge  # noqa: E402
from news_scraper.pipeline import Company  # noqa: E402


def ident(name, domain="", card=None, **kw):
    return Identity(Company(name=name, domain=domain, **kw), card or {})


def j(i, title, summary="", text="", source="google", score=0.6, **kw):
    return judge(i, title=title, summary=summary, source=source, score=score, text=text, **kw)


class FakeCombiner:
    def __init__(self, p):
        self.p = p

    def predict_proba(self, X):
        return [[1 - self.p, self.p]]


class NameType(unittest.TestCase):
    def test_auto_ambiguous(self):
        self.assertEqual(auto_ambiguous("12768640 CANADA INC.", ""), "numbered company")
        self.assertEqual(auto_ambiguous("ARG Pty Ltd", "arg.com.au"), "short name")
        self.assertEqual(auto_ambiguous("Clancy", "clancycorp.com.au"), "one-word name that is not the website's name")
        self.assertEqual(auto_ambiguous("Accora", "accora.care"), "")
        self.assertEqual(auto_ambiguous("Orchard Medical Pty Ltd", "orchardmedical.com.au"), "")

    def test_context_words_make_a_name_ambiguous(self):
        self.assertTrue(ident("Deputy", "deputy.com", context=["scheduling"]).ambiguous)

    def test_with_name_type_returns_a_copy(self):
        a = ident("Clutch", "clutch.co", employees=50)
        b = a.with_name_type(True, "20 matches, few confirm the company")
        self.assertFalse(a.ambiguous)
        self.assertTrue(b.ambiguous)
        self.assertEqual(b.name_type, "ambiguous (20 matches, few confirm the company)")

    def test_one_word_rule_is_small_companies_only(self):
        self.assertTrue(ident("Atkar", "atkar.com.au", employees=40).one_word)
        self.assertFalse(ident("Atkar", "atkar.com.au").one_word)                 # size unknown
        self.assertFalse(ident("Atkar", "atkar.com.au", employees=40, ticker="ATK").one_word)


class Evidence(unittest.TestCase):
    def test_points(self):
        i = ident("Zip Co", "zip.co", card={"city": "Sydney", "keywords": ["buy now pay later"]}, location="Sydney")
        self.assertEqual(i.evidence("Zip Co (ASX:ZIP) posts record revenue")[0], 2)
        self.assertEqual(i.evidence("Read more at zip.co")[0], 2)
        pts, found = i.evidence("The Sydney buy now pay later firm")
        self.assertEqual(pts, 2)
        self.assertEqual(found, ["keyword buy now pay later", "location"])

    def test_ticker_is_case_sensitive(self):
        i = ident("Atlassian", "atlassian.com", ticker="NASDAQ:TEAM")
        self.assertEqual(i.evidence("Atlassian (TEAM) shares rise")[0], 2)
        self.assertEqual(i.evidence("the Atlassian team ships")[0], 0)


class NameRules(unittest.TestCase):
    def test_newsroom_always_counts(self):
        r = j(ident("Deputy", "deputy.com", context=["scheduling"]), "Our winter update", source="newsroom", score=1.0)
        self.assertTrue(r.counts)
        self.assertEqual(r.rule, "company website")

    def test_common_name_used_as_a_job_title(self):
        r = j(ident("Deputy", "deputy.com", context=["scheduling"]), "Deputy Mayor opens new library")
        self.assertFalse(r.counts)
        self.assertEqual(r.rule, "name used as word")
        self.assertTrue(r.reason.startswith("text not read:"))

    def test_common_name_needs_confirmation(self):
        i = ident("Deputy", "deputy.com", context=["scheduling"])
        self.assertEqual(j(i, "Deputy launches new app").rule, "common name unconfirmed")
        r = j(i, "Deputy launches AI scheduling for shift workers")
        self.assertTrue(r.counts)
        self.assertEqual(r.rule, "evidence")

    def test_wrong_case(self):
        r = j(ident("Rokt", "rokt.com"), "ROKT ETF falls as space stocks slide in a volatile week")
        self.assertEqual(r.rule, "wrong case")

    def test_all_caps_headline_is_not_wrong_case(self):
        self.assertTrue(j(ident("Rokt", "rokt.com"), "ROKT RAISES $100M IN NEW FUNDING").counts)

    def test_passing_mention_in_a_comparison(self):
        self.assertEqual(j(ident("Canva", "canva.com"), "Adobe Express vs Canva: which is better?").rule, "passing mention")
        self.assertEqual(j(ident("Canva", "canva.com"), "Adobe, Figma, Canva and CapCut add AI").rule, "passing mention")

    def test_passing_mention_counts_when_the_text_keeps_naming_it(self):
        text = "Canva said on Monday it would expand. " * 3 + "the company " * 40
        self.assertTrue(j(ident("Canva", "canva.com"), "Adobe Express vs Canva", text=text).counts)

    def test_passing_phrase(self):
        r = j(ident("Canva", "canva.com"), "Canva-backed start-up raises $5m")
        self.assertEqual(r.rule, "passing phrase")
        self.assertEqual(r.reason, "passing mention: 'Canva-backed'")

    def test_one_word_small_company_needs_solid_evidence(self):
        i = ident("Accora", "accora.care", card={"keywords": ["designed"]}, employees=200)
        self.assertEqual(j(i, "Accora designed a new lounge").rule, "one word unconfirmed")     # a lone generic keyword is not enough
        self.assertTrue(j(i, "Accora opens in Leeds, see accora.care").counts)

    def test_text_read_rules(self):
        i = ident("Xero", "xero.com")
        # found through the summary, but neither the headline nor the text names it
        self.assertEqual(j(i, "Accounting results", summary="Xero", text="Accounting news. " + "the market moved " * 30).rule, "not named")
        self.assertEqual(j(i, "Xero", text="Xero " + "lorem ipsum dolor sit amet " * 20).rule, "not english")

    def test_low_match_score(self):
        r = j(ident("Xero", "xero.com"), "Xero launches new payroll", score=0.4)
        self.assertEqual((r.counts, r.rule, r.reason), (False, "match score", "low match score (0.4)"))

    def test_counted_rule_says_evidence_or_name_only(self):
        i = ident("Xero", "xero.com")
        self.assertEqual(j(i, "Xero launches new payroll").rule, "name only")
        self.assertEqual(j(i, "Xero launches new payroll", summary="xero.com/payroll").rule, "evidence")


class NlpRules(unittest.TestCase):
    def ents(self, title, label, start, end):
        return NlpSignals([{"in": "title", "start": start, "end": end, "text": title[start:end], "label": label}])

    def test_hyphenated_compound_for_small_company(self):
        i = ident("Big Post", "bigpost.com.au", employees=30)
        r = j(i, "Big Post-Launch sales soar", nlp=NlpSignals([]))
        self.assertEqual(r.rule, "nlp compound")

    # small one-word companies need 1 solid point to get past the name rules (step 1), so these headlines carry the city
    def test_longer_name_with_another_company_suffix(self):
        t = "Array Technologies wins solar deal in Perth"
        i = ident("Array", "array.com", employees=30, location="Perth")
        self.assertEqual(j(i, t, nlp=self.ents(t, "ORG", 0, 18)).rule, "nlp longer name")

    def test_alias_is_a_known_name_not_a_longer_name(self):
        t = "Array Technologies wins solar deal in Perth"
        i = ident("Array", "array.com", employees=30, location="Perth", aliases=["Array Technologies"])
        self.assertTrue(j(i, t, nlp=self.ents(t, "ORG", 0, 18)).counts)

    def test_wrong_type_only_without_strong_evidence(self):
        t = "Barga wins award in Leeds"
        i = ident("Barga", "barga.com.au", employees=30, location="Leeds")
        self.assertEqual(j(i, t, nlp=self.ents(t, "GPE", 0, 5)).rule, "nlp wrong type")                       # 1 point < CONFIRM
        self.assertTrue(j(i, t, summary="barga.com.au", nlp=self.ents(t, "GPE", 0, 5)).counts)                # domain: 3 points

    def test_well_known_companies_skip_the_nlp_rules(self):
        self.assertTrue(j(ident("Canva", "canva.com"), "Ex-Canva staff launch studio", nlp=NlpSignals([])).counts)

    def test_features_only_with_nlp(self):
        i = ident("Xero", "xero.com")
        self.assertIsNone(j(i, "Xero launches payroll").features)
        f = j(i, "Xero launches payroll", nlp=NlpSignals([], fit=0.4)).features
        self.assertEqual(len(f), len(identity.FEATURE_NAMES))


class Combiner(unittest.TestCase):
    def test_rejects_when_confident(self):
        r = j(ident("Xero", "xero.com"), "Xero launches payroll", nlp=NlpSignals([]), combiner={"model": FakeCombiner(0.1)})
        self.assertEqual((r.counts, r.rule), (False, "combiner"))

    def test_accepts_when_confident(self):
        r = j(ident("Canva", "canva.com"), "Adobe Express vs Canva", nlp=NlpSignals([]), combiner={"model": FakeCombiner(0.9)})
        self.assertEqual((r.counts, r.rule), (True, "combiner"))
        self.assertIn("combiner p=0.9", r.evidence)

    def test_never_accepts_below_min_match(self):
        r = j(ident("Canva", "canva.com"), "Adobe Express vs Canva", score=0.4, nlp=NlpSignals([]), combiner={"model": FakeCombiner(0.9)})
        self.assertFalse(r.counts)
        self.assertEqual(r.rule, "passing mention")


class CommonNameFlips(unittest.TestCase):
    def rows(self, n, confirmed):
        return [{"text_status": "ok", "evidence": "location" if k < confirmed else ""} for k in range(n)]

    def test_many_unconfirmed_matches_flip_a_small_company(self):
        ids = {"clutch": ident("Clutch", "clutch.co", employees=80)}
        self.assertEqual(common_name_flips(ids, {"clutch": self.rows(20, 1)}), {"clutch": "20 matches, few confirm the company"})

    def test_no_flip(self):
        ids = {"clutch": ident("Clutch", "clutch.co", employees=80), "big": ident("Clutch", "clutch.co"),
               "long": ident("Bank of Sydney Pty Ltd", "banksyd.com.au", employees=80)}
        self.assertEqual(common_name_flips(ids, {"clutch": self.rows(20, 10)}), {})        # confirmed often enough
        self.assertEqual(common_name_flips(ids, {"clutch": self.rows(10, 0)}), {})         # too few matches
        self.assertEqual(common_name_flips(ids, {"big": self.rows(20, 0)}), {})            # not a small company
        self.assertEqual(common_name_flips(ids, {"long": self.rows(20, 0)}), {})           # specific multi-word name
        unread = [{"text_status": "not read", "evidence": ""}] * 20
        self.assertEqual(common_name_flips(ids, {"clutch": unread}), {})                   # unread articles say nothing


if __name__ == "__main__":
    unittest.main()

assert CONFIRM == 2   # the cases above assume the documented threshold
