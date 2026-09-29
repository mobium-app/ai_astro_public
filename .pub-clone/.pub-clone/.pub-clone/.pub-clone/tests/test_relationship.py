"""Testy profilu relacji (P3) i streszczania wątku modelem (opt-in)."""

import os
import tempfile
import types
import unittest
from unittest import mock

from astro import config, memory
from astro.core import relationship
from astro.core.session import Session


def make_mem():
    return memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))


class TestRelationship(unittest.TestCase):
    def test_unknown_when_no_history(self):
        mem = make_mem()
        agent = types.SimpleNamespace(memory=mem)
        reply, route = relationship.report(agent)
        self.assertEqual(route, "relation")
        self.assertIn("pierwsza", reply.lower())
        self.assertEqual(relationship.context_line(mem), "")

    def test_stats_and_report(self):
        mem = make_mem()
        mem.add_episode("cześć", "hej")
        mem.add_episode("jak się masz", "dobrze")
        days, turns, known = relationship.stats(mem)
        self.assertTrue(known)
        self.assertGreaterEqual(turns, 4)
        self.assertIn("Relacja:", relationship.context_line(mem))
        agent = types.SimpleNamespace(memory=mem)
        reply, route = relationship.report(agent)
        self.assertEqual(route, "relation")
        self.assertIn("wypowiedzi", reply)

    def test_context_line_includes_name(self):
        mem = make_mem()
        mem.add_episode("hej", "cześć")
        line = relationship.context_line(mem, profile={"preferred_name": "Anna"})
        self.assertIn("Anna", line)


class TestModelSummary(unittest.TestCase):
    def test_summarizer_used_when_enabled(self):
        seen = {}

        def summ(prev, latest, limit):
            seen["latest"] = latest
            return "MODEL: " + latest[:12]

        s = Session(max_turns=1, gap_s=10 ** 6, max_chars=10 ** 6, summarizer=summ)
        with mock.patch.object(config, "SESSION_SUMMARY_MODEL", True):
            s.record("pierwsze pytanie", "odp", now=1)
            s.record("drugie pytanie", "odp2", now=2)
        self.assertTrue(s.summary.startswith("MODEL:"))
        self.assertEqual(seen["latest"], "pierwsze pytanie")

    def test_fallback_when_model_empty(self):
        def summ(prev, latest, limit):
            return ""

        s = Session(max_turns=1, gap_s=10 ** 6, max_chars=10 ** 6, summarizer=summ)
        with mock.patch.object(config, "SESSION_SUMMARY_MODEL", True):
            s.record("pierwsze pytanie", "odp", now=1)
            s.record("drugie pytanie", "odp2", now=2)
        self.assertIn("pierwsze pytanie", s.summary)

    def test_heuristic_when_disabled(self):
        def summ(prev, latest, limit):
            return "MODEL"

        s = Session(max_turns=1, gap_s=10 ** 6, max_chars=10 ** 6, summarizer=summ)
        with mock.patch.object(config, "SESSION_SUMMARY_MODEL", False):
            s.record("pierwsze pytanie", "odp", now=1)
            s.record("drugie pytanie", "odp2", now=2)
        self.assertNotIn("MODEL", s.summary)


if __name__ == "__main__":
    unittest.main()
