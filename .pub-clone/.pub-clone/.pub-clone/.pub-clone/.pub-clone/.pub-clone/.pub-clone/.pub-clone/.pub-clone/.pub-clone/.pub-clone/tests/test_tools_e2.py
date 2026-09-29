"""Testy narzędzi E2 (dokumentacja, skrypty, sieć/POI)."""

import os
import tempfile
import types
import unittest

from astro.safety import Confirmer
from astro.tools import ToolContext, registry, system, web


def make_ctx(auto=True, workspace=None):
    settings = types.SimpleNamespace(
        WORKSPACE=workspace or os.path.join(tempfile.mkdtemp(), "sandbox"))
    return ToolContext(settings=settings, memory=None, confirmer=Confirmer(auto=auto),
                       registry=registry)


class TestDocs(unittest.TestCase):
    def test_man_page(self):
        out = system.man_page_text("grep")
        self.assertIn("GREP", out.upper())
        self.assertGreater(len(out), 100)

    def test_cmd_help(self):
        self.assertTrue(system.cmd_help_text("ls").strip())

    def test_man_secret_refused(self):
        self.assertTrue(system.man_page_text("id_rsa").startswith("odmowa"))


class TestCheckScript(unittest.TestCase):
    def test_bad_bash(self):
        p = os.path.join(tempfile.mkdtemp(), "bad.sh")
        with open(p, "w") as f:
            f.write("#!/bin/bash\nif [ 1 -eq 1 ]\nthen echo x\n")
        ok, _ = system.check_script_text(p)
        self.assertFalse(ok)

    def test_good_bash(self):
        p = os.path.join(tempfile.mkdtemp(), "ok.sh")
        with open(p, "w") as f:
            f.write("#!/bin/bash\nset -e\necho ok\n")
        ok, _ = system.check_script_text(p)
        self.assertTrue(ok)

    def test_bad_python(self):
        p = os.path.join(tempfile.mkdtemp(), "bad.py")
        with open(p, "w") as f:
            f.write("def f(:\n    pass\n")
        ok, _ = system.check_script_text(p)
        self.assertFalse(ok)


class TestRunScript(unittest.TestCase):
    def test_run_in_sandbox(self):
        ctx = make_ctx(auto=True)
        write = registry.execute("write_file",
                                 {"path": "demo.sh", "content": "#!/bin/bash\necho astro-script-ok\n"},
                                 ctx)
        self.assertTrue(write.ok)
        res = registry.execute("run_script", {"path": "demo.sh"}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("astro-script-ok", res.text)

    def test_run_outside_sandbox_refused(self):
        res = registry.execute("run_script", {"path": "/tmp/evil.sh"}, make_ctx())
        self.assertFalse(res.ok)


class TestSearchParsing(unittest.TestCase):
    SAMPLE = ("Wyniki (duckduckgo):\n"
              "1. [duckduckgo] Python docs\n   https://docs.python.org/3/\n   oficjalna dokumentacja\n"
              "2. [bing] Linux kernel\n   https://kernel.org/\n   strona jądra\n")

    def test_parse_results(self):
        entries = web.parse_search_results(self.SAMPLE)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0], "Python docs")

    def test_source_rules(self):
        self.assertTrue(web.source_trusted("https://docs.python.org/3/"))
        self.assertFalse(web.source_ok("https://pornhub.com/x"))
        self.assertTrue(web.source_ok("https://example.com/x"))


class TestPoi(unittest.TestCase):
    def test_nearby_kind(self):
        self.assertEqual(web.nearby_kind("najbliższy paczkomat"), "paczkomat")
        self.assertEqual(web.nearby_kind("gdzie jest apteka"), "apteka")
        self.assertEqual(web.nearby_kind("najbliższy sklep"), "sklep")

    def test_nearby_kind_extended(self):
        # Uwaga żywa 2026-09-28: obsługa z listy must-have + warianty STT („podkomat").
        self.assertEqual(web.nearby_kind("podkomat"), "paczkomat")
        self.assertEqual(web.nearby_kind("najbliższy bank"), "bank")
        self.assertEqual(web.nearby_kind("bankomat"), "bankomat")
        self.assertEqual(web.nearby_kind("najbliższa siłownia"), "silownia")
        self.assertEqual(web.nearby_kind("fitness"), "silownia")
        self.assertEqual(web.nearby_kind("poczta"), "poczta")
        self.assertEqual(web.nearby_kind("sklep spożywczy"), "sklep")
        self.assertEqual(web.nearby_kind("szpital"), "szpital")
        # każdy rozpoznany rodzaj ma filtr POI (inaczej „brak wyników")
        for kind in ("bank", "poczta", "silownia", "kawiarnia"):
            self.assertIn(kind, web.POI_TAGS)
            self.assertIn(kind, web.POI_LABEL)

    def test_parse_inpost(self):
        payload = {"items": [{"name": "POZ03B", "display_name": "Paczkomat POZ03B",
                              "address": {"line1": "Byka 1", "line2": "Poznań"},
                              "distance": 140.4, "opening_hours": "24/7"}]}
        items = web.parse_inpost(payload)
        self.assertEqual(items[0]["name"], "Paczkomat POZ03B")
        self.assertEqual(items[0]["distance"], 140)
        self.assertIn("Byka 1", items[0]["address"])

    def test_parse_overpass_sorted(self):
        payload = {"elements": [
            {"lat": 52.41, "lon": 16.93, "tags": {"name": "Dalszy"}},
            {"lat": 52.40, "lon": 16.92, "tags": {"name": "Bliższy"}},
        ]}
        items = web.parse_overpass(payload, 52.40, 16.92, "sklep")
        self.assertEqual(items[0]["name"], "Bliższy")
        self.assertLess(items[0]["distance"], items[1]["distance"])

    def test_haversine(self):
        d = web.haversine_m(52.40, 16.92, 52.40, 16.93)
        self.assertTrue(600 < d < 750)


if __name__ == "__main__":
    unittest.main()
