"""Testy narzędzi „bez ekranu": mak_dir, gated mutacje, skan Wi-Fi (mock)."""

import os
import tempfile
import types
import unittest
from unittest import mock

from astro.safety import Confirmer
from astro.tools import ToolContext, registry


def make_ctx(auto=False, workspace=None):
    settings = types.SimpleNamespace(WORKSPACE=workspace or os.path.join(tempfile.mkdtemp(), "ws"))
    return ToolContext(settings=settings, memory=None, confirmer=Confirmer(auto=auto),
                       registry=registry)


class TestScreenless(unittest.TestCase):
    def test_make_dir_in_workspace(self):
        ws = os.path.join(tempfile.mkdtemp(), "ws")
        ctx = make_ctx(workspace=ws)
        res = registry.execute("make_dir", {"path": "projekty"}, ctx)
        self.assertTrue(res.ok)
        self.assertTrue(os.path.isdir(os.path.join(ws, "projekty")))

    def test_make_dir_outside_refused(self):
        ctx = make_ctx()
        res = registry.execute("make_dir", {"path": "/tmp/zle"}, ctx)
        self.assertFalse(res.ok)

    def test_mutating_tools_gated(self):
        ctx = make_ctx(auto=False)
        for name, args in (("system_power", {"action": "shutdown"}),
                           ("wifi_connect", {"ssid": "Dom", "password": "x"}),
                           ("network_scan", {}),
                           ("update_system", {"action": "update"})):
            res = registry.execute(name, args, ctx)
            self.assertFalse(res.ok, name)
            self.assertTrue(res.data and res.data.get("pending"), name)

    def test_update_confirm_text_per_action(self):
        # 1:1 z plikiem must-have: repozytoria vs programy (komunikat mówi, co się stanie).
        ctx = make_ctx(auto=False)
        registry.execute("update_system", {"action": "update"}, ctx)
        self.assertIn("repozytoria", ctx.confirmer.pending["announce"])
        ctx2 = make_ctx(auto=False)
        registry.execute("update_system", {"action": "full"}, ctx2)
        self.assertIn("programy", ctx2.confirmer.pending["announce"])

    def test_run_stream_mirrors_progress(self):
        from astro.tools import screenless

        class FakeStdout:
            def __iter__(self):
                return iter(["Get:1 http://deb test\n", "", "Czytanie list pakietów...\n"])

        class FakeProc:
            stdout = FakeStdout()

            def wait(self, timeout=None):
                return 0

        with mock.patch("astro.tools.screenless.subprocess.Popen", return_value=FakeProc()), \
             mock.patch("astro.tools.screenless.mirror.wall_write") as ww, \
             mock.patch("astro.tools.screenless.mirror.command") as mc:
            code, out = screenless._run_stream(["apt-get", "-y", "update"])
        self.assertEqual(code, 0)
        self.assertIn("Get:1", out)
        self.assertTrue(ww.called, "postęp apt musi lecieć na ekran (mirror)")
        self.assertTrue(mc.called, "komenda musi być widoczna na ekranie")

    def test_update_pending_executes(self):
        from astro.core.pending import execute_pending
        ctx = make_ctx(auto=False)
        res = registry.execute("update_system", {"action": "update"}, ctx)
        self.assertTrue(res.data and res.data.get("pending"))
        pending = ctx.confirmer.pending
        ctx.confirmer.clear()
        agent = types.SimpleNamespace(ctx=ctx)
        with mock.patch("astro.tools.screenless._run_stream", return_value=(0, "ok")):
            text = execute_pending(pending, agent)
        self.assertIn("Aktualizacja zakończona", text)

    def test_wifi_scan_mocked(self):
        ctx = make_ctx()
        fake = types.SimpleNamespace(returncode=0, stdout="DomWiFi:80:WPA2\n", stderr="")
        with mock.patch("astro.tools.screenless.shutil.which", return_value="/usr/bin/nmcli"), \
             mock.patch("astro.tools.screenless.subprocess.run", return_value=fake):
            res = registry.execute("wifi_scan", {}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("DomWiFi", res.text)


if __name__ == "__main__":
    unittest.main()


class TestSpelling(unittest.TestCase):
    def test_spelled_password(self):
        from astro.spelling import looks_spelled, parse_spelled_secret
        txt = ("małe a, duże B, slash, hashtag, małpa, wykrzyknik, end, gwiazdka, dolar, procent")
        self.assertTrue(looks_spelled(txt))
        self.assertEqual(parse_spelled_secret(txt), "aB/#@!&*$%")

    def test_plain_password_not_spelled(self):
        from astro.spelling import looks_spelled
        self.assertFalse(looks_spelled("DomWiFi2026"))

    def test_wifi_connect_decodes_spelled(self):
        ctx = make_ctx(auto=True)
        rows = [{"ssid": "Dom", "signal": 80, "security": "WPA2"}]
        with mock.patch("astro.wifi.scan", return_value=rows), \
             mock.patch("astro.wifi.available", return_value=True), \
             mock.patch("astro.wifi.connect", return_value=(True, "ok")) as conn:
            registry.execute("wifi_connect",
                             {"ssid": "Dom", "password": "małe a, duże B, hashtag"}, ctx)
        self.assertEqual(conn.call_args[0][0], "Dom")
        self.assertEqual(conn.call_args[0][1], "aB#")
