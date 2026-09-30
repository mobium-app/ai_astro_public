"""Testy raportu polszczyzny (skrobie logi i zwraca usterki)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astro.scripts import polish_report


class TestReport(unittest.TestCase):
    def test_reports_voice_reply(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "astro.log"
            log.write_text("[voice] odpowiedź: 'To jest the test bez kropki'\n", encoding="utf-8")
            with mock.patch.object(polish_report.config, "LOGS_DIR", Path(d)):
                texts = polish_report.collect()
        self.assertEqual(len(texts), 1)
        issues = polish_report.polish.quality_issues(texts[0])
        self.assertTrue(any("angielskie" in i for i in issues))

    def test_reports_topics(self):
        with tempfile.TemporaryDirectory() as d:
            usage = Path(d) / "usage.jsonl"
            usage.write_text(json.dumps({"topic": "sprawdz temperature"}) + "\n", encoding="utf-8")
            with mock.patch.object(polish_report.config, "LOGS_DIR", Path(d)):
                texts = polish_report.collect(topics=True)
        self.assertEqual(texts, ["sprawdz temperature"])


if __name__ == "__main__":
    unittest.main()
