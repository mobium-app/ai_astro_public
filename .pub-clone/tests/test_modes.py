"""Testy trybów pracy: trwały stan, kolejność backendów per tryb, komendy głosowe."""

import os
import tempfile
import unittest
from unittest import mock

from astro import backends as B
from astro import config
from astro.backends import modes
from astro.core import must_have


class Dummy(B.Backend):
    def __init__(self, name, caps=("chat", "tools", "json", "plan")):
        self.name = name
        self.capabilities = set(caps)

    def ready(self):
        return True

    def run(self, messages, **kw):
        return B.BackendResult(text=self.name)


class ModeStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.path = os.path.join(self.tmp, "mode.json")
        self._patch = mock.patch.object(config, "MODE_FILE", self.path)
        self._patch.start()
        modes._cache.update(key=None, mtime=None, mode="")
        self.addCleanup(self._patch.stop)
        self.addCleanup(lambda: modes._cache.update(key=None, mtime=None, mode=""))

    def test_default_is_offline(self):
        self.assertEqual(modes.get_mode(), modes.OFFLINE)

    def test_set_and_persist(self):
        self.assertEqual(modes.set_mode(modes.KOMPUTER), modes.KOMPUTER)
        # świeży odczyt bez cache (symulacja restartu)
        modes._cache.update(key=None, mtime=None, mode="")
        self.assertEqual(modes.get_mode(), modes.KOMPUTER)

    def test_unknown_mode_rejected(self):
        self.assertEqual(modes.set_mode("bzdury"), "")
        self.assertEqual(modes.get_mode(), modes.OFFLINE)

    def test_announce(self):
        self.assertIn("tryb offline", modes.announce(modes.OFFLINE).lower())
        self.assertIn("tryb komputer", modes.announce(modes.KOMPUTER).lower())
        self.assertIn("tryb premium", modes.announce(modes.PREMIUM).lower())


class OrderTest(unittest.TestCase):
    def test_orders_per_mode(self):
        self.assertEqual(modes.order_for("chat", modes.KOMPUTER)[0], "pc")
        self.assertEqual(modes.order_for("tools", modes.KOMPUTER)[0], "pc")
        self.assertEqual(modes.order_for("chat", modes.PREMIUM)[0], "premium")
        self.assertEqual(modes.order_for("tools", modes.PREMIUM)[0], "premium")
        self.assertEqual(modes.order_for("chat", modes.OFFLINE)[0], "cpu")

    def test_registry_honors_mode(self):
        reg = B.BackendRegistry()
        for name in ("cpu", "cpu_fast", "npu", "pc", "remote", "premium"):
            reg.register(Dummy(name))
        with mock.patch.object(modes, "get_mode", return_value=modes.KOMPUTER):
            self.assertEqual(reg.choose("chat").name, "pc")
            self.assertEqual(reg.choose("tools").name, "pc")
        with mock.patch.object(modes, "get_mode", return_value=modes.PREMIUM):
            self.assertEqual(reg.choose("chat").name, "premium")
        with mock.patch.object(modes, "get_mode", return_value=modes.OFFLINE):
            self.assertEqual(reg.choose("chat").name, "cpu")

    def test_local_only_ignores_mode(self):
        # Komenda wykonawcza nigdy nie trafi do pc/premium, nawet w trybie komputer/premium.
        reg = B.BackendRegistry()
        for name in ("cpu", "cpu_fast", "pc", "premium", "remote"):
            reg.register(Dummy(name))
        with mock.patch.object(modes, "get_mode", return_value=modes.PREMIUM):
            order = [b.name for b in reg.order("tools", local_only=True)]
        # `local_only` dopuszcza wyłącznie npu/cpu (istniejąca, twarda allowlista) — tryb nie
        # może wpuścić pc/premium do zlecenia wykonawczego.
        self.assertEqual(order, ["cpu"])


class ModeCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "mode.json")
        self._patch = mock.patch.object(config, "MODE_FILE", self.path)
        self._patch.start()
        modes._cache.update(key=None, mtime=None, mode="")
        self.addCleanup(self._patch.stop)
        self.addCleanup(lambda: modes._cache.update(key=None, mtime=None, mode=""))

    def test_intent_variants(self):
        self.assertEqual(must_have.intent("tryb offline"), "mode-offline")
        self.assertEqual(must_have.intent("tryb oflajn"), "mode-offline")
        self.assertEqual(must_have.intent("przełącz na tryb komputer"), "mode-komputer")
        self.assertEqual(must_have.intent("tryb premium"), "mode-premium")
        self.assertEqual(must_have.intent("tryb premiem"), "mode-premium")

    def test_intent_stt_variants(self):
        # Realne wyniki STT (pomiar 2026-09-28): Vosk bez gramatyki myli te frazy.
        self.assertEqual(must_have.intent("off-line"), "mode-offline")
        self.assertEqual(must_have.intent("tryb off line"), "mode-offline")
        self.assertEqual(must_have.intent("włącz tryb komputer"), "mode-komputer")
        self.assertEqual(must_have.intent("przełącz na komputer"), "mode-komputer")
        self.assertEqual(must_have.intent("premiem"), "mode-premium")

    def test_no_false_positive_on_generic_word(self):
        # „komputer"/„offline" w zwykłym zdaniu nie może przełączać trybu.
        self.assertEqual(must_have.intent("wyłącz komputer"), "")
        self.assertEqual(must_have.intent("restartuj komputer"), "")
        self.assertEqual(must_have.intent("komputer"), "")
        self.assertEqual(must_have.intent("jesteś offline"), "")

    def test_status_intent_and_handle(self):
        self.assertEqual(must_have.intent("tryb status"), "mode-status")
        self.assertEqual(must_have.intent("jaki tryb"), "mode-status")
        self.assertEqual(must_have.intent("status łączności"), "mode-status")
        self.assertEqual(must_have.intent("melduj status"), "mode-status")
        with mock.patch("astro.core.conn_status.snapshot_text", return_value="sieć=OK"), \
             mock.patch.object(modes, "status_line", return_value="Tryb Offline (offline)"):
            reply, route = must_have.handle("tryb status")
        self.assertEqual(route, "mode-status")
        self.assertIn("Tryb Offline", reply)
        self.assertIn("sieć=OK", reply)

    def test_handle_sets_mode_and_announces(self):
        # Realny status łączności jest testowany osobno (`test_conn_status`); tu nie chcemy
        # sieciowych probe'ów (opencode = realne wywołanie), więc mockujemy komunikat.
        msg = "Uruchamiam tryb premium. Status premium - gotowe."
        with mock.patch.object(modes, "set_mode", wraps=modes.set_mode) as sp, \
             mock.patch("astro.core.conn_status.mode_reply", return_value=msg):
            reply, route = must_have.handle("tryb premium")
        self.assertEqual(route, "mode-premium")
        self.assertIn("tryb premium", reply.lower())
        self.assertTrue(sp.called)
        self.assertEqual(modes.get_mode(), modes.PREMIUM)

    def test_handle_offline(self):
        msg = "Uruchamiam tryb offline. Status support - gotowe."
        with mock.patch("astro.core.conn_status.mode_reply", return_value=msg):
            reply, route = must_have.handle("tryb offline")
        self.assertEqual(route, "mode-offline")
        self.assertIn("tryb offline", reply.lower())
        self.assertEqual(modes.get_mode(), modes.OFFLINE)


class PremiumBudgetTest(unittest.TestCase):
    def test_unlimited_by_default(self):
        with mock.patch.object(config, "PREMIUM_DAILY_TOKENS", 0), \
             mock.patch.object(config, "PREMIUM_DAILY_REQUESTS", 0):
            self.assertTrue(modes.premium_budget_ok())

    def test_token_cap(self):
        with mock.patch.object(config, "PREMIUM_DAILY_TOKENS", 100), \
             mock.patch.object(config, "PREMIUM_DAILY_REQUESTS", 0), \
             mock.patch.object(modes, "premium_spend_today", return_value=(150, 3)):
            self.assertFalse(modes.premium_budget_ok())
        with mock.patch.object(config, "PREMIUM_DAILY_TOKENS", 100), \
             mock.patch.object(config, "PREMIUM_DAILY_REQUESTS", 0), \
             mock.patch.object(modes, "premium_spend_today", return_value=(50, 3)):
            self.assertTrue(modes.premium_budget_ok())

    def test_request_cap(self):
        with mock.patch.object(config, "PREMIUM_DAILY_TOKENS", 0), \
             mock.patch.object(config, "PREMIUM_DAILY_REQUESTS", 5), \
             mock.patch.object(modes, "premium_spend_today", return_value=(10, 5)):
            self.assertFalse(modes.premium_budget_ok())

    def test_registry_drops_premium_over_budget(self):
        reg = B.BackendRegistry()
        for name in ("cpu", "cpu_fast", "pc", "premium"):
            reg.register(Dummy(name))
        with mock.patch.object(modes, "get_mode", return_value=modes.PREMIUM), \
             mock.patch.object(modes, "premium_budget_ok", return_value=False):
            self.assertEqual(reg.choose("chat").name, "pc")
        with mock.patch.object(modes, "get_mode", return_value=modes.PREMIUM), \
             mock.patch.object(modes, "premium_budget_ok", return_value=True):
            self.assertEqual(reg.choose("chat").name, "premium")

    def test_status_line_mentions_mode(self):
        # Hermetyczność: bez tego test czytałby trwały `runtime/mode.json` usługi.
        with mock.patch.object(modes, "get_mode", return_value=modes.OFFLINE):
            self.assertIn("offline", modes.status_line().lower())


if __name__ == "__main__":
    unittest.main()
