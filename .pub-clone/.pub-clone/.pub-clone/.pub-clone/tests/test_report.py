"""Testy raportu HTML (report.build_report) — wcześniej bez pokrycia."""

import os
import tempfile
import unittest

from astro import report


class TestBuildReport(unittest.TestCase):
    def test_writes_html_to_out_dir(self):
        d = tempfile.mkdtemp()
        path = report.build_report(out_dir=d)
        self.assertTrue(os.path.exists(path), path)
        self.assertTrue(path.endswith(".html"))
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("<html", body.lower())

    def test_section_helpers_do_not_raise(self):
        # Pomocnicze sekcje muszą być odporne na brak DB/logów (środowisko testowe).
        self.assertIsInstance(report._db_counts(), dict)
        self.assertIsInstance(report._usage_routes(), dict)


if __name__ == "__main__":
    unittest.main()
