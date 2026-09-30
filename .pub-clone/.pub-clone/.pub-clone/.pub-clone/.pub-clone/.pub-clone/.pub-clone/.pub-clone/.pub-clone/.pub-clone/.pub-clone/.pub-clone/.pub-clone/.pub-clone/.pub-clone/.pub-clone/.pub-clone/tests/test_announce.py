"""Testy zapowiedzi startowej (D2): wyłączona domyślnie, respektuje ciszę/force."""

import importlib.util
import os
import tempfile
import unittest
from unittest import mock

from astro import config
from astro.core.initiative import Initiative

_SPEC = importlib.util.spec_from_file_location(
    "astro_announce", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "scripts", "astro_announce.py"))
_ANN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ANN)


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text, **kw):
        self.spoken.append(text)
        return "out.wav"


class TestAnnounce(unittest.TestCase):
    def setUp(self):
        self.init = Initiative(state_path=os.path.join(tempfile.mkdtemp(), "i.json"),
                               enabled=True, quiet=False)

    def test_disabled_by_default(self):
        tts = FakeTTS()
        self.assertEqual(_ANN.announce(init=self.init, tts=tts), "")
        self.assertEqual(tts.spoken, [])

    def test_force_speaks(self):
        tts = FakeTTS()
        text = _ANN.announce(force=True, init=self.init, tts=tts)
        self.assertTrue(text)
        self.assertEqual(tts.spoken, [text])

    def test_quiet_blocks(self):
        self.init.set_quiet(True)
        tts = FakeTTS()
        self.assertEqual(_ANN.announce(force=True, init=self.init, tts=tts), "")
        self.assertEqual(tts.spoken, [])


if __name__ == "__main__":
    unittest.main()
