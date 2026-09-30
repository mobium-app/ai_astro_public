"""Testy fast-path aktualizacji (brak hijacku system_info) i mirroringu terminali."""

import types
import unittest
from unittest import mock

from astro import config, mirror
from astro.core import fast_tools
from astro.safety import normalize_facts
from astro.tools.registry import ToolResult


class _FakeReg:
    def __init__(self):
        self.calls = []

    def execute(self, name, args, ctx):
        self.calls.append((name, dict(args or {})))
        return ToolResult(f"PENDING:{name}", ok=True)


def _ctx(reg):
    return types.SimpleNamespace(registry=reg, memory=None)


class TestUpdateAction(unittest.TestCase):
    def test_repos_is_update(self):
        self.assertEqual(fast_tools.update_action("zaktualizuj repozytoria"), "update")

    def test_system_is_full(self):
        self.assertEqual(fast_tools.update_action("zaktualizuj aplikacje systemowe"), "full")
        self.assertEqual(fast_tools.update_action("aktualizacja systemu"), "full")

    def test_programs_is_full(self):
        # Lista must-have: „aktualizuj programy" = sudo apt-get upgrade (fast-path, nie model).
        self.assertEqual(fast_tools.update_action("aktualizuj programy"), "full")

    def test_not_update(self):
        for low in ("co to jest system", "sprawdź temperaturę procesora", "kto to systemd"):
            self.assertIsNone(fast_tools.update_action(low), low)


class TestNoHijack(unittest.TestCase):
    def test_mutating_command_not_system_info(self):
        reg = _FakeReg()
        out = fast_tools.try_fast("zaktualizuj aplikacje systemowe", _ctx(reg))
        self.assertIn("update_system", [c[0] for c in reg.calls])
        self.assertNotIn("system_info", [c[0] for c in reg.calls])
        self.assertIsNotNone(out)

    def test_readonly_still_system_info(self):
        reg = _FakeReg()
        fast_tools.try_fast("sprawdź stan dysku", _ctx(reg))
        self.assertEqual(reg.calls[0][0], "system_info")

    def test_theory_about_system_not_system_info(self):
        # „co to jest system plików" to teoria, nie zapytanie o stan — nie może trafić w system_info.
        reg = _FakeReg()
        out = fast_tools.try_fast("co to jest system plików", _ctx(reg))
        self.assertNotIn("system_info", [c[0] for c in reg.calls])
        self.assertIsNone(out)

    def test_temperature_only(self):
        # Plik must-have: „podaj temperaturę procesora" = TYLKO temperatura (bez dysku/RAM/daty).
        with mock.patch("astro.core.resources.resource_data",
                        return_value={"cpu": {"temp_c": 52.4}}):
            out = fast_tools.try_fast("podaj temperaturę procesora", _ctx(None))
        self.assertEqual(out, "Temperatura procesora wynosi 52.4 stopni Celsjusza.")
        self.assertNotIn("Dysk", out)

    def test_date_only(self):
        # Plik must-have: „podaj datę / data / który dzisiaj dzień" = TYLKO data.
        for text in ("podaj datę", "data", "który dzisiaj dzień", "ktory dzisiaj dzien"):
            out = fast_tools.try_fast(text, _ctx(None))
            self.assertTrue(out and out.startswith("Dzisiaj jest"), text)
            self.assertNotIn("Temperatura", out, text)


class TestMirror(unittest.TestCase):
    def test_logged_in_ttys_type(self):
        self.assertIsInstance(mirror.logged_in_ttys(), list)

    def test_disabled_is_noop(self):
        import unittest.mock as mock
        with mock.patch.object(config, "MIRROR", False):
            mirror.reply("test")  # nie może rzucić wyjątku

    def test_command_helpers_exist(self):
        self.assertTrue(callable(mirror.reply))
        self.assertTrue(callable(mirror.command))

    def test_dedup_suppresses_repeat(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "tty.log")
        open(path, "a").close()
        with mock.patch.object(config, "MIRROR", True), \
             mock.patch.object(config, "MIRROR_VT", False), \
             mock.patch.object(config, "MIRROR_DEDUP_S", 5.0), \
             mock.patch.object(mirror, "cached_ttys", return_value=[path]):
            mirror._LAST["msg"] = None
            mirror.wall_write("ten sam tekst")
            mirror.wall_write("ten sam tekst")
            mirror.wall_write("inny tekst")
        data = open(path, encoding="utf-8").read()
        self.assertEqual(data.count("ten sam tekst"), 1)
        self.assertEqual(data.count("inny tekst"), 1)


