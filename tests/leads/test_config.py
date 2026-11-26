"""A lead list is a folder (Marketing Intelligence/lead_lists/<name>/list.toml): it must load into the shapes grading uses."""
import unittest

from cloudstaff_dev.leads import config


class TestLeadList(unittest.TestCase):
    def setUp(self):
        self.lst = config.LeadList("apollo_emea")

    def test_listed(self):
        self.assertIn("apollo_emea", config.available())

    def test_markets(self):
        lst = self.lst
        self.assertEqual(list(lst.list_target), ["care home", "cyber"])          # file order: the first match wins
        self.assertEqual(lst.list_target["care home"], ("UK care homes", {"Healthcare & Wellness"}))
        self.assertEqual(lst.target_codes["UK care homes"]["uk"], {"87", "88"})
        self.assertIsInstance(lst.subsectors["UK care homes"]["Nursing homes"]["sic"], set)
        self.assertNotIn("cqc", lst.subsectors["UK cybersecurity"]["Training"])   # no CQC rule outside care
        self.assertNotIn("pitch", lst.subsectors["UK care homes"]["Home care"])   # pitch is kept apart
        self.assertIn("Home care", lst.subsector_pitch)
        self.assertIn("Construction & Engineering", lst.supplier_groups)

    def test_files(self):
        lst = self.lst
        self.assertTrue(lst.template.exists(), lst.template)
        self.assertEqual(lst.rules.name, "apollo_emea")
        self.assertTrue(lst.manual_events.exists())
        self.assertEqual(lst.grades_json.name, "lead_grades_apollo_emea.json")

    def test_unknown_list(self):
        with self.assertRaises(SystemExit):
            config.LeadList("no_such_list")


if __name__ == "__main__":
    unittest.main()
