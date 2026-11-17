import os
import tempfile
import unittest

from openpyxl import load_workbook

from news_scraper import check_sheet
from news_scraper.classify import split_layoffs


def _ev(cid, title, url, cat="Restructuring"):
    return {"company_id": cid, "title": title, "url": url, "category": cat, "category_basis": "rules", "published_at": "2026-11-01",
            "source": "google", "evidence": "domain x.com", "event_confidence": "high"}


class LayoffsTest(unittest.TestCase):
    def test_job_cuts_become_layoffs(self):
        for t in ["Acme to cut 300 jobs as growth slows", "Acme lays off 12% of staff", "Redundancies at Acme",
                  "Acme slashes headcount by 20%", "Hundreds of jobs to go at Acme"]:
            self.assertEqual(split_layoffs("Restructuring", t), "Layoffs", t)

    def test_other_restructuring_stays(self):
        for t in ["Acme enters voluntary administration", "Acme closes Sydney office", "Acme announces restructure of divisions",
                  "Acme cuts prices for customers", "Downsizers flock to Noosa", "Network redundancy at Acme data centre"]:
            self.assertNotEqual(split_layoffs("Restructuring", t), "Layoffs", t)

    def test_only_restructuring_is_split(self):
        self.assertEqual(split_layoffs("M&A", "Acme buys rival, cuts 50 jobs"), "M&A")


class LabelsKeptTest(unittest.TestCase):
    def test_marks_survive_reexport(self):
        who = {"C1": {"company_name": "Acme", "website": "acme.com", "company_profile": ""}}
        with tempfile.TemporaryDirectory() as d:
            ev = [_ev("C1", "Acme cuts 300 jobs", "https://a.com/1"), _ev("C1", "Acme closes office", "https://a.com/2")]
            path = check_sheet.write(d, ev, [], who, {"C1": "distinctive"})
            wb = load_workbook(path)
            ws = wb["Article check"]
            head = {c.value: c.column for c in ws[2]}
            for r in range(3, ws.max_row + 1):
                if ws.cell(row=r, column=head["Headline"]).value == "Acme closes office":
                    ws.cell(row=r, column=head["Right company? (Yes/No/Unsure)"], value="Yes")
                    ws.cell(row=r, column=head["Right category? (Yes/No/Unsure)"], value="Yes")
                    ws.cell(row=r, column=head["Notes"], value="checked")
            wb.save(path)
            # re-export: same article, new category; plus an article that is gone
            ev2 = [_ev("C1", "Acme cuts 300 jobs", "https://a.com/1", "Layoffs"), _ev("C1", "Acme closes office", "https://a.com/2", "M&A")]
            path = check_sheet.write(d, ev2, [], who, {"C1": "distinctive"})
            ws = load_workbook(path)["Article check"]
            row = next(r for r in range(3, ws.max_row + 1) if ws.cell(row=r, column=head["Headline"]).value == "Acme closes office")
            self.assertEqual(ws.cell(row=row, column=head["Right company? (Yes/No/Unsure)"]).value, "Yes")
            self.assertIn("category was 'Restructuring'", ws.cell(row=row, column=head["Notes"]).value)
            self.assertTrue(ws.cell(row=row, column=head["Notes"]).value.startswith("checked"))
            # third export without that article: the mark moves to its own tab
            path = check_sheet.write(d, ev2[:1], [], who, {"C1": "distinctive"})
            wb = load_workbook(path)
            self.assertIn("Marks without a row", wb.sheetnames)
            self.assertEqual(wb["Marks without a row"].cell(row=2, column=3).value, "Acme closes office")
            # it stays parked on the next export, and goes back on its row when the article returns
            path = check_sheet.write(d, ev2[:1], [], who, {"C1": "distinctive"})
            self.assertIn("Marks without a row", load_workbook(path).sheetnames)
            path = check_sheet.write(d, ev2, [], who, {"C1": "distinctive"})
            wb = load_workbook(path)
            self.assertNotIn("Marks without a row", wb.sheetnames)
            ws = wb["Article check"]
            row = next(r for r in range(3, ws.max_row + 1) if ws.cell(row=r, column=head["Headline"]).value == "Acme closes office")
            self.assertEqual(ws.cell(row=row, column=head["Right company? (Yes/No/Unsure)"]).value, "Yes")


if __name__ == "__main__":
    unittest.main()
