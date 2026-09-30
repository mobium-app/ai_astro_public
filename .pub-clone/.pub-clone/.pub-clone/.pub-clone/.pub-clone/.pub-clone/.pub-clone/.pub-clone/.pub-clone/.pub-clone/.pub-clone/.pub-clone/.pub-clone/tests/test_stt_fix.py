"""Testy korekcji STT nazw (E8.4): miasta i imiona, brak fałszywych trafień."""

import unittest

from astro.user import stt_fix


class TestCities(unittest.TestCase):
    def test_corrects_common_errors(self):
        self.assertEqual(stt_fix.correct_city("Poznani"), "Poznań")
        self.assertEqual(stt_fix.correct_city("Gdans"), "Gdańsk")
        self.assertEqual(stt_fix.correct_city("Wroclaw"), "Wrocław")
        self.assertEqual(stt_fix.correct_city("nowy sacz"), "Nowy Sącz")
        self.assertEqual(stt_fix.correct_city("Zielona Gora"), "Zielona Góra")

    def test_keeps_correct(self):
        self.assertEqual(stt_fix.correct_city("Warszawa"), "Warszawa")
        self.assertEqual(stt_fix.correct_city("Kraków"), "Kraków")

    def test_keeps_unknown(self):
        self.assertEqual(stt_fix.correct_city("Wioska Dolna"), "Wioska Dolna")


class TestNames(unittest.TestCase):
    def test_corrects(self):
        self.assertEqual(stt_fix.correct_name("Michau"), "Michał")
        self.assertEqual(stt_fix.correct_name("Pawel"), "Paweł")

    def test_keeps(self):
        self.assertEqual(stt_fix.correct_name("Anna"), "Anna")
        self.assertEqual(stt_fix.correct_name("Katarzyna"), "Katarzyna")

    def test_multiword_untouched(self):
        self.assertEqual(stt_fix.correct_name("Anna Maria"), "Anna Maria")

    def test_unknown_untouched(self):
        self.assertEqual(stt_fix.correct_name("Xyzabc"), "Xyzabc")


class TestCityForms(unittest.TestCase):
    def test_genitive(self):
        self.assertEqual(stt_fix.genitive_city("Poznań"), "Poznania")
        self.assertEqual(stt_fix.genitive_city("Warszawa"), "Warszawy")
        self.assertEqual(stt_fix.genitive_city("Katowice"), "Katowic")
        self.assertEqual(stt_fix.genitive_city("Nowy Sącz"), "Nowego Sącza")

    def test_locative(self):
        self.assertEqual(stt_fix.locative_city("Poznań"), "Poznaniu")
        self.assertEqual(stt_fix.locative_city("Kraków"), "Krakowie")
        self.assertEqual(stt_fix.locative_city("Katowice"), "Katowicach")

    def test_unknown_unchanged(self):
        self.assertEqual(stt_fix.genitive_city("Wioska Dolna"), "Wioska Dolna")
        self.assertEqual(stt_fix.locative_city("Wioska Dolna"), "Wioska Dolna")


if __name__ == "__main__":
    unittest.main()
