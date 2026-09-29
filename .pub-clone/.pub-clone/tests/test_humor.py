"""Testy humoru ASTRO (E7.6): reguły, cooldown, komendy, wpięcie w kontekst/dispatch."""

import sys
import types
import unittest

from astro.affect import AffectState
from astro.core import humor_flow
from astro.memory import Memory
from astro.persona import humor
from astro.persona.persona import normalize


class TestJokes(unittest.TestCase):
    def test_request_detection(self):
        for t in ("opowiedz żart", "powiedz coś śmiesznego", "rozśmiesz mnie",
                  "masz jakiś dowcip", "znasz kawał"):
            self.assertTrue(humor.is_joke_request(t), t)
        self.assertFalse(humor.is_joke_request("jaka pogoda"))

    def test_jokes_unique_ids(self):
        ids = [j["id"] for j in humor.JOKES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 10)

    def test_pick_avoids_recent(self):
        import random
        last = humor.JOKES[0]["id"]
        picked = humor.pick(avoid=[last], rng=random.Random(1))
        self.assertNotEqual(picked["id"], last)


class TestRules(unittest.TestCase):
    def test_low_humor_blocks(self):
        self.assertFalse(humor.can_joke(normalize({"humor": 0.1})))

    def test_high_humor_allows(self):
        self.assertTrue(humor.can_joke(normalize({"humor": 0.9})))

    def test_sensitive_blocks(self):
        self.assertFalse(humor.can_joke(normalize({"humor": 0.9}), text="zmarł mi ojciec"))

    def test_negative_mood_blocks(self):
        s = AffectState()
        s.apply(-1.0, 0.5, -0.5)
        self.assertFalse(humor.can_joke(normalize({"humor": 0.9}), s))

    def test_cooldown(self):
        mem = Memory(":memory:")
        store = mem.humor
        store.cooldown = 100
        self.assertTrue(store.allow(now=1000))
        store.mark("wirus", now=1000)
        self.assertFalse(store.allow(now=1050))
        self.assertTrue(store.allow(now=1100))
        store.reset()
        self.assertEqual(store.recent_ids(), [])


class TestFlow(unittest.TestCase):
    def test_handle_returns_joke_and_marks(self):
        mem = Memory(":memory:")
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace(memory=mem), memory=mem)
        reply, route = humor_flow.handle("opowiedz żart", agent)
        self.assertEqual(route, "humor")
        self.assertTrue(any(reply == j["text"] for j in humor.JOKES))
        self.assertTrue(mem.humor.recent_ids())

    def test_handle_sensitive_declines(self):
        mem = Memory(":memory:")
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace(memory=mem), memory=mem)
        reply, route = humor_flow.handle("opowiedz żart, właśnie zmarł mi ojciec", agent)
        self.assertEqual(route, "humor")
        self.assertNotIn("wirusa", reply)
        self.assertIn("żarty", reply)

    def test_none_for_other(self):
        self.assertIsNone(humor_flow.handle("jaka pogoda", None))

    def test_dispatch_routes(self):
        import astro.core.dispatch  # noqa: F401
        d = sys.modules["astro.core.dispatch"]
        mem = Memory(":memory:")
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace(memory=mem), memory=mem)
        res = d.dispatch("opowiedz żart", agent)
        self.assertEqual(res.route, "humor")


class TestContext(unittest.TestCase):
    def test_expression_humor_hint(self):
        from astro.core.context import build_context
        mem = Memory(":memory:")
        msgs = build_context("opowiedz coś", mem)
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertIn("EKSPRESJA", system_text)
        self.assertIn("humor", system_text.lower())


if __name__ == "__main__":
    unittest.main()
