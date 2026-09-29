"""Testy prefiksów kanału (must-have 2026-09-27): terminal / czat / skrypt."""

import os
import tempfile
import unittest
from unittest import mock

from astro import backends as B
from astro import config, memory, wifi
from astro.core import Agent, dispatch, must_have
from astro.core import prefix
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


class CaptureBackend(B.Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def __init__(self):
        self.last = None

    def ready(self):
        return True

    def run(self, messages, **kw):
        self.last = kw
        return B.BackendResult(text="Odpowiedź modelu.")


def make_agent():
    breg = B.BackendRegistry()
    breg.register(CaptureBackend())
    mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=False),
                      registry=registry, backends=breg)
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx)


class ParseTest(unittest.TestCase):
    def test_terminal(self):
        ch, body = prefix.parse("terminal wyłącz system")
        self.assertEqual(ch, prefix.TERMINAL)
        self.assertEqual(body, "wyłącz system")

    def test_czat_variants(self):
        self.assertEqual(prefix.parse("czat jakie jest twoje ulubione zwierze")[0], prefix.CZAT)
        self.assertEqual(prefix.parse("chat opowiedz żart")[0], prefix.CZAT)

    def test_skrypt(self):
        ch, body = prefix.parse("skrypt oblicz ile to 7 * 8")
        self.assertEqual(ch, prefix.SKRYPT)
        self.assertEqual(body, "oblicz ile to 7 * 8")

    def test_prefix_variants(self):
        # Warianty zapisu/STT prefiksu (uwaga żywa 2026-09-28).
        for p in ("skryp oblicz 2 plus 2", "skrypcie oblicz 2 plus 2", "script oblicz 2 plus 2",
                  "skrypcik oblicz 2 plus 2"):
            self.assertEqual(prefix.parse(p)[0], prefix.SKRYPT, p)
        self.assertEqual(prefix.parse("czacik co to jest linux")[0], prefix.CZAT)

    def test_no_prefix(self):
        ch, body = prefix.parse("która godzina")
        self.assertEqual(ch, "")
        self.assertEqual(body, "która godzina")

    def test_boundary_not_matched(self):
        # „czatownik"/„terminalowy" nie są prefiksem (wymagana granica słowa).
        self.assertEqual(prefix.parse("czatownik")[0], "")
        self.assertEqual(prefix.parse("terminalowy reset")[0], "")


class RoutingTest(unittest.TestCase):
    def test_czat_forces_chat_without_tools(self):
        agent = make_agent()
        res = dispatch("czat wyłącz system", agent)
        # Nie wykonano komendy; poszło do agenta bez narzędzi (force_chat).
        self.assertNotIn(res.route, ("must-have:abort", "fast:zasilanie"))
        self.assertIsNotNone(agent.backends.get("cpu").last)
        self.assertFalse(agent.backends.get("cpu").last.get("tools"))

    def test_skrypt_wifi_scan(self):
        agent = make_agent()
        with mock.patch.object(wifi, "scan_text", return_value="LISTA SIECI"):
            res = dispatch("skrypt znajdź dostępne sieci", agent)
        self.assertEqual(res.reply, "LISTA SIECI")
        self.assertEqual(res.route, "wifi-scan")
        self.assertIsNone(agent.backends.get("cpu").last)  # brak modelu

    def test_skrypt_calculator(self):
        agent = make_agent()
        res = dispatch("skrypt oblicz ile to 7 razy 8", agent)
        self.assertIn("56", res.reply)
        self.assertIsNone(agent.backends.get("cpu").last)

    def test_skrypt_miss(self):
        agent = make_agent()
        res = dispatch("skrypt zrób coś czego nie ma", agent)
        self.assertEqual(res.route, "skrypt-miss")
        self.assertIsNone(agent.backends.get("cpu").last)

    def test_terminal_behaves_normally(self):
        agent = make_agent()
        res = dispatch("terminal która godzina", agent)
        self.assertIn("godzina", res.reply.lower())


class MustHaveNewTest(unittest.TestCase):
    def test_context_intent(self):
        self.assertEqual(must_have.intent("czy pamiętasz kontekst"), "context")
        self.assertEqual(must_have.intent("ostatni kontekst"), "context")

    def test_fav_animal_intent(self):
        self.assertEqual(must_have.intent("jakie jest twoje ulubione zwierze"), "fav-animal")
        self.assertEqual(must_have.intent("zwierzadko"), "fav-animal")


if __name__ == "__main__":
    unittest.main()
