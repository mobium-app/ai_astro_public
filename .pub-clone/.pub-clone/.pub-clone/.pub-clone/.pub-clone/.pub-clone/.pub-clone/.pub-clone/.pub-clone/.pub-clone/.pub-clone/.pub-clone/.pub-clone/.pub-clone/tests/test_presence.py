"""Testy obecności (M5): przejścia enter/leave, bezpieczeństwo detektora, powitanie."""

import os
import tempfile
import time
import unittest

from astro.core.initiative import Initiative
from astro.core.presence import Presence


def _noon():
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))


class TestPresence(unittest.TestCase):
    def test_disabled_returns_none(self):
        p = Presence(detector=lambda: True, enabled=False)
        self.assertIsNone(p.poll())

    def test_transitions(self):
        state = {"v": False}
        p = Presence(detector=lambda: state["v"], enabled=True)
        self.assertIsNone(p.poll())
        state["v"] = True
        self.assertEqual(p.poll(), "enter")
        self.assertIsNone(p.poll())
        state["v"] = False
        self.assertEqual(p.poll(), "leave")

    def test_detector_error_is_safe(self):
        def boom():
            raise RuntimeError("brak kamery")

        p = Presence(detector=boom, enabled=True)
        self.assertIsNone(p.poll())

    def test_greeting_via_initiative(self):
        init = Initiative(state_path=os.path.join(tempfile.mkdtemp(), "i.json"),
                          enabled=True, quiet=False)
        p = Presence(detector=lambda: True, enabled=True)
        self.assertTrue(p.greeting(init, now=_noon()))


if __name__ == "__main__":
    unittest.main()
