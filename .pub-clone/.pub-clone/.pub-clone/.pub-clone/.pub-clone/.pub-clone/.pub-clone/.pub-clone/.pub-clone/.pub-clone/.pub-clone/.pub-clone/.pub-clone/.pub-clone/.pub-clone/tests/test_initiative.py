"""Testy proaktywności ASTRO (M4): powitanie, spontaniczny humor, tryb cichy, cisza nocna."""

import os
import tempfile
import time
import unittest
from unittest import mock

from astro import config
from astro.core import initiative
from astro.core.initiative import Initiative
from astro.user import intake


class _FakeProfiles:
    def __init__(self, data):
        self._data = dict(data)

    def get(self):
        return dict(self._data)


class _FakeMem:
    def __init__(self, data):
        self.profiles = _FakeProfiles(data)


def _noon_ts():
    """Znacznik czasu dla południa lokalnego (poza ciszą nocną)."""
    lt = time.localtime()
    noon = time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
    return time.mktime(noon)


class TestInitiative(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(tempfile.mkdtemp(), "initiative.json")
        self.now = _noon_ts()

    def _init(self, **kw):
        kw.setdefault("state_path", self.tmp)
        kw.setdefault("enabled", True)
        kw.setdefault("quiet", False)
        return Initiative(**kw)

    def test_greeting_contextual(self):
        init = self._init()
        text = init.greeting(now=self.now)
        self.assertTrue(text)
        self.assertIn("Dzień dobry", text)

    def test_greeting_cooldown(self):
        init = self._init()
        self.assertTrue(init.greeting(now=self.now))
        self.assertIsNone(init.greeting(now=self.now + 60))

    def test_global_cooldown_blocks_second(self):
        init = self._init()
        init.greeting(now=self.now)
        # powitanie zarejestrowane -> kolejna inicjatywa w cooldownie globalnym
        self.assertIsNone(init.remark("idle", now=self.now + 30))

    def test_quiet_mode_blocks_everything(self):
        init = self._init(quiet=True)
        self.assertIsNone(init.greeting(now=self.now))
        self.assertIsNone(init.remark("idle", now=self.now))

    def test_quiet_hours_block_idle_allow_greeting(self):
        init = self._init()
        night = self.now + 12 * 3600  # ~ północ
        with mock.patch.object(config, "INITIATIVE_QUIET_START", 22), \
             mock.patch.object(config, "INITIATIVE_QUIET_END", 7):
            self.assertIsNone(init.remark("idle", now=night))
            self.assertTrue(init.greeting(now=night))

    def test_remark_event(self):
        init = self._init()
        self.assertIn("jestem", init.remark("idle", now=self.now).lower())
        self.assertIsNone(init.remark("nieznane", now=self.now))

    def test_spontaneous_joke_respects_quiet(self):
        init = self._init(quiet=True)
        self.assertIsNone(init.spontaneous_joke(now=self.now))

    def test_greeting_asks_short_profile_question(self):
        # Spontaniczne zbieranie kontekstu: powitanie dopytuje JEDNO krótkie pole (brak profilu).
        init = self._init()
        text = init.greeting(memory=_FakeMem({}), now=self.now)
        self.assertIn("Jak mam się do Ciebie zwracać", text)

    def test_greeting_profile_question_only_when_missing(self):
        init = self._init()
        full = {k: "x" for k, _q, _h in intake.QUESTIONS}
        text = init.greeting(memory=_FakeMem(full), now=self.now)
        self.assertNotIn("Jak mam się do Ciebie zwracać", text)

    def test_profile_question_suppressed_at_night(self):
        init = self._init()
        night = self.now + 12 * 3600
        with mock.patch.object(config, "INITIATIVE_QUIET_START", 22), \
             mock.patch.object(config, "INITIATIVE_QUIET_END", 7):
            text = init.greeting(memory=_FakeMem({}), now=night)
        self.assertNotIn("Jak mam się do Ciebie zwracać", text)

    def test_handle_command_toggle(self):
        with mock.patch.object(initiative, "Initiative", lambda: self._init()):
            r = initiative.handle_command("tryb cichy")
            self.assertEqual(r[1], "initiative-quiet")
            r2 = initiative.handle_command("wróć do rozmowy")
            self.assertEqual(r2[1], "initiative-loud")
        self.assertIsNone(initiative.handle_command("jaka pogoda"))


if __name__ == "__main__":
    unittest.main()
