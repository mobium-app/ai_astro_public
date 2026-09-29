"""Testy Wi-Fi offline: rozpoznawanie intencji, skan (pusty), dopasowanie SSID, beep."""

import unittest
from unittest import mock

from astro import wifi
from astro.audio import signals


class TestIntent(unittest.TestCase):
    def test_scan(self):
        for t in ("wyszukaj dostępne sieci wifi", "zeskanuj sieci", "jakie są sieci wifi",
                  "pokaż dostępne sieci", "lista sieci wifi"):
            self.assertEqual((wifi.intent(t) or {}).get("action"), "scan", t)

    def test_connect(self):
        i = wifi.intent("podłącz do sieci MojaSiec")
        self.assertEqual(i["action"], "connect")
        self.assertIn("mojasiec", i["ssid"].lower())

    def test_connect_inline_password(self):
        i = wifi.intent("połącz z wifi Domowa hasło małe a duże Be koniec")
        self.assertEqual(i["action"], "connect")
        self.assertIn("domowa", i["ssid"].lower())
        self.assertIn("male", i["password"].lower())
        self.assertIn("be", i["password"].lower())

    def test_disconnect(self):
        i = wifi.intent("rozłącz z siecią Domowa")
        self.assertEqual(i["action"], "disconnect")
        self.assertIn("domowa", i["name"].lower())

    def test_connect_fuzzy_verb(self):
        i = wifi.intent("polancz sie z siecia Domowa")
        self.assertEqual(i["action"], "connect")
        self.assertIn("domowa", i["ssid"].lower())

    def test_none(self):
        self.assertIsNone(wifi.intent("połącz się przez ssh z komputerem"))
        self.assertIsNone(wifi.intent("jaka pogoda"))


class TestScan(unittest.TestCase):
    def test_empty_scan_message(self):
        with mock.patch.object(wifi, "scan", return_value=[]), \
             mock.patch.object(wifi, "available", return_value=True):
            self.assertEqual(wifi.scan_text(), "brak dostępnych sieci w zasięgu")

    def test_scan_text_lists(self):
        rows = [{"ssid": "Dom", "signal": 80, "security": "WPA2"},
                {"ssid": "Kawiarnia", "signal": 40, "security": "--"}]
        with mock.patch.object(wifi, "scan", return_value=rows), \
             mock.patch.object(wifi, "available", return_value=True), \
             mock.patch.object(wifi.mirror, "wall_write"):
            txt = wifi.scan_text()
        self.assertIn("Dom", txt)
        self.assertIn("otwarta", txt)

    def test_is_open(self):
        self.assertTrue(wifi.is_open("--"))
        self.assertTrue(wifi.is_open(""))
        self.assertFalse(wifi.is_open("WPA2"))


class TestResolve(unittest.TestCase):
    def test_partial(self):
        rows = [{"ssid": "MojaDomowaSiec", "signal": 70, "security": "WPA2"},
                {"ssid": "Sasiad", "signal": 30, "security": "WPA2"}]
        with mock.patch.object(wifi, "scan", return_value=rows):
            self.assertEqual(wifi.resolve("domowa"), "MojaDomowaSiec")

    def test_missing(self):
        with mock.patch.object(wifi, "scan", return_value=[{"ssid": "X", "signal": 1,
                                                            "security": "WPA2"}]):
            self.assertIsNone(wifi.resolve("nieistniejaca"))

    def test_separators_and_digit_words(self):
        rows = [{"ssid": "Kapibara_2G", "signal": 80, "security": "WPA2"},
                {"ssid": "Kapibara_5G", "signal": 60, "security": "WPA2"}]
        with mock.patch.object(wifi, "scan", return_value=rows):
            self.assertEqual(wifi.resolve("kapibara 2g"), "Kapibara_2G")
            self.assertEqual(wifi.resolve("kapibara dwa"), "Kapibara_2G")


class TestSignals(unittest.TestCase):
    def test_tick_pcm_len(self):
        pcm = signals.tick_pcm(22050)
        self.assertGreater(len(pcm), 0)
        self.assertLessEqual(float(abs(pcm).max()), 0.25)


if __name__ == "__main__":
    unittest.main()
