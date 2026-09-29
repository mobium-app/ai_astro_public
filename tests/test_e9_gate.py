"""Test bramki polszczyzny modelu (E9) — evaluate() i main() z zamockowanym modelem."""

import unittest
from unittest import mock

from astro.scripts import e9_gate


class TestEvaluate(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(e9_gate.evaluate("Jestem Astro i pomagam po polsku."), [])

    def test_bad(self):
        issues = e9_gate.evaluate("I am the agent **http://x** 😀")
        self.assertTrue(issues)

    def test_empty(self):
        self.assertIn("pusta odpowiedź", e9_gate.evaluate(""))


class TestMain(unittest.TestCase):
    def test_main_offline_skip(self):
        def raise_err(*a, **k):
            raise OSError("brak modelu")
        buf = []
        with mock.patch.object(e9_gate, "_chat", side_effect=raise_err), \
             mock.patch("builtins.print", side_effect=lambda *a, **k: buf.append(" ".join(map(str, a)))):
            rc = e9_gate.main([])
        self.assertEqual(rc, 0)  # wszystko SKIP -> nie failujemy offline


if __name__ == "__main__":
    unittest.main()
