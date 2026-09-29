"""Testy głosu per nastrój (E7.5): mapowanie presetów sox + wpięcie w TTS i pętlę głosową."""

import os
import shlex
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from astro import config
from astro.audio import voice_style
from astro.audio.tts import TTS
from astro.memory import Memory


class TestMapping(unittest.TestCase):
    def setUp(self):
        # Bazowa warstwa tonu (TTS_PITCH) jest opt-in; testy polityki nastrojów zakładają brak.
        self._pitch = getattr(config, "TTS_PITCH", "")
        config.TTS_PITCH = ""

    def tearDown(self):
        config.TTS_PITCH = self._pitch

    def test_all_anchors_have_preset(self):
        # Preset może być pusty (czysty głos — domyślna polityka po pomiarze tts_bench),
        # ale musi być poprawnym łańcuchem sox (str) i bez „zabójców zrozumiałości".
        from astro.affect.affect import ANCHORS
        for label, _guidance, _pad in ANCHORS:
            fx = voice_style.fx_for(label)
            self.assertIsInstance(fx, str, label)
            for bad in ("chorus", "reverb", "echo", "pitch", "tremolo"):
                self.assertNotIn(bad, fx, f"{label}: {bad} psuje zrozumiałość")

    def test_default_fallback(self):
        self.assertEqual(voice_style.fx_for("neutralna"), config.TTS_FX)
        self.assertEqual(voice_style.fx_for("nieznana"), config.TTS_FX)

    def test_affect_fx_from_memory(self):
        mem = Memory(":memory:")
        mem.affect.save(_state_joyful())
        self.assertEqual(voice_style.affect_fx(mem), voice_style.PRESETS["radosna"])

    def test_affect_fx_without_memory(self):
        self.assertEqual(voice_style.affect_fx(None), config.TTS_FX)

    def test_pitch_layer_composes_all_moods(self):
        # Bazowa warstwa tonu (np. „dziecięca") jest spójna dla każdego nastroju.
        old = getattr(config, "TTS_PITCH", "")
        try:
            config.TTS_PITCH = "pitch 350 tempo 1.06"
            self.assertTrue(voice_style.fx_for("neutralna").startswith("pitch 350 tempo 1.06"))
            for label in voice_style.PRESETS:
                self.assertIn("pitch 350 tempo 1.06", voice_style.fx_for(label))
        finally:
            config.TTS_PITCH = old


def _state_joyful():
    from astro.affect import AffectState
    s = AffectState()
    s.apply(2.0, 2.0, 1.0)
    return s


class TestTTSParams(unittest.TestCase):
    def test_fx_argv_override(self):
        if not shutil.which("sox"):
            self.skipTest("brak sox")
        t = TTS(engine="none")
        argv = t.fx_argv("in.wav", "out.wav", fx="pitch 100")
        self.assertEqual(argv[:3], ["sox", "in.wav", "out.wav"])
        self.assertEqual(argv[3:], ["pitch", "100"])

    def test_fx_argv_default(self):
        if not shutil.which("sox"):
            self.skipTest("brak sox")
        t = TTS(engine="none", fx="gain -3")
        self.assertEqual(t.fx_argv("a", "b")[3:], ["gain", "-3"])


class TestSoxChains(unittest.TestCase):
    def test_presets_are_valid_sox(self):
        if not shutil.which("sox"):
            self.skipTest("brak sox")
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.wav")
            subprocess.run(["sox", "-n", src, "synth", "0.2", "sine", "300"], check=True)
            chains = {label: voice_style.fx_for(label) for label in voice_style.PRESETS}
            chains["_default"] = config.TTS_FX
            for label, chain in chains.items():
                out = os.path.join(d, f"{label}.wav")
                argv = ["sox", src, out] + shlex.split(chain)
                r = subprocess.run(argv, capture_output=True)
                self.assertEqual(r.returncode, 0, f"{label}: {r.stderr.decode()[:200]}")


