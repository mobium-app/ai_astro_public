"""Testy appraisal ASTRO (E7.3): reguły PAD, detekcja tonu/ryzyka, wpięcie w Agent.run."""

import sys
import types
import unittest

from astro.affect import appraisal
from astro.affect.affect import AffectState
from astro.memory import Memory


class TestRules(unittest.TestCase):
    def test_appraise_scaling(self):
        self.assertEqual(appraisal.appraise("praise"), (0.35, 0.25, 0.15))
        p = appraisal.appraise("tool_fail", 0.5)
        self.assertAlmostEqual(p[0], -0.125)
        self.assertEqual(appraisal.appraise("nieznane"), (0.0, 0.0, 0.0))

    def test_detect(self):
        self.assertIn("praise", appraisal.detect("dziękuję, świetnie działa"))
        self.assertIn("critique", appraisal.detect("jesteś beznadziejna, nie działa"))
        self.assertIn("risk", appraisal.detect("awaria, pomocy"))
        self.assertEqual(appraisal.detect("podaj godzinę"), [])

    def test_outcome_events(self):
        self.assertEqual(appraisal.outcome_events([]), [])
        self.assertEqual(appraisal.outcome_events([{"ok": True}]), [("tool_ok", 1.0)])
        self.assertEqual(appraisal.outcome_events([{"ok": True}, {"ok": True}]),
                         [("task_done", 1.0)])
        ev = appraisal.outcome_events([{"ok": False}])
        self.assertEqual(ev[0][0], "tool_fail")
        self.assertGreaterEqual(ev[0][1], 0.6)

    def test_deterministic_joy(self):
        s = AffectState()
        s.apply(*appraisal.appraise("praise"))
        label, _ = s.describe(now=s.ts)
        self.assertEqual(label, "zadowolona")
        self.assertTrue(s.effective()[0] > 0)


class TestAgentWiring(unittest.TestCase):
    def test_affect_after_updates_mood(self):
        from astro.core.agent import _affect_after
        mem = Memory(":memory:")
        _affect_after(mem, "dziękuję, super", [{"ok": True}])
        eff = mem.affect.load().effective()
        self.assertGreater(eff[0], 0.0)
        self.assertGreater(eff[2], 0.0)

    def test_affect_after_failure(self):
        from astro.core.agent import _affect_after
        mem = Memory(":memory:")
        _affect_after(mem, "zrób coś", [{"ok": False}])
        eff = mem.affect.load().effective()
        self.assertLess(eff[0], 0.0)
        self.assertGreater(eff[1], 0.0)

    def test_agent_run_touches_affect(self):
        from astro.core.agent import Agent
        mem = Memory(":memory:")

        class Result:
            text = "Zrobiłam to zadanie zgodnie z poleceniem i wszystko działa poprawnie."
            tool_calls = []

        class Backends:
            def run(self, *a, **k):
                return Result()

        agent = Agent(backends=Backends(), memory=mem)
        agent.run("dziękuję bardzo")
        self.assertGreater(mem.affect.load().effective()[0], 0.0)


if __name__ == "__main__":
    unittest.main()
