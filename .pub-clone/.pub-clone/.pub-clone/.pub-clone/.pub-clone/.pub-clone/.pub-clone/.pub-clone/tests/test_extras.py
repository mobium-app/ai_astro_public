"""Testy szybkich ścieżek dodatkowych: odmiana miast, nazwy usług."""

import unittest

from astro.core import extras


class TestCityVariants(unittest.TestCase):
    def test_locative(self):
        self.assertIn("poznan", extras._city_variants("poznaniu"))

    def test_stem_kept(self):
        self.assertIn("krakow", extras._city_variants("krakowie"))


class TestServiceName(unittest.TestCase):
    def test_explicit(self):
        self.assertEqual(extras.service_name("stan usługi ssh"), "ssh")

    def test_alias(self):
        self.assertEqual(extras.service_name("status samby"), "smbd")

    def test_astro(self):
        self.assertEqual(extras.service_name("stan usługi astro"), "astro")

    def test_none(self):
        self.assertEqual(extras.service_name("jaka pogoda"), "")


if __name__ == "__main__":
    unittest.main()
