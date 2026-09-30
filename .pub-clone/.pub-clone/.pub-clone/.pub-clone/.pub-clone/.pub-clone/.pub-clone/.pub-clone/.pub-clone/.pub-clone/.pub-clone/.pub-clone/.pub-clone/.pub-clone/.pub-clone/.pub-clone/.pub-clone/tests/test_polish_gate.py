"""Test bramki polszczyzny (uruchamia scripts/polish_gate.py jako funkcję)."""

import unittest
from unittest import mock

from astro.scripts import polish_gate


class TestPolishGate(unittest.TestCase):
    def test_gate_passes(self):
        with mock.patch("builtins.print"):
            self.assertEqual(polish_gate.main(), 0)


if __name__ == "__main__":
    unittest.main()
