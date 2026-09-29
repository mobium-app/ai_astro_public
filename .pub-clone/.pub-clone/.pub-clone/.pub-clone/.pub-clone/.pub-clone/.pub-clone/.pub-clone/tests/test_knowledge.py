"""Testy offline bazy wiedzy ASTRO (search_knowledge)."""

import os
import tempfile
import unittest
from unittest import mock

from astro import config
from astro import memory
from astro.tools import knowledge


class TestKnowledge(unittest.TestCase):
    def test_search_all_learned(self):
        db = os.path.join(tempfile.mkdtemp(), "m.db")
        mem = memory.Memory(db)
        mem.add_learned("legacy:factory", "Praca w zespole",
                        "Praca w zespole to współpraca grupy osób o różnych umiejętnościach.",
                        source="legacy", verified=False, confidence=0.6)
        with mock.patch.object(config, "KNOWLEDGE_DB", "/nie/ma.db"):
            parts = knowledge.search_all(mem, "praca w zespole", k=3)
        self.assertTrue(any("zespole" in text for _s, text in parts))

    def test_fts_missing_db(self):
        with mock.patch.object(config, "KNOWLEDGE_DB", "/nie/ma/takiej.db"):
            self.assertEqual(knowledge.search_fts("grep", k=2), [])

    def test_curated_fact(self):
        mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        with mock.patch.object(config, "KNOWLEDGE_DB", "/nie/ma.db"):
            parts = knowledge.search_all(mem, "co to jest inflacja", k=1)
        self.assertTrue(any("inflac" in text.lower() for _s, text in parts))


if __name__ == "__main__":
    unittest.main()
