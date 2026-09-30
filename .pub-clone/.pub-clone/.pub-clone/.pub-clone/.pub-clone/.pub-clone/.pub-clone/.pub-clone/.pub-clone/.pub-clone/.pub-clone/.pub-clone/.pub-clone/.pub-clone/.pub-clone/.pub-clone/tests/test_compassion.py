"""Testy współczucia i kryzysu ASTRO (E7.7): detekcja, routing, blok wsparcia, bezpieczeństwo."""

import sys
import types
import unittest

from astro.core import compassion_flow
from astro.memory import Memory
from astro.persona import compassion


class TestDetect(unittest.TestCase):
    def test_crisis(self):
        for t in ("nie chcę żyć", "chcę się zabić", "mam dosc zycia", "chcę zniknąć"):
            self.assertEqual(compassion.detect(t), "crisis", t)

    def test_grief(self):
        self.assertEqual(compassion.detect("zmarł mi ojciec"), "grief")
        self.assertEqual(compassion.detect("tęsknię za nią"), "grief")

    def test_health(self):
        self.assertEqual(compassion.detect("mam raka i boję się"), "health")

    def test_distress(self):
        self.assertEqual(compassion.detect("jestem samotna i smutna"), "distress")

    def test_none(self):
        self.assertIsNone(compassion.detect("jaka jest pogoda"))
        self.assertIsNone(compassion.detect("przypomnij mi o lekach"))


class TestCrisisReply(unittest.TestCase):
    def test_contains_helplines_and_transparency(self):
        reply = compassion.crisis_reply()
        self.assertIn("112", reply)
        self.assertIn("116 123", reply)
        self.assertIn("programem", reply)
        self.assertIn("zadzwoń", reply)

    def test_handle_only_crisis(self):
        out = compassion_flow.handle("nie chcę żyć", None)
        self.assertEqual(out[1], "crisis")
        self.assertIn("112", out[0])
        self.assertIsNone(compassion_flow.handle("zmarł mi ojciec", None))


class TestCompassionBlock(unittest.TestCase):
    def test_blocks_for_non_crisis(self):
        for t, keyword in (("zmarł mi ojciec", "żałob"),
                           ("mam raka", "chorob"),
                           ("jestem samotna", "smutek")):
            block = compassion.compassion_block(t)
            self.assertIn("WSPARCIE", block)
            self.assertIn(keyword, block.lower(), t)

    def test_no_block_for_crisis_or_neutral(self):
        self.assertEqual(compassion.compassion_block("nie chcę żyć"), "")
        self.assertEqual(compassion.compassion_block("jaka pogoda"), "")


class TestIntegration(unittest.TestCase):
    def test_dispatch_crisis(self):
        import astro.core.dispatch  # noqa: F401
        d = sys.modules["astro.core.dispatch"]
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace())
        res = d.dispatch("nie chcę żyć", agent)
        self.assertEqual(res.route, "crisis")

    def test_context_has_support_block(self):
        from astro.core.context import build_context
        mem = Memory(":memory:")
        msgs = build_context("zmarł mi ojciec", mem)
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertIn("WSPARCIE", system_text)
        self.assertIn("żałob", system_text.lower())

    def test_joke_in_grief_declined(self):
        import astro.core.dispatch  # noqa: F401
        d = sys.modules["astro.core.dispatch"]
        mem = Memory(":memory:")
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace(memory=mem), memory=mem)
        res = d.dispatch("opowiedz żart, zmarł mi ojciec", agent)
        self.assertEqual(res.route, "humor")
        self.assertNotIn("wirusa", res.reply)


if __name__ == "__main__":
    unittest.main()
