"""Testy C4 w torze głosowym: StreamSpeaker (fragmenty) + integracja z VoiceLoop."""

import unittest
from unittest import mock

import astro.audio.loop as loopmod
from astro.audio.stream_speech import StreamSpeaker, _split
from astro.core.dispatch import DispatchResult


class SplitTest(unittest.TestCase):
    def test_sentence_boundary(self):
        frag, rest = _split("Dzień dobry. Jak leci")
        self.assertEqual(frag, "Dzień dobry.")
        self.assertEqual(rest, " Jak leci")

    def test_no_boundary(self):
        frag, rest = _split("bez kropki tutaj")
        self.assertEqual(frag, "")
        self.assertEqual(rest, "bez kropki tutaj")


class SpeakerTest(unittest.TestCase):
    def _mk(self, **kw):
        spoken = []
        sp = StreamSpeaker(speak=spoken.append, **kw)
        self.addCleanup(sp.close)
        return sp, spoken

    def test_speaks_fragments_in_order(self):
        sp, spoken = self._mk(min_first_chars=10)
        sp.feed("To jest pierwsze zdanie odpowiedzi. ")
        sp.feed("A to drugie zdanie.")
        out = sp.finish()
        self.assertIn("To jest pierwsze zdanie odpowiedzi.", spoken[0])
        self.assertTrue(any("drugie zdanie" in s for s in spoken))
        self.assertIn("pierwsze", out)

    def test_short_reply_not_started(self):
        sp, spoken = self._mk(min_first_chars=24)
        sp.feed("Nie wiem.")
        out = sp.finish()
        self.assertEqual(out, "")
        self.assertEqual(spoken, [])

    def test_blocked_ignored(self):
        block = {"v": True}
        sp, spoken = self._mk(min_first_chars=1, is_blocked=lambda: block["v"])
        sp.feed("To zdanie nie powinno być przeczytane.")
        self.assertEqual(sp.finish(), "")
        self.assertEqual(spoken, [])

    def test_reset_discards_buffer(self):
        sp, spoken = self._mk(min_first_chars=1000)
        sp.feed("pierwszy krok")
        sp.reset()
        sp.feed("drugi krok")
        out = sp.finish()
        self.assertNotIn("pierwszy krok", out)


class _FakeTTS:
    def __init__(self):
        self.spoken = []
        self.stopped = 0

    def speak(self, text, **kw):
        self.spoken.append(text)

    def stop(self):
        self.stopped += 1
        return True


class _FakeRegistry:
    def __init__(self, tools=None):
        self._tools = tools or []

    def select(self, text):
        return list(self._tools)


class _FakeCtx:
    pass


class _FakeAgent:
    def __init__(self, tools=None):
        self.ctx = _FakeCtx()
        self.registry = _FakeRegistry(tools)


def _make_loop(agent, tts):
    return loopmod.VoiceLoop(agent=agent, stt=object(), tts=tts,
                             wake_detector=object(), initiative=object())


class LoopStreamTest(unittest.TestCase):
    def test_dispatch_streams_and_avoids_duplicate(self):
        agent = _FakeAgent()
        tts = _FakeTTS()
        loop = _make_loop(agent, tts)
        reply = "To jest pierwsza część odpowiedzi. To druga część."

        def fake_dispatch(command, ag):
            sink = getattr(ag.ctx, "stream_sink", None)
            if sink:
                for piece in ("To jest pierwsza część odpowiedzi. ", "To druga część."):
                    sink(piece)
            return DispatchResult(reply, "agent")

        with mock.patch.object(loopmod, "dispatch", fake_dispatch), \
             mock.patch.object(loopmod.config, "STREAM", True), \
             mock.patch.object(loopmod, "classify_request", lambda t: "question"):
            resp, spoken = loop._dispatch("jak się masz")
            self.assertTrue(spoken.startswith("To jest pierwsza"))
            self.assertTrue(tts.spoken)
            before = len(tts.spoken)
            barged, pcm = loop._say_or_finish_stream(resp.reply, resp, spoken)
            self.assertFalse(barged)
            self.assertEqual(len(tts.spoken), before)  # brak dubletu

    def test_command_not_eligible(self):
        agent = _FakeAgent()
        tts = _FakeTTS()
        loop = _make_loop(agent, tts)
        with mock.patch.object(loopmod.config, "STREAM", True), \
             mock.patch.object(loopmod, "classify_request", lambda t: "command"):
            self.assertFalse(loop._stream_eligible("wyłącz system"))
        with mock.patch.object(loopmod.config, "STREAM", True), \
             mock.patch.object(loopmod, "classify_request", lambda t: "question"):
            self.assertTrue(loop._stream_eligible("jak działa pamięć"))

    def test_default_streaming_disabled(self):
        agent = _FakeAgent()
        tts = _FakeTTS()
        loop = _make_loop(agent, tts)
        with mock.patch.object(loopmod.config, "STREAM", False):
            self.assertFalse(loop._stream_eligible("jak się masz"))


if __name__ == "__main__":
    unittest.main()
