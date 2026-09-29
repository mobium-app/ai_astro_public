"""Testy polszczyzny modelu (E9): checker, wzorce, integracja z kontekstem."""

import unittest
from unittest import mock

from astro import config
from astro.memory import Memory
from astro.persona import polish


class TestChecker(unittest.TestCase):
    def test_clean_polish(self):
        self.assertEqual(polish.quality_issues(
            "Jestem Astro, lokalnym agentem działającym na Raspberry Pi."), [])

    def test_english_words(self):
        self.assertEqual(polish.english_words("To jest the test"), ["the"])
        self.assertEqual(polish.english_words("i oraz to"), [])  # dwuznaczne pomijamy

    def test_markdown_url_emoji(self):
        self.assertTrue(polish.markdown_present("**Bold**"))
        self.assertTrue(polish.markdown_present("## Nagłówek"))
        self.assertTrue(polish.url_present("Zobacz https://example.com"))
        self.assertTrue(polish.emoji_present("Gotowe 😀"))

    def test_sign_names(self):
        self.assertEqual(polish.sign_names("kratka i małpa"), ["kratka", "małpa"])

    def test_ends_properly(self):
        self.assertTrue(polish.ends_properly("To koniec."))
        self.assertTrue(polish.ends_properly("Naprawdę?"))
        self.assertFalse(polish.ends_properly("bez kropki"))

    def test_issues_flags(self):
        issues = polish.quality_issues("I am the best **agent** 😀 bez kropki")
        self.assertTrue(any("angielskie" in i for i in issues))
        self.assertIn("markdown", issues)
        self.assertIn("emoji", issues)
        self.assertIn("brak interpunkcji końcowej", issues)

    def test_english_phrases_and_repeats(self):
        self.assertIn("open source", polish.english_phrases("To open source projekt"))
        self.assertEqual(polish.repeated_words("to jest jest test"), ["jest"])
        issues = polish.quality_issues("to jest jest test")
        self.assertTrue(any("powtórzenia" in i for i in issues))
        self.assertIn("brak wielkiej litery na początku", issues)
        self.assertTrue(polish.starts_upper("Dobrze."))
        self.assertFalse(polish.starts_upper("dobrze."))

    def test_looks_english(self):
        self.assertTrue(polish.looks_english("I am the best agent here"))
        self.assertTrue(polish.looks_english("Sorry, I don't know"))
        self.assertFalse(polish.looks_english("Jestem Astro i pomagam po polsku."))
        self.assertFalse(polish.looks_english("To jest test."))


class TestExamples(unittest.TestCase):
    def test_block_off(self):
        self.assertEqual(polish.examples_block(0), "")

    def test_block_content(self):
        block = polish.examples_block(2)
        self.assertIn("POLSZCZYZNA", block)
        self.assertIn("pytanie:", block)

    def test_context_includes_block(self):
        from astro.core.context import build_context
        mem = Memory(":memory:")
        with mock.patch("astro.config.POLISH_FEWSHOT", 2):
            msgs = build_context("cześć", mem)
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertIn("POLSZCZYZNA", system_text)

    def test_context_without_block(self):
        from astro.core.context import build_context
        mem = Memory(":memory:")
        with mock.patch("astro.config.POLISH_FEWSHOT", 0):
            msgs = build_context("cześć", mem)
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertNotIn("pisz tak", system_text)


class TestAgentLanguageGuard(unittest.TestCase):
    def _agent(self):
        from astro import backends as B
        from astro import memory as memmod
        from astro.core import Agent
        from astro.safety import Confirmer
        from astro.tools import ToolContext, registry as reg

        class Backend(B.Backend):
            name = "cpu"
            capabilities = {"chat", "tools", "json", "plan"}

            def __init__(self):
                self.calls = 0

            def ready(self):
                return True

            def run(self, messages, **kw):
                self.calls += 1
                if self.calls == 1:
                    return B.BackendResult(text="I am the best agent, sorry.")
                return B.BackendResult(text="Jestem Astro i chętnie pomogę.")

        be = Backend()
        breg = B.BackendRegistry()
        breg.register(be)
        m = memmod.Memory(":memory:")
        ctx = ToolContext(settings=config, memory=m, confirmer=Confirmer(auto=True),
                          registry=reg, backends=breg)
        agent = Agent(backends=breg, registry=reg, memory=m, ctx=ctx)
        return agent, be

    def test_english_reply_retried_in_polish(self):
        agent, be = self._agent()
        res = agent.run("kim jesteś")
        self.assertGreaterEqual(be.calls, 2)  # była regeneracja
        self.assertFalse(polish.looks_english(res.reply))
        self.assertIn("Astro", res.reply)


if __name__ == "__main__":
    unittest.main()