class TestMath(unittest.TestCase):
    def test_add(self):
        self.assertEqual(fast_tools.math_reply("oblicz ile to jest 2 + 2"),
                         "Obliczam. Wynik dodawania to 4.")

    def test_words(self):
        self.assertEqual(fast_tools.math_reply("oblicz 10 minus 3"),
                         "Obliczam. Wynik odejmowania to 7.")
        self.assertEqual(fast_tools.math_reply("oblicz ile to jest 6 razy 7"),
                         "Obliczam. Wynik mnożenia to 42.")
        self.assertEqual(fast_tools.math_reply("oblicz 20 przez 4"),
                         "Obliczam. Wynik dzielenia to 5.")

    def test_stt_variant_do_do(self):
        # STT: „dodać" bywa słyszane jako „do do" (uwaga żywa 2026-09-28).
        self.assertEqual(fast_tools.math_reply("oblicz dwa do do dwa"),
                         "Obliczam. Wynik dodawania to 4.")

    def test_precedence_and_parens(self):
        self.assertEqual(fast_tools.math_reply("policz 2 plus 3 razy 4"),
                         "Obliczam. Wynik działania to 14.")
        self.assertEqual(fast_tools.math_reply("oblicz (2 + 3) * 4"),
                         "Obliczam. Wynik działania to 20.")

    def test_decimal(self):
        self.assertEqual(fast_tools.math_reply("oblicz 2,5 + 0,5"),
                         "Obliczam. Wynik dodawania to 3.")

    def test_division_fraction(self):
        self.assertEqual(fast_tools.math_reply("ile to jest 10 / 3"),
                         "Obliczam. Wynik dzielenia to 3.33333.")

    def test_not_math(self):
        self.assertIsNone(fast_tools.math_reply("oblicz całkę z x^2"))
        self.assertIsNone(fast_tools.math_reply("ile jest wolnej pamięci"))
        self.assertIsNone(fast_tools.math_reply("jaka jest temperatura procesora"))

    def test_div_zero_returns_none(self):
        self.assertIsNone(fast_tools.math_reply("oblicz 8 przez 0"))

    def test_try_fast_routes_math(self):
        out = fast_tools.try_fast("oblicz ile to jest 2 + 2", _ctx(None))
        self.assertEqual(out, "Obliczam. Wynik dodawania to 4.")

    def test_word_numbers(self):
        self.assertEqual(fast_tools.math_reply("oblicz ile to jest dwa dodać dwa"),
                         "Obliczam. Wynik dodawania to 4.")
        self.assertEqual(fast_tools.math_reply("oblicz pięć razy sześć"),
                         "Obliczam. Wynik mnożenia to 30.")
        self.assertEqual(fast_tools.math_reply("policz sto podzielić przez dziesięć"),
                         "Obliczam. Wynik dzielenia to 10.")
        self.assertEqual(fast_tools.math_reply("oblicz ile to jest cztery odjąć trzy"),
                         "Obliczam. Wynik odejmowania to 1.")
        self.assertEqual(fast_tools.math_reply("oblicz dwadzieścia dwa dodać trzy"),
                         "Obliczam. Wynik dodawania to 25.")
        self.assertEqual(fast_tools.math_reply("policz 100 podzielić przez 10"),
                         "Obliczam. Wynik dzielenia to 10.")


class TestWeatherCity(unittest.TestCase):
    def test_extract_city(self):
        from astro.core.extras import extract_city
        self.assertEqual(extract_city("jaka pogoda w Gdańsku"), "gdansku")
        self.assertEqual(extract_city("pogoda"), "")
        self.assertEqual(extract_city("jaka pogoda"), "")

    def test_alias_has_diacritics(self):
        from astro.core.extras import _city_variants
        self.assertIn("Łódź", _city_variants("lodzi"))
        self.assertIn("Wrocław", _city_variants("wroclaw"))

    def test_weather_asks_without_city(self):
        from astro.core import extras
        self.assertIn("mieście", extras.weather_text("pogoda"))

    def test_weather_reports_named_city(self):
        from astro.core import extras
        seen = []

        def fake(url):
            seen.append(url)
            if "geocoding" in url:
                return {"results": [{"name": "Kraków", "latitude": 50.0, "longitude": 19.9,
                                     "population": 760000, "country_code": "PL"}]}
            return {"current": {"temperature_2m": 12.0, "wind_speed_10m": 5.0, "weather_code": 0}}

        orig = extras._get_json
        extras._get_json = fake
        try:
            out = extras.weather_text("pogoda w Krakowie")
        finally:
            extras._get_json = orig
        self.assertIn("krakow", normalize_facts(out))
        self.assertIn("12", out)
        self.assertNotIn("warszaw", normalize_facts(out))


if __name__ == "__main__":
    unittest.main()
