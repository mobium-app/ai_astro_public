"""Testy praktyk treningowych (reguła 2026-09-27): pasek postępu, dedup/rotacja duplikatów."""

import os
import tempfile
import unittest

from astro.scripts import train_book


class TestBar(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(train_book.bar(0, 10), "░" * 10)
        self.assertEqual(train_book.bar(100, 10), "█" * 10)
        self.assertEqual(len(train_book.bar(50, 30)), 30)

    def test_report_line_has_bar_and_counts(self):
        line = train_book.report_line(50, 100, label="nauka")
        self.assertIn("50/100", line)
        self.assertIn("50%", line)
        self.assertIn("█", line)
        self.assertIn("░", line)

    def test_report_line_zero_target_safe(self):
        self.assertIn("0%", train_book.report_line(0, 0))


class TestSemanticDedup(unittest.TestCase):
    def _embedder(self):
        # proste wektory: bliskie pary mają cosine ~1, dalekie ~0
        table = {
            "a1": [1.0, 0.0, 0.0],
            "a2": [0.99, 0.01, 0.0],
            "b1": [0.0, 1.0, 0.0],
            "c1": [0.0, 0.0, 1.0],
        }
        return lambda t: table.get(t)

    def test_drops_near_duplicate_keeps_distinct(self):
        keys = ["a1", "a2", "b1", "c1"]
        keep, drop, dups = train_book.semantic_dedup(keys, 0.95, self._embedder(), progress=False)
        self.assertEqual(keep, [0, 2, 3])
        self.assertEqual(drop, [1])
        self.assertEqual(dups, ["a2"])

    def test_no_embedder_keeps_all(self):
        keys = ["a1", "a2"]
        keep, drop, _ = train_book.semantic_dedup(keys, 0.9, None, progress=False)
        self.assertEqual(keep, [0, 1])
        self.assertEqual(drop, [])


class TestAvoidList(unittest.TestCase):
    def test_write_and_load_roundtrip(self):
        path = os.path.join(tempfile.mkdtemp(), "dups_avoid.txt")
        n = train_book.write_avoid(path, ["pytanie 1", "pytanie 2", "pytanie 1"])
        self.assertEqual(n, 2)
        self.assertEqual(train_book.load_avoid(path), ["pytanie 1", "pytanie 2"])


class TestCycleReport(unittest.TestCase):
    def _log(self):
        p = os.path.join(tempfile.mkdtemp(), "loop.log")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("2026-09-27 19:53:35 [know-loop] ===== runda 1 start (learned=8045) =====\n")
            fh.write("[remote-know] KONIEC dodane=1200 duble=227 nieudane=0 (rate_limit=0) rund=33\n")
            fh.write("2026-09-27 21:59:15 [know-loop] ===== runda 1 koniec: learned 8045 -> 9228 "
                     "(+1183) =====\n")
        return p

    def test_parse_and_format(self):
        from astro.scripts import knowledge_cycle_report as kc
        runs = [r for r in kc.parse_runs(self._log()) if r.get("after") is not None]
        self.assertEqual(len(runs), 1)
        line = kc.format_run(runs[0])
        self.assertIn("1183/1200", line)
        self.assertIn("dodane=1200", line)
        self.assertIn("duble=227", line)
        self.assertIn("█", line)


if __name__ == "__main__":
    unittest.main()
