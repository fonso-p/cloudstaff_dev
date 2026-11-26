import os
import tempfile
import unittest

from cloudstaff_dev.common.company_keys import name_key
from cloudstaff_dev.signals.jobs import adzuna as az


def _lead(names, short=False):
    return {"keys": {name_key(n) for n in names}, "short": short}


class MatchTest(unittest.TestCase):
    def test_same_name_with_legal_suffix_matches(self):
        lead = _lead(["Forge Care", "Forge Care Homes Ltd"])
        self.assertEqual(az.match("Forge Care Ltd", lead, near=False), "matched")
        self.assertEqual(az.match("FORGE CARE HOMES LIMITED", lead, near=False), "matched")

    def test_longer_employer_name_is_only_possible(self):
        self.assertEqual(az.match("Forge Care Group Services", _lead(["Forge Care"]), near=False), "possible")

    def test_other_employers_do_not_match(self):
        lead = _lead(["Forge Care"])
        for emp in ["Hays", "Forge Healthcare", "Careforge", ""]:
            self.assertIsNone(az.match(emp, lead, near=False), emp)

    def test_one_word_names_count_only_near_the_city(self):
        lead = _lead(["Cerbos"], short=True)
        self.assertEqual(az.match("Cerbos Ltd", lead, near=True), "matched")
        self.assertEqual(az.match("Cerbos Ltd", lead, near=False), "possible")

    def test_ambiguous_two_word_names_need_the_city(self):
        lead = _lead(["George Thomas"], short=True)
        self.assertEqual(az.match("George Thomas", lead, near=False), "possible")
        self.assertEqual(az.match("George Thomas", lead, near=True), "matched")


class HomeTest(unittest.TestCase):
    def test_home_searches_use_base_names_and_skip_the_groups_own(self):
        homes = [{"location_name": "Portland House Nursing Home", "city": "Shrewsbury"},
                 {"location_name": "Delta Care Ltd - Preston", "city": "Preston"},       # the group's name: found already
                 {"location_name": "The Care Home", "city": "Leeds"},                   # nothing to search for
                 {"location_name": "Portland House", "city": "Shrewsbury"},             # same home twice
                 {"location_name": "Rosewood House", "city": ""}]                       # no town to search near
        s = az.home_searches({"delta care"}, homes)
        self.assertEqual([(x["q"], x["home_key"], x["near"], x["km"]) for x in s],
                         [("Portland House", "portland house", "Shrewsbury", az.HOME_KM)])

    def test_match_home(self):
        self.assertEqual(az.match_home("Ivybank House Care Home", "ivybank house"), "matched")
        self.assertEqual(az.match_home("Ivybank House", "ivybank house"), "matched")
        self.assertEqual(az.match_home("Ivybank House Healthcare Partners", "ivybank house"), "possible")
        self.assertIsNone(az.match_home("Home Group Limited", "bank house"))


class KeysTest(unittest.TestCase):
    def test_scrub_removes_keys_from_messages(self):
        msg = "HTTP 401 for https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id=abc123&app_key=SECRETKEY&what_phrase=x"
        out = az.scrub(msg, ("abc123", "SECRETKEY"))
        self.assertNotIn("abc123", out)
        self.assertNotIn("SECRETKEY", out)
        self.assertIn("HTTP 401", out)
        self.assertNotIn("zzz", az.scrub("app_key=zzz&x=1", ()))

    def test_read_env(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".env")
            with open(p, "w", encoding="utf-8") as f:
                f.write('# comment\nADZUNA_APP_ID=abc\nexport ADZUNA_APP_KEY="k=1"\n\nBROKEN LINE\n')
            self.assertEqual(az.read_env(p), {"ADZUNA_APP_ID": "abc", "ADZUNA_APP_KEY": "k=1"})
            self.assertEqual(az.read_env(os.path.join(d, "missing")), {})


if __name__ == "__main__":
    unittest.main()