class TestUnifiedDefaultVoice(unittest.TestCase):
    """Regresja: każdy tor mowy bez jawnego fx dziedziczy bazowy ton profilu (spójny głos).

    Wcześniej streaming pierwszego fragmentu, „ogon" odpowiedzi i zapowiedź startu wołały
    `tts.speak(...)` bez fx → goły `config.TTS_FX` („kobieta"), a `say()` dokładał pitch
    („dziewczynka"). Stąd głos zmieniał się między etapami rozmowy."""

    def setUp(self):
        from astro.audio import voice_style
        self.tmp = tempfile.mkdtemp()
        self._rt = mock.patch.object(config, "RUNTIME_DIR", self.tmp)
        self._rt.start()
        self._pitch = getattr(config, "TTS_PITCH", "")
        config.TTS_PITCH = "pitch 350 tempo 1.06"
        voice_style._profile_cache.update(mtime=None, profile=None)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        from astro.audio import voice_style
        self._rt.stop()
        config.TTS_PITCH = self._pitch
        voice_style._profile_cache.update(mtime=None, profile=None)

    def test_tts_default_fx_includes_pitch_layer(self):
        t = TTS(engine="none")
        self.assertIn("pitch 350 tempo 1.06", t.fx)

    def test_tts_explicit_empty_fx_is_clean(self):
        # Jawne fx="" (pomiar STT, testy) nadal wyłącza efekty — pitch nie może wejść.
        t = TTS(engine="none", fx="")
        self.assertEqual(t.fx, "")

    def test_voice_plan_includes_pitch_layer(self):
        from astro.audio.loop import VoiceLoop

        class FakeTTS:
            def speak(self, *a, **k):
                return "out.wav"

        loop = VoiceLoop(agent=types.SimpleNamespace(memory=None), stt=object(), tts=FakeTTS(),
                         wake_detector=object(), barge_in=False)
        self.assertIn("pitch 350 tempo 1.06", loop._voice_plan()["fx"])


class TestLoopWiring(unittest.TestCase):
    def test_say_passes_mood_fx(self):
        from astro.audio.loop import VoiceLoop

        old = getattr(config, "TTS_PITCH", "")
        config.TTS_PITCH = ""
        self.addCleanup(lambda: setattr(config, "TTS_PITCH", old))
        mem = Memory(":memory:")
        mem.affect.save(_state_joyful())
        agent = types.SimpleNamespace(memory=mem)

        class FakeTTS:
            def __init__(self):
                self.calls = []

            def speak(self, text, out_wav=None, fx=None, model=None):
                self.calls.append(fx)
                return "out.wav"

            def synthesize(self, text, out_wav, fx=None, model=None):
                return "out.wav"

            def play(self, wav):
                return True

            def stop(self):
                return False

        class FakeSTT:
            def available(self):
                return False

        class FakeWake:
            def available(self):
                return False

        fake = FakeTTS()
        loop = VoiceLoop(agent=agent, stt=FakeSTT(), tts=fake, wake_detector=FakeWake(),
                         barge_in=False)
        loop.say("cześć")
        self.assertEqual(fake.calls, [voice_style.PRESETS["radosna"]])


class TestGirlVoiceDefault(unittest.TestCase):
    """Regresja 2026-09-29: domyślny głos ASTRO = „mała dziewczynka" (gosia + podniesiony ton).

    Powód: alert kamery poszedł męskim `darkmanem` ze starego procesu vision-watch (config
    wczytany przed zmianą) — wymóg jest teraz zakodowany w configu i pilnowany testem.
    """

    def setUp(self):
        self._patch = mock.patch.object(voice_style, "load_profile", return_value=None)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_default_model_is_gosia(self):
        self.assertIn("gosia", os.path.basename(getattr(config, "TTS_MODEL", "")))

    def test_default_fx_raises_pitch(self):
        self.assertTrue(voice_style.fx_for(None).startswith("pitch 350"))

    def test_all_moods_keep_girl_pitch(self):
        from astro.affect.affect import ANCHORS
        for label, _guidance, _pad in ANCHORS:
            self.assertIn("pitch 350", voice_style.fx_for(label), label)

    def test_tts_object_uses_girl_voice(self):
        t = TTS()
        self.assertIn("gosia", os.path.basename(t.model))
        self.assertIn("pitch 350", t.fx)


if __name__ == "__main__":
    unittest.main()
