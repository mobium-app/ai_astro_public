"""Testy rejestru i narzędzi."""

import os
import tempfile
import types
import unittest

from astro import config
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


def make_ctx(auto=True, workspace=None):
    settings = types.SimpleNamespace(
        WORKSPACE=workspace or os.path.join(tempfile.mkdtemp(), "sandbox"))
    return ToolContext(settings=settings, memory=None, confirmer=Confirmer(auto=auto),
                       registry=registry)


class TestRegistry(unittest.TestCase):
    def test_schemas(self):
        names = [s["function"]["name"] for s in registry.schemas()]
        self.assertIn("system_info", names)
        self.assertIn("run_command", names)

    def test_select_subset(self):
        picked = [s["function"]["name"] for s in registry.select("jaka jest temperatura i RAM")]
        self.assertIn("system_info", picked)
        self.assertLess(len(picked), len(registry.schemas()))

    def test_select_fallback_bounded(self):
        picked = registry.select_names("zupełnie niejasne zapytanie o niczym")
        self.assertLessEqual(len(picked), config.MAX_TOOLS)
        self.assertIn("system_info", picked)
        self.assertLess(len(picked), len(registry.schemas()))

    def test_select_exec_command_includes_run_command(self):
        # „wykonaj polecenie df -h" -> run_command MUSI być w wyborze (regresja: „cen" w „polecenie"
        # kierowało na web_search, a run_command wypadał z budżetu).
        for text in ("Wykonaj polecenie df -h", "uruchom polecenie ls -la", "wykonaj komendę uname"):
            self.assertIn("run_command", registry.select_names(text, config.MAX_TOOLS), text)

    def test_select_price_is_web_not_command(self):
        # „cena" (zakupy) nadal -> web, ale nie przez podsłowo „cen" w „polecenie".
        picked = registry.select_names("jaka jest cena bitcoina", config.MAX_TOOLS)
        self.assertIn("web_search", picked)

    def test_previously_unreachable_tools_are_selectable(self):
        # Regresja: te narzędzia były zarejestrowane, ale nieosiągalne przez model (brak hinta).
        cases = {
            "zaktualizuj system": "update_system",
            "zrestartuj Raspberry Pi": "system_power",
            "włącz światło w domu": "home_command",
            "sprawdź stan urządzeń w domu": "home_status",
            "co widzisz przez kamerę": "camera_look",
            "utwórz katalog w piaskownicy": "make_dir",
            "zeskanuj sieć lokalną nmap": "network_scan",
            "zeskanuj dostępne sieci wifi": "wifi_scan",
            "połącz z siecią wifi": "wifi_connect",
            "rozłącz z siecią wifi": "wifi_disconnect",
        }
        for text, tool in cases.items():
            self.assertIn(tool, registry.select_names(text, config.MAX_TOOLS), text)


class TestSystemInfo(unittest.TestCase):
    def test_system_info(self):
        res = registry.execute("system_info", {}, make_ctx())
        self.assertTrue(res.ok)
        self.assertIn("°C", res.text)
        self.assertIn("GB", res.text)
        self.assertTrue(res.data["disk_free_gb"] > 0)


class TestPaths(unittest.TestCase):
    def test_sensitive_read_refused(self):
        res = registry.execute("read_file", {"path": "~/.ssh/id_rsa"}, make_ctx())
        self.assertFalse(res.ok)

    def test_write_outside_sandbox_refused(self):
        res = registry.execute("write_file", {"path": "/tmp/astro-out.txt", "content": "x"},
                               make_ctx())
        self.assertFalse(res.ok)
        self.assertFalse(os.path.exists("/tmp/astro-out.txt"))

    def test_write_inside_sandbox(self):
        ws = os.path.join(tempfile.mkdtemp(), "sandbox")
        ctx = make_ctx(workspace=ws)
        res = registry.execute("write_file", {"path": "notatka.txt", "content": "hej"}, ctx)
        self.assertTrue(res.ok)
        self.assertTrue(os.path.isfile(os.path.join(ws, "notatka.txt")))


class TestRunCommand(unittest.TestCase):
    def test_readonly_runs_without_confirm(self):
        ctx = make_ctx(auto=False)
        res = registry.execute("run_command", {"command": "whoami"}, ctx)
        self.assertTrue(res.ok)
        self.assertTrue(res.text.strip())

    def test_mutating_gated(self):
        ctx = make_ctx(auto=False)
        res = registry.execute("run_command", {"command": "touch /tmp/astro-gated-marker"}, ctx)
        self.assertFalse(res.ok)
        self.assertTrue(res.data and res.data.get("pending"))
        self.assertFalse(os.path.exists("/tmp/astro-gated-marker"))

    def test_blocked(self):
        ctx = make_ctx(auto=True)
        res = registry.execute("run_command", {"command": "rm -rf /"}, ctx)
        self.assertFalse(res.ok)


class TestNetwork(unittest.TestCase):
    def test_private_url_refused(self):
        res = registry.execute("web_fetch", {"url": "http://127.0.0.1:11434"}, make_ctx())
        self.assertFalse(res.ok)

    def test_url_allowed_guards_scheme_and_private(self):
        from astro.tools import web
        self.assertFalse(web.url_allowed("file:///etc/passwd"))
        self.assertFalse(web.url_allowed("ftp://example.com/x"))
        self.assertFalse(web.url_allowed("http://127.0.0.1:8080"))
        self.assertFalse(web.url_allowed("http://169.254.169.254/latest/meta-data"))
        self.assertTrue(web.url_allowed("https://example.com/x"))

    def test_redirect_to_private_blocked(self):
        import urllib.error
        import urllib.request
        from astro.tools import web
        req = urllib.request.Request("https://example.com/start")
        with self.assertRaises(urllib.error.HTTPError):
            web._GuardRedirectHandler().redirect_request(
                req, None, 302, "Found", {}, "http://127.0.0.1:11434/api/tags")


if __name__ == "__main__":
    unittest.main()
