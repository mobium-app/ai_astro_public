"""Testy prefiksu SKAJNET (must-have): intencje + wykonanie przez mock (bez skutków na Pi4)."""

import unittest
from unittest import mock

from astro.core import prefix, skynet


class FakeConfirmer:
    def __init__(self, agree=True):
        self.agree = agree
        self.pending = None
        self.calls = []

    def require_confirm(self, text, kind, payload):
        self.calls.append((text, kind, payload))
        if not self.agree:
            self.pending = {"kind": kind, "payload": payload}
            return False
        return True


class FakeCtx:
    def __init__(self, confirmer=None):
        self.confirmer = confirmer
        self.assume_confirmed = False
        self.memory = None


class FakeAgent:
    def __init__(self, ctx):
        self.ctx = ctx


class TestPrefix(unittest.TestCase):
    def test_channel_and_body(self):
        ch, body = prefix.parse("skajnet status doker")
        self.assertEqual(ch, prefix.SKAJNET)
        self.assertEqual(body, "status doker")

    def test_phonetic_variants(self):
        for raw in ("skajnet", "skynet", "skajnetu", "skynetu", "Skajnet"):
            ch, _ = prefix.parse(raw + " wyłącz się")
            self.assertEqual(ch, prefix.SKAJNET, raw)

    def test_no_prefix(self):
        ch, _ = prefix.parse("status doker")
        self.assertEqual(ch, "")


class TestIntent(unittest.TestCase):
    def test_all_routes(self):
        cases = {
            "jaki status doker": "docker-status",
            "status doker": "docker-status",
            "wyłącz system": "power-shutdown",
            "zamknij system": "power-shutdown",
            "wyłącz się": "power-shutdown",
            "restart systemu": "power-reboot",
            "resetuj się": "power-reboot",
            "pokaż zasoby systemowe": "resources",
            "zasoby systemowe": "resources",
            "pokaż zasoby zdalne": "remote-resources",
            "zasoby remołt": "remote-resources",
            "aktualizuj repozytoria": "update-repo",
            "updejt repo": "update-repo",
            "aktualizuj aplikacje": "update-apps",
            "updejt apps": "update-apps",
            "instaluj aplikacje mc": "install",
            "instaluj program htop": "install",
            "podaj temperaturę procesora": "temp",
            "temperatura ce pe u": "temp",
        }
        for text, want in cases.items():
            self.assertEqual(skynet.intent(text), want, text)

    def test_miss(self):
        self.assertEqual(skynet.intent("zagraj mi piosenkę"), "")


class TestHandle(unittest.TestCase):
    def test_docker_status_ok(self):
        with mock.patch.object(skynet, "_pi4", return_value=(0, "nazwa (img) Up\nrunning=1; total=1")):
            reply, route = skynet.handle("status doker")
            self.assertEqual(route, "docker-status")
            self.assertIn("nazwa", reply)

    def test_docker_status_fail(self):
        with mock.patch.object(skynet, "_pi4", return_value=(1, "ssh: connect refused")):
            reply, route = skynet.handle("status doker")
            self.assertIn("Nie mogę", reply)

    def test_temp(self):
        with mock.patch.object(skynet, "_pi4", return_value=(0, "48.2'C\n")):
            reply, route = skynet.handle("temperatura procesora")
            self.assertEqual(route, "temp")
            self.assertIn("48.2", reply)

    def test_mutating_requires_confirmation(self):
        agent = FakeAgent(FakeCtx(FakeConfirmer(agree=False)))
        with mock.patch("astro.tools.tasks.execute_steps") as ex:
            reply, route = skynet.handle("wyłącz system", agent)
            self.assertEqual(route, "power-shutdown")
            self.assertIn("Wymaga potwierdzenia", reply)
            ex.assert_not_called()

    def test_mutating_executes_after_confirm(self):
        agent = FakeAgent(FakeCtx(FakeConfirmer(agree=True)))
        with mock.patch("astro.tools.tasks.execute_steps",
                        return_value=mock.Mock(text="Wynik planu:\n1. $ ... -> kod 0", ok=True)):
            reply, route = skynet.handle("wyłącz system", agent)
            self.assertEqual(route, "power-shutdown")
            self.assertIn("Wynik planu", reply)

    def test_install_extracts_package(self):
        agent = FakeAgent(FakeCtx(FakeConfirmer(agree=True)))
        with mock.patch("astro.tools.tasks.execute_steps",
                        return_value=mock.Mock(text="Wynik planu:\n1. $ ... -> kod 0", ok=True)):
            reply, route = skynet.handle("instaluj aplikacje mc", agent)
            self.assertEqual(route, "install")
            agent.ctx.confirmer.calls  # brak błędu = kroki zbudowane
            _, _, payload = agent.ctx.confirmer.calls[0]
            self.assertIn("apt-get install -y mc", payload["steps"][0]["command"])


if __name__ == "__main__":
    unittest.main()