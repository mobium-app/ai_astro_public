"""Testy polityki wyrażania ASTRO (E7.4): styl, parametry LLM, wrażliwość, integracja."""

import unittest

from astro.memory import Memory
from astro.persona import expression
from astro.persona.persona import normalize


class TestSensitivity(unittest.TestCase):
    def test_detect(self):
        self.assertTrue(expression.is_sensitive("zmarł mi ojciec"))
        self.assertTrue(expression.is_sensitive("boję się, jestem samotna"))
        self.assertFalse(expression.is_sensitive("jaka jest pogoda"))


class TestStyle(unittest.TestCase):
    def test_verbosity_and_formality(self):
        block = expression.style_block(normalize({"verbosity": 0.1, "formality": 0.9}))
        self.assertIn("zwięźle", block)
        self.assertIn("formalny", block)
        block = expression.style_block(normalize({"verbosity": 0.9, "formality": 0.1}))
        self.assertIn("szerzej", block)
        self.assertIn("swobodnie", block)

    def test_humor(self):
        self.assertIn("humor", expression.style_block(normalize({"humor": 0.9})))
        self.assertIn("Unikaj żartów", expression.style_block(normalize({"humor": 0.1})))

    def test_sensitive_disables_humor(self):
        block = expression.style_block(normalize({"humor": 1.0}), text="zmarł mi ojciec")
        self.assertIn("wrażliwy", block)
        self.assertNotIn("wpleść lekki humor", block)

    def test_affect_guidance(self):
        from astro.affect import AffectState
        s = AffectState()
        s.apply(0.5, 0.2, 0.2)
        block = expression.style_block(normalize(None), s)
        self.assertIn("EKSPRESJA", block)


class TestParams(unittest.TestCase):
    def test_tokens_scale_with_verbosity(self):
        self.assertEqual(expression.llm_params(normalize({"verbosity": 0.0}))["max_tokens"], 300)
        self.assertEqual(expression.llm_params(normalize({"verbosity": 1.0}))["max_tokens"], 800)

    def test_temperature_range(self):
        for v in (0.0, 0.5, 1.0):
            t = expression.llm_params(normalize({"energy": v}))["temperature"]
            self.assertGreaterEqual(t, 0.1)
            self.assertLessEqual(t, 0.85)

    def test_sensitive_caps_temperature(self):
        p = normalize({"energy": 1.0, "humor": 1.0})
        t = expression.llm_params(p, text="jestem chory, boję się")["temperature"]
        self.assertLessEqual(t, 0.3)

    def test_for_run_with_memory(self):
        mem = Memory(":memory:")
        params = expression.for_run("cześć", mem)
        self.assertIn("max_tokens", params)
        self.assertIn("temperature", params)


class TestIntegration(unittest.TestCase):
    def test_context_has_expression(self):
        from astro.core.context import build_context
        mem = Memory(":memory:")
        msgs = build_context("cześć", mem)
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertIn("EKSPRESJA", system_text)

    def test_agent_run_uses_policy(self):
        from astro.core.agent import Agent
        mem = Memory(":memory:")

        class Result:
            text = "Rozumiem, że to trudny moment. Jestem obok i pomogę."
            tool_calls = []

        class Backends:
            def __init__(self):
                self.kw = {}

            def run(self, *a, **k):
                self.kw = k
                return Result()

        b = Backends()
        agent = Agent(backends=b, memory=mem)
        agent.run("zmarł mi ojciec")
        self.assertLessEqual(b.kw["temperature"], 0.3)
        self.assertGreaterEqual(b.kw["max_tokens"], 200)


if __name__ == "__main__":
    unittest.main()
