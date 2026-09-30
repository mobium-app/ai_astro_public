"""Testy pamięci afektywnej ASTRO (E8): zapis, przypominanie, reminiscencja, integracja."""

import time
import unittest

from astro.core.agent import _affect_after
from astro.memory import Memory


class TestAffectMemory(unittest.TestCase):
    def test_record_and_count(self):
        mem = Memory(":memory:")
        am = mem.affect_memory
        self.assertEqual(am.count(), 0)
        am.record("lubię deszcz", (0.8, 0.2, 0.1))
        am.record("awaria serwera", (-0.8, 0.5, -0.5))
        self.assertEqual(am.count(), 2)

    def test_recall_relevance(self):
        mem = Memory(":memory:")
        am = mem.affect_memory
        am.record("lubię deszcz", (0.8, 0.2, 0.1))
        am.record("awaria serwera", (-0.8, 0.5, -0.5))
        pad, hits = am.recall("deszcz")
        self.assertIsNotNone(pad)
        self.assertGreater(pad[0], 0)
        self.assertTrue(hits)
        pad2, _ = am.recall("awaria")
        self.assertLess(pad2[0], 0)

    def test_recall_no_match(self):
        mem = Memory(":memory:")
        am = mem.affect_memory
        am.record("lubię deszcz", (0.8, 0.2, 0.1))
        pad, hits = am.recall("zupełnie inny temat o górach")
        self.assertIsNone(pad)
        self.assertEqual(hits, [])

    def test_recency_weighting(self):
        mem = Memory(":memory:")
        am = mem.affect_memory
        now = time.time()
        am.con.execute("INSERT INTO affect_events(ts, goal, p, a, d) VALUES(?,?,?,?,?)",
                       (now - 2 * 10800, "rower", 1.0, 0.0, 0.0))
        am.con.execute("INSERT INTO affect_events(ts, goal, p, a, d) VALUES(?,?,?,?,?)",
                       (now - 5, "rower", -1.0, 0.0, 0.0))
        am.con.commit()
        pad, _ = am.recall("rower", now=now)
        self.assertLess(pad[0], 0)

    def test_reset(self):
        mem = Memory(":memory:")
        am = mem.affect_memory
        am.record("coś", (0.1, 0.1, 0.1))
        am.reset()
        self.assertEqual(am.count(), 0)


class TestReminiscence(unittest.TestCase):
    def test_recall_nudges_mood(self):
        mem = Memory(":memory:")
        mem.affect_memory.record("rower górski w lesie", (0.9, 0.3, 0.2))
        _affect_after(mem, "rower górski w lesie", [])
        eff = mem.affect.load().effective()
        self.assertGreater(eff[0], 0.15)

    def test_turn_is_recorded(self):
        mem = Memory(":memory:")
        _affect_after(mem, "dzień dobry", [])
        self.assertGreaterEqual(mem.affect_memory.count(), 1)

    def test_no_memory_no_crash(self):
        _affect_after(None, "cześć", [])


if __name__ == "__main__":
    unittest.main()
