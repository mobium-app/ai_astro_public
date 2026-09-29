"""Testy temperamentu ASTRO (E7.1): schemat, magazyn, komendy, wpięcie w kontekst/dispatch."""

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from astro import persona
from astro.core import persona_flow
from astro.persona import persona as P
from astro.persona.store import PersonaStore


class TestSchema(unittest.TestCase):
    def test_normalize_fills_and_clamps(self):
        p = P.normalize({"humor": 2, "warmth": -1, "nieznane": 0.5})
        self.assertEqual(p["humor"], 1.0)
        self.assertEqual(p["warmth"], 0.0)
        self.assertNotIn("nieznane", p)
        self.assertEqual(set(p), set(P.TRAITS))

    def test_adjust(self):
        p = P.adjust(P.defaults(), "humor", 0.2)
        self.assertAlmostEqual(p["humor"], 0.7)

    def test_describe_and_block(self):
        p = P.normalize({"warmth": 0.9, "formality": 0.1})
        text = "\n".join(P.describe(p))
        self.assertIn("ciepło", text)
        block = P.context_block(p)
        self.assertIn("TEMPERAMENT ASTRO", block)
        self.assertIn("serdeczne", block)


class TestStore(unittest.TestCase):
    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            s = PersonaStore(os.path.join(d, "persona.json"))
            self.assertEqual(s.load(), P.defaults())

    def test_save_load_set_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "persona.json")
            s = PersonaStore(path)
            s.save({"humor": 0.9})
            self.assertAlmostEqual(s.load()["humor"], 0.9)
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
            traits, ok = s.set_trait("formality", 0.8)
            self.assertTrue(ok)
            self.assertAlmostEqual(s.load()["formality"], 0.8)
            _, ok = s.set_trait("nieznana", 0.5)
            self.assertFalse(ok)
            s.reset()
            self.assertEqual(s.load(), P.defaults())

    def test_corrupt_file_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "persona.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{nie json")
            self.assertEqual(PersonaStore(path).load(), P.defaults())


class TestFlow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "persona.json")
        self.patcher = mock.patch("astro.config.PERSONA_FILE", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self._tmp.cleanup()

    def test_query(self):
        reply, route = persona_flow.handle("jaki masz temperament", None)
        self.assertEqual(route, "persona")
        self.assertIn("temperament", reply.lower())

    def test_change_and_reset(self):
        reply, _ = persona_flow.handle("bądź poważna", None)
        self.assertIn("formalność", reply)
        traits = PersonaStore(self.path).load()
        self.assertGreater(traits["formality"], P.defaults()["formality"])
        self.assertLess(traits["humor"], P.defaults()["humor"])
        persona_flow.handle("przywróć domyślną osobowość", None)
        self.assertEqual(PersonaStore(self.path).load(), P.defaults())

    def test_none_for_other(self):
        self.assertIsNone(persona_flow.handle("jaka pogoda", None))

    def test_dispatch_routes(self):
        import astro.core.dispatch  # noqa: F401
        d = sys.modules["astro.core.dispatch"]
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace())
        res = d.dispatch("jaki masz temperament", agent)
        self.assertEqual(res.route, "persona")


class TestContext(unittest.TestCase):
    def test_current_block_uses_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "persona.json")
            with mock.patch("astro.config.PERSONA_FILE", path):
                PersonaStore(path).save({"humor": 1.0})
                block = persona.current_block()
                self.assertIn("TEMPERAMENT ASTRO", block)
                self.assertIn("żartobliwy", block)


if __name__ == "__main__":
    unittest.main()
