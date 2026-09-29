"""Testy ekspresyjnego TTS (E8.2): plan per nastrój, głosy z env, pauzy, override modelu."""

import os
import unittest
from unittest import mock

from astro import config
from astro.audio import express, voice_style
from astro.audio.tts import TTS
from astro.memory import Memory


class TestPlan(unittest.TestCase):
    def setUp(self):
        self._pitch = getattr(config, "TTS_PITCH", "")
        config.TTS_PITCH = ""

    def tearDown(self):
        config.TTS_PITCH = self._pitch

    def test_plan_defaults(self):
        p = express.plan("radosna")
        self.assertEqual(p["mood"], "radosna")
        self.assertEqual(p["fx"], voice_style.PRESETS["radosna"])
        self.assertEqual(p["model"], config.TTS_MODEL)
        self.assertIn("pause", p)

    def test_pause_scaling(self):
        self.assertLess(express.pause_for("radosna"), express.pause_for("zmęczona"))
        with mock.patch("astro.config.TTS_PAUSE_SCALE", 2.0):
            self.assertAlmostEqual(express.pause_for("zmęczona"), 2.0)

    def test_voice_env_override(self):
        with mock.patch.dict(os.environ, {"ASTRO_TTS_VOICE_ZMARTWIONA": "/x/pl.onnx"}):
            self.assertEqual(express.voice_for("zmartwiona"), "/x/pl.onnx")
            self.assertEqual(express.plan("zmartwiona")["model"], "/x/pl.onnx")

    def test_plan_for_affect(self):
        mem = Memory(":memory:")
        from astro.affect import AffectState
        s = AffectState()
        s.apply(2.0, 2.0, 1.0)
        mem.affect.save(s)
        p = express.plan_for_affect(mem)
        self.assertEqual(p["mood"], "radosna")

    def test_plan_for_affect_without_memory(self):
        self.assertEqual(express.plan_for_affect(None)["mood"], "neutralna")


class TestTTSModel(unittest.TestCase):
    def test_synth_cmd_model_override(self):
        t = TTS(engine="piper", piper="/usr/bin/piper", model="/default.onnx")
        self.assertIn("/override.onnx", t.synth_cmd("out.wav", model="/override.onnx"))
        self.assertIn("/default.onnx", t.synth_cmd("out.wav"))

    def test_loop_uses_plan(self):
        from astro.audio.loop import VoiceLoop
        import tempfile

        class FakeTTS:
            def __init__(self):
                self.calls = []

            def speak(self, text, out_wav=None, fx=None, model=None):
                self.calls.append((fx, model))
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

        import types
        mem = Memory(":memory:")
        agent = types.SimpleNamespace(memory=mem)
        fake = FakeTTS()
        loop = VoiceLoop(agent=agent, stt=FakeSTT(), tts=fake, wake_detector=FakeWake(),
                         barge_in=False)
        loop.say("cześć")
        fx, model = fake.calls[0]
        self.assertEqual(fx, express.plan("neutralna")["fx"])
        self.assertEqual(model, express.voice_for("neutralna"))


if __name__ == "__main__":
    unittest.main()
