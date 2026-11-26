import os
import tempfile
import unittest

import pandas as pd

from cloudstaff_dev.signals.registers import officers


class NameTest(unittest.TestCase):
    def test_register_form_is_turned_round(self):
        self.assertEqual(officers.person_name("SMITH, John Michael"), "John Michael Smith")

    def test_name_without_comma_is_kept(self):
        self.assertEqual(officers.person_name("Acme Secretaries Limited"), "Acme Secretaries Limited")


class CsvTest(unittest.TestCase):
    def test_only_current_people_are_written(self):
        cache = {"01234567": {"fetched": "2026-11-24", "status": "ok", "items": [
            {"name": "SMITH, Jane", "officer_role": "director", "appointed_on": "2010-01-01", "resigned_on": None},
            {"name": "JONES, Tom", "officer_role": "director", "appointed_on": "2005-01-01", "resigned_on": "2020-01-01"},
            {"name": "ACME SECRETARIES LIMITED", "officer_role": "corporate-secretary", "appointed_on": "2010-01-01", "resigned_on": None},
            {"name": "BROWN, Ann", "officer_role": "llp-designated-member", "appointed_on": "2015-06-01", "resigned_on": None}]}}
        with tempfile.TemporaryDirectory() as d:
            officers.OUT_CSV = os.path.join(d, "officers.csv")
            out = officers.write_csv({"01234567": ["apollo-1", "apollo-2"]}, cache)
            self.assertEqual(sorted(set(out["name"])), ["Ann Brown", "Jane Smith"])
            self.assertEqual(len(out), 4)                         # two current people x two leads sharing the number
            self.assertIn("llp designated member", set(out["role"]))
            self.assertTrue(pd.read_csv(officers.OUT_CSV).shape[0] == 4)


if __name__ == "__main__":
    unittest.main()
