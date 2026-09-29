"""Testy audio E7: wake „Astro", TTS/robocik, STT, przechwytywanie i pętla głosowa."""

import os
import tempfile
import types
import unittest
import wave

import numpy as np

from astro import audio, config
from astro.audio import capture, signals, wake
from astro.audio.loop import (VoiceLoop, _known_score, _pick_transcript, _weak_transcript, is_sleep)
from astro.audio.stt import STT, fix_asr
from astro.audio.tts import TTS
from astro.core import command_match


class TestWake(unittest.TestCase):
    def test_wake_word_config(self):
        self.assertEqual(config.WAKE_WORD, "hej astro")

    def test_is_wake(self):
        self.assertTrue(audio.is_wake("Hej Astro, jaka pogoda?"))
        self.assertTrue(audio.is_wake("hej astro sprawdź temperaturę"))
        self.assertTrue(audio.is_wake("no hej, astro, obudź się"))

    def test_no_false_positive(self):
        # Pojedyncze słowa NIE budzą — dopiero cała fraza (fraza dwusłowna dla odporności).
        self.assertFalse(audio.is_wake("hej, jak się masz?"))
        self.assertFalse(audio.is_wake("astro to dziedzina nauki"))
        self.assertFalse(audio.is_wake("edycja pliku"))
        self.assertFalse(audio.is_wake("otwórz edytor"))
        self.assertFalse(audio.is_wake("dziennik"))

    def test_strip_wake(self):
        self.assertEqual(audio.strip_wake("Hej Astro, sprawdź temperaturę"), "sprawdź temperaturę")
        self.assertEqual(audio.strip_wake("hej astro jaka pogoda"), "jaka pogoda")
        self.assertEqual(audio.strip_wake("bez wake"), "bez wake")

    def test_vosk_warm_without_model(self):
        wd = wake.WakeDetector(model_path="/nonexistent/vosk-model")
        self.assertFalse(wd.available())
        self.assertFalse(wd.warm())


class TestNpuWarm(unittest.TestCase):
    def test_warm_stt_survives_missing_llm(self):
        from unittest import mock
        from astro.backends.npu import NpuEngine
        eng = NpuEngine(llm_hef="/nonexistent.hef", whisper_hef="/nonexistent.hef")
        calls = {"s2t": 0, "llm": 0}

        def s2t():
            calls["s2t"] += 1
            return object()

        def llm():
            calls["llm"] += 1
            raise RuntimeError("brak HEF LLM")

        with mock.patch.object(eng, "_ensure_s2t", side_effect=s2t), \
                mock.patch.object(eng, "_ensure_llm", side_effect=llm):
            eng.warm()
        # STT rozgrzane mimo błędu LLM (kolejność i niezależność prób).
        self.assertEqual(calls["s2t"], 1)
        self.assertEqual(calls["llm"], 1)


class TestSignals(unittest.TestCase):
    def test_wake_pcm(self):
        pcm = signals.wake_pcm(22050)
        expected = int(22050 * 0.10) * 2 + int(22050 * 0.05)
        self.assertEqual(len(pcm), expected)
        self.assertLessEqual(float(np.max(np.abs(pcm))), 0.36)

    def test_done_pcm(self):
        pcm = signals.done_pcm(22050)
        self.assertEqual(len(pcm), int(22050 * 0.12))
        self.assertTrue(np.all(np.abs(pcm) <= 0.31))

    def test_sleep_word(self):
        self.assertTrue(is_sleep("dziękuję"))
        self.assertTrue(is_sleep("Dziękuję bardzo"))
        self.assertTrue(is_sleep("dzięki"))
        self.assertFalse(is_sleep("dziękuję, a teraz temperatura"))
        self.assertFalse(is_sleep("nie dziękuję"))


class TestTTS(unittest.TestCase):
    def test_unavailable_paths(self):
        tts = TTS(engine="piper", piper="/nie/ma/piper", model="/nie/ma.onnx")
        self.assertFalse(tts.available())

    def test_none_engine(self):
        self.assertFalse(TTS(engine="none").available())

    def test_synth_cmd(self):
        tts = TTS(engine="piper", piper="/bin/echo", model="voice.onnx")
        cmd = tts.synth_cmd("/tmp/out.wav")
        self.assertEqual(cmd[0], "/bin/echo")
        self.assertIn("--model", cmd)
        self.assertIn("voice.onnx", cmd)

    def test_fx_chain(self):
        tts = TTS(engine="piper", fx="pitch 200 chorus 0.6 0.9 50 0.4 0.25 2 -t echo 0.8 0.88 50 0.3")
        argv = tts.fx_argv("in.wav", "out.wav")
        self.assertIsNotNone(argv)
        self.assertEqual(argv[:3], ["sox", "in.wav", "out.wav"])
        self.assertIn("pitch", argv)
        self.assertIsNone(TTS(engine="piper", fx="").fx_argv("in.wav", "out.wav"))

    def test_play_cmd(self):
        tts = TTS(engine="piper", player="aplay", device="plughw:CARD=wm8960,DEV=0")
        self.assertEqual(tts.play_cmd("x.wav"),
                         ["aplay", "-D", "plughw:CARD=wm8960,DEV=0", "x.wav"])

    def test_default_profile_is_clean(self):
        # Wniosek z tts_bench: domyślnie CZYSTY głos (efekty szkodzą zrozumiałości).
        self.assertEqual(config.TTS_FX_PROFILE, "none")
        self.assertEqual(config.TTS_FX, "")
        self.assertIn("subtle", config.TTS_FX_PRESETS)

    def test_mood_presets_avoid_intelligibility_killers(self):
        # Nastrój = tempo/głośność, bez chorus/reverb/echo/pitch/tremolo (mierzone jako szkodliwe).
        from astro.audio import voice_style
        for label, fx in voice_style.PRESETS.items():
            if fx is None:
                continue
            for bad in ("chorus", "reverb", "echo", "pitch", "tremolo"):
                self.assertNotIn(bad, fx, f"{label}: {bad} psuje zrozumiałość")


class FakeNPU:
    def __init__(self, ready):
        self._ready = ready

    def whisper_ready(self):
        return self._ready

    def transcribe(self, pcm, language="pl"):
        return "Astro test"


class TestSTT(unittest.TestCase):
    def test_fix_asr(self):
        self.assertEqual(fix_asr("Astro Ktura Gocina"), "Astro Która Godzina")
        self.assertEqual(fix_asr("jaka pogoda"), "jaka pogoda")

    def test_fix_asr_glosnosc(self):
        # Whisper-Base gubi „l" („gośność") albo zamienia „ś" na „sz" („gorszność").
        self.assertEqual(fix_asr("Jaka Gorszność"), "Jaka Głośność")
        self.assertEqual(fix_asr("podaj gośność"), "podaj głośność")
        self.assertEqual(fix_asr("jaka gorszosc"), "jaka głośność")
        from astro.core import fast_tools
        from astro.safety import normalize_facts
        for text in ("Jaka Gorszność", "podaj gośność", "jaka gorszosc"):
            fixed = fix_asr(text)
            self.assertTrue(fast_tools.VOLUME_RE.search(normalize_facts(fixed)), text)

    def test_fix_asr_ip_and_confirm(self):
        # „IP" dyktowane literami oraz potwierdzenia z zgubionym „d" (sesja 08:1x).
        self.assertEqual(fix_asr("podaj i b"), "podaj ip")
        self.assertEqual(fix_asr("wyświetl i p"), "wyświetl ip")
        self.assertEqual(fix_asr("podaj i pa"), "podaj ip")
        self.assertEqual(fix_asr("podaj i"), "podaj ip")
        self.assertEqual(fix_asr("Potwierzam"), "Potwierdzam")
        self.assertEqual(fix_asr("Zatwirdzam"), "Zatwierdzam")

    def test_unavailable(self):
        self.assertFalse(STT(engine="npu", npu=FakeNPU(False)).available())

    def test_silence_returns_empty(self):
        stt = STT(engine="npu", npu=FakeNPU(True))
        self.assertEqual(stt.transcribe(np.zeros(16000, dtype="float32")), "")

    def test_loud_calls_npu(self):
        stt = STT(engine="npu", npu=FakeNPU(True))
        loud = _alt(16000, 0.5)
        self.assertEqual(stt.transcribe(loud), "Astro test")

    def test_constant_signal_rejected(self):
        # Sygnał stały/ton (std=0) — Whisper na nim halucynuje; odrzucamy przed NPU.
        stt = STT(engine="npu", npu=FakeNPU(True))
        self.assertEqual(stt.transcribe(np.ones(16000, dtype="float32") * 0.5), "")


class CapturingNPU(FakeNPU):
    def __init__(self):
        super().__init__(True)
        self.seen = None

    def transcribe(self, pcm, language="pl"):
        self.seen = np.asarray(pcm, dtype="float32")
        return "ok"


def _alt(n, level=1.0):
    """Naprzemienny sygnał ±level (std>0) — reprezentuje mowę, nie stały ton."""
    return (((np.arange(n) % 2) * 2 - 1) * level).astype("float32")


class TestSTTNormalize(unittest.TestCase):
    def test_quiet_speech_normalized(self):
        npu = CapturingNPU()
        STT(engine="npu", npu=npu).transcribe(_alt(16000, 0.05))
        self.assertAlmostEqual(float(np.max(np.abs(npu.seen))), 0.95, places=2)

    def test_loud_left_untouched(self):
        npu = CapturingNPU()
        STT(engine="npu", npu=npu).transcribe(_alt(16000, 1.0))
        self.assertAlmostEqual(float(np.max(np.abs(npu.seen))), 1.0, places=2)


class TestCommandGrammar(unittest.TestCase):
    def test_grammar_is_valid_json(self):
        import json
        phrases = json.loads(wake.COMMAND_GRAMMAR)
        self.assertIsInstance(phrases, list)
        self.assertIn("wyłącz system", phrases)
        self.assertIn("poznaj mnie", phrases)
        self.assertIn("[unk]", phrases)

    def test_pick_prefers_known_action(self):
        self.assertEqual(_pick_transcript("Pols na imię", "poznaj mnie"), "poznaj mnie")
        self.assertEqual(_pick_transcript("Pokrasz zasobl", "pokaż zasoby"), "pokaż zasoby")
        self.assertEqual(_pick_transcript("", "reset systemu"), "reset systemu")

    def test_command_grammar_cache_invalidates_on_file_change(self):
        import json
        import os
        import tempfile
        p = tempfile.mktemp(suffix=".musthave")
        try:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("## pierwsza komenda testowa\n")
            g1 = json.loads(wake.build_command_grammar_cached(musthave_path=p))
            self.assertIn("pierwsza komenda testowa", g1)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("## druga komenda testowa\n")
            # wymuś nowy mtime PO zapisie (rozdzielczość FS na tmpfs bywa gruba)
            os.utime(p, (os.path.getmtime(p) + 10, os.path.getmtime(p) + 10))
            g2 = json.loads(wake.build_command_grammar_cached(musthave_path=p))
            self.assertIn("druga komenda testowa", g2)
            self.assertNotIn("pierwsza komenda testowa", g2)
        finally:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_weak_only_for_unclear(self):
        self.assertTrue(_weak_transcript("Pols na imię"))
        self.assertTrue(_weak_transcript(""))
        self.assertFalse(_weak_transcript("wyłącz system"))
        self.assertFalse(_weak_transcript("co to jest fotosynteza"))

    def test_command_match_cache_invalidates_on_file_change(self):
        import os
        import tempfile
        p = tempfile.mktemp(suffix=".musthave")
        saved = dict(command_match._CACHE)
        try:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("## pierwsza komenda testowa\n")
            self.assertIn("pierwsza komenda testowa", command_match.commands(path=p))
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("## druga komenda testowa\n")
            # nowy mtime PO zapisie (patrz test gramatyki — tmpfs ma gruby mtime)
            os.utime(p, (os.path.getmtime(p) + 10, os.path.getmtime(p) + 10))
            cmds = command_match.commands(path=p)
            self.assertIn("druga komenda testowa", cmds)
            self.assertNotIn("pierwsza komenda testowa", cmds)
        finally:
            command_match._CACHE.update(saved)
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_known_score(self):
        self.assertEqual(_known_score("reset systemu"), 3)
        self.assertLess(_known_score("uruchom htop"), 3)
        self.assertEqual(_known_score("bez sensu bełkot"), 0)

    def test_known_score_must_have(self):
        for phrase in ("otwórz opencode", "podaj swoje ip", "pokaż zasoby zdalne",
                       "wyjdź z sieci", "zaproponuj obiad", "podaj temperaturę procesora",
                       "który dzisiaj dzień", "podaj datę", "podaj aj pi"):
            self.assertEqual(_known_score(phrase), 3, phrase)

    def test_grammar_has_must_have(self):
        import json
        phrases = json.loads(wake.COMMAND_GRAMMAR)
        for p in ("otwórz opencode", "podaj ip", "pokaż zasoby zdalne", "wyjdź z sieci"):
            self.assertIn(p, phrases)


class TestCommandBias(unittest.TestCase):
    def test_must_have_phrases_parsed(self):
        import tempfile
        content = (
            "# SYSTEM\n"
            "\t## wylacz system / zamknij system - opis [potwierdzenie]\n"
            "# SKRYPTY\n"
            "\t## KALKULATOR\n"
            "\t\t### oblicz ile to jest [...] / oblicz [...] - liczy\n"
            "\tAstro odpowiada w formie 'obliczam'\n"
            "\t## aktualny kurs [dolara/euro] - kurs NBP\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(content)
            path = fh.name
        phrases = wake._must_have_phrases(path)
        self.assertIn("wylacz system", phrases)
        self.assertIn("oblicz", phrases)
        self.assertIn("aktualny kurs dolara", phrases)
        self.assertNotIn("kalkulator", phrases)
        os.unlink(path)

    def test_build_command_grammar_merges(self):
        import json as _json
        grammar = _json.loads(wake.build_command_grammar(extra=["zagraj muzykę"]))
        self.assertIn("zagraj muzyke", grammar)  # gramatyka normalizuje (bez diakrytyków)
        self.assertIn("[unk]", grammar)
        self.assertIn("wyłącz system", grammar)


class ConfWakeDetector:
    def __init__(self, text="", conf=None):
        self.text, self.conf = text, conf

    def available(self):
        return True

    def transcribe(self, pcm):
        return self.text

    def transcribe_conf(self, pcm):
        return self.text, self.conf

    def command_check(self, pcm):
        return ""


class TestConfidence(unittest.TestCase):
    def setUp(self):
        self._whisper = config.STT_WHISPER_ENABLED
        config.STT_WHISPER_ENABLED = False   # bez realnego ładowania faster-whisper w testach

    def tearDown(self):
        config.STT_WHISPER_ENABLED = self._whisper

    def _loop(self, conf):
        wd = ConfWakeDetector(text="jakis belkot", conf=conf)
        return VoiceLoop(agent=object(), stt=STT(engine="npu", npu=NPUWithText("jakis belkot")),
                         tts=FakeTTS(), wake_detector=wd)

    def test_low_conf_is_uncertain(self):
        _text, unc = self._loop(0.3).transcribe_ex(_alt(16000, 0.5))
        self.assertTrue(unc)

    def test_high_conf_not_uncertain(self):
        _text, unc = self._loop(0.95).transcribe_ex(_alt(16000, 0.5))
        self.assertFalse(unc)


class FakeWakeDetector:
    def __init__(self, free="", grammar=""):
        self.free, self.grammar = free, grammar
        self.free_calls = self.grammar_calls = 0

    def available(self):
        return True

    def transcribe(self, pcm):
        self.free_calls += 1
        return self.free

    def command_check(self, pcm):
        self.grammar_calls += 1
        return self.grammar


class NPUWithText(FakeNPU):
    def __init__(self, text):
        super().__init__(True)
        self._text = text

    def transcribe(self, pcm, language="pl"):
        return self._text


class TestTranscribeRescue(unittest.TestCase):
    def setUp(self):
        self._whisper = config.STT_WHISPER_ENABLED
        config.STT_WHISPER_ENABLED = False   # bez realnego ładowania faster-whisper w testach

    def tearDown(self):
        config.STT_WHISPER_ENABLED = self._whisper

    def _loop(self, npu_text, free="", grammar=""):
        wd = FakeWakeDetector(free=free, grammar=grammar)
        return VoiceLoop(agent=object(), stt=STT(engine="npu", npu=NPUWithText(npu_text)),
                         tts=FakeTTS(), wake_detector=wd), wd

    def test_grammar_rescues_garbled_command(self):
        loop, wd = self._loop("Pols na imię", grammar="poznaj mnie")
        self.assertEqual(loop.transcribe(_alt(16000, 0.5)), "poznaj mnie")
        self.assertEqual(wd.grammar_calls, 1)

    def test_free_vosk_rescues_garbled(self):
        loop, wd = self._loop("Pols na imie", free="poznaj mnie")
        self.assertEqual(loop.transcribe(_alt(16000, 0.5)), "poznaj mnie")

    def test_good_command_untouched(self):
        loop, wd = self._loop("wyłącz system", free="coś innego", grammar="która godzina")
        self.assertEqual(loop.transcribe(_alt(16000, 0.5)), "wyłącz system")
        self.assertEqual(wd.free_calls, 0)
        self.assertEqual(wd.grammar_calls, 0)

    def test_uncertain_flag_grammar_rescue(self):
        loop, _wd = self._loop("Pols na imię", grammar="poznaj mnie")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertEqual(text, "poznaj mnie")
        self.assertTrue(unc)

    def test_uncertain_flag_free_rescue(self):
        # Vosk podał DOKŁADNĄ znaną komendę (fuzzy 1.0) -> pewne, bez potwierdzenia (mniej tarcia).
        loop, _wd = self._loop("Pols na imie", free="poznaj mnie")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertEqual(text, "poznaj mnie")
        self.assertFalse(unc)

    def test_uncertain_flag_free_rescue_fuzzy(self):
        # Ratunek Vosk daje PRZYBLIŻONE, ale INNE trafienie niż kanon (nie sama utrata ogonków)
        # -> nadal niepewne (potwierdź).
        loop, _wd = self._loop("Pols na imie", free="podaj zasoby")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertTrue(unc)

    def test_uncertain_false_when_only_diacritics_lost(self):
        # Ta sama komenda, STT zgubił diakrytyki („aktualna bojina" -> „aktualna godzina")
        # -> traktujemy jako pewne, bez pytania o potwierdzenie (fix 2026-09-29).
        loop, _wd = self._loop("Pols na imie", free="aktualna bojina")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        from astro.core import command_match
        self.assertEqual(command_match.normalize(text), "aktualna godzina")
        self.assertFalse(unc)

    def test_uncertain_false_for_grammar_confirmation(self):
        # Gramatyka znalazła TĘ SAMĄ komendę, którą słyszał NPU (nie wymuszenie na szumie)
        # -> pewne (np. „temperatura cpu").
        loop, _wd = self._loop("temperatura cpu", grammar="temperatura cpu")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertFalse(unc)

    def test_uncertain_true_for_grammar_forced_from_noise(self):
        # NPU słyszał coś niezwiązanego, gramatyka WYMUSIŁA komendę -> nadal potwierdzamy.
        loop, _wd = self._loop("Pols na imie", grammar="poznaj mnie")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertEqual(text, "poznaj mnie")
        self.assertTrue(unc)

    def test_uncertain_flag_false_for_clear(self):
        loop, _wd = self._loop("wyłącz system", free="coś innego", grammar="która godzina")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertEqual(text, "wyłącz system")
        self.assertFalse(unc)

    def test_whisper_cpu_fallback_for_uncertain(self):
        from unittest import mock
        config.STT_WHISPER_ENABLED = True
        loop, _wd = self._loop("Pols na imie", free="", grammar="")
        with mock.patch("astro.audio.loop.whisper_cpu.transcribe",
                        return_value="pokaż zasoby zdalne") as m:
            text = loop.transcribe(_alt(16000, 0.5))
        self.assertTrue(m.called)
        from astro.core import command_match
        self.assertEqual(command_match.normalize(text), "pokaz zasoby zdalne")


class TestHighConfidenceNoConfirm(unittest.TestCase):
    """(d) Pewne trafienie do znanej komendy z własnej transkrypcji -> bez potwierdzenia."""

    def setUp(self):
        self._whisper = config.STT_WHISPER_ENABLED
        config.STT_WHISPER_ENABLED = False
        self._mh = config.MUSTHAVE_FILE
        import tempfile
        self._path = tempfile.mktemp()
        with open(self._path, "w", encoding="utf-8") as fh:
            fh.write("## testowa komenda specjalna\n")
        config.MUSTHAVE_FILE = self._path
        from astro.core import command_match
        command_match.commands()   # odśwież cache na tymczasowy plik

    def tearDown(self):
        config.STT_WHISPER_ENABLED = self._whisper
        config.MUSTHAVE_FILE = self._mh
        from astro.core import command_match
        command_match.commands()   # przywróć cache
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def _loop(self, npu_text, free="", grammar=""):
        wd = FakeWakeDetector(free=free, grammar=grammar)
        return VoiceLoop(agent=object(), stt=STT(engine="npu", npu=NPUWithText(npu_text)),
                         tts=FakeTTS(), wake_detector=wd)

    def test_own_transcript_high_match_is_confident(self):
        loop = self._loop("", free="testowa komenda specjalna")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertEqual(command_match.normalize(text), "testowa komenda specjalna")
        self.assertFalse(unc)

    def test_grammar_forced_high_match_still_uncertain(self):
        loop = self._loop("", free="", grammar="wyłącz system")
        text, unc = loop.transcribe_ex(_alt(16000, 0.5))
        self.assertEqual(command_match.normalize(text), "wylacz system")
        self.assertTrue(unc)


class TestPersistentMic(unittest.TestCase):
    RATE = 16000

    def _plan(self):
        size = int(self.RATE * 0.1)
        alt = ((np.arange(size) % 2) * 2 - 1).astype("float32")
        plan = [(0.0, 5), (0.2, 10)] + [(0.0, 20)]
        for level, n in plan:
            for _ in range(n):
                yield (alt * level).astype("float32")

    def test_prime_once_and_record_from_shared_stream(self):
        from unittest import mock
        consumed = {"n": 0}

        def fake_stream(**kw):
            for c in self._plan():
                consumed["n"] += 1
                yield c

        with mock.patch.object(capture, "stream_pcm", fake_stream):
            mic = capture.PersistentMic(rate=self.RATE)
            first = mic.record(max_s=3.0, threshold=0.01, warmup_s=0.0)
            self.assertTrue(mic._primed)
            self.assertGreater(first.size, 0)
            n_after_first = consumed["n"]
            # warmup odrzucony tylko raz — drugie nagranie nie zjada ponownie rozgrzewki
            mic.record(max_s=1.0, threshold=0.01, warmup_s=0.0)
            self.assertGreater(consumed["n"], n_after_first)
            mic.close()


class TestWhisperCpuPreload(unittest.TestCase):
    def test_preload_false_when_disabled_or_unavailable(self):
        from unittest import mock
        from astro.audio import whisper_cpu
        with mock.patch.object(whisper_cpu, "_preload_started", False), \
                mock.patch("astro.audio.whisper_cpu.config.STT_WHISPER_ENABLED", False):
            self.assertFalse(whisper_cpu.preload())
        with mock.patch.object(whisper_cpu, "_preload_started", False), \
                mock.patch("astro.audio.whisper_cpu.available", return_value=False):
            self.assertFalse(whisper_cpu.preload())

    def test_preload_starts_once_in_background(self):
        from unittest import mock
        from astro.audio import whisper_cpu
        started = []

        class _Thread:
            def __init__(self, target=None, **kwargs):
                started.append(target)

            def start(self):
                pass

        with mock.patch.object(whisper_cpu, "_preload_started", False), \
                mock.patch("astro.audio.whisper_cpu.available", return_value=True), \
                mock.patch("astro.audio.whisper_cpu.threading.Thread", _Thread):
            self.assertTrue(whisper_cpu.preload())
            self.assertFalse(whisper_cpu.preload())
        self.assertEqual(len(started), 1)
        self.assertTrue(callable(started[0]))

    def test_transcribe_skips_constant_signal(self):
        from astro.audio import whisper_cpu
        self.assertEqual(whisper_cpu.transcribe(np.ones(16000, dtype="float32") * 0.5), "")


class TestCapture(unittest.TestCase):
    def test_read_wav(self):
        path = os.path.join(tempfile.mkdtemp(), "t.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(np.array([0, 16384, 32767, -32768], dtype="<i2").tobytes())
        pcm, rate = capture.read_wav(path)
        self.assertEqual(rate, 16000)
        self.assertEqual(pcm.dtype, np.float32)
        self.assertAlmostEqual(float(pcm[1]), 0.5, places=2)
        self.assertGreater(capture.rms(pcm), 0)


class TestVAD(unittest.TestCase):
    RATE = 16000

    def _chunks(self, plan, counter=None):
        size = int(self.RATE * 0.1)
        alt = ((np.arange(size) % 2) * 2 - 1).astype("float32")
        for level, n in plan:
            for _ in range(n):
                if counter is not None:
                    counter[0] += 1
                yield (alt * level).astype("float32")

    def test_detects_speech_and_stops_on_silence(self):
        plan = [(0.0, 5), (0.2, 10)] + [(0.0, 20)]
        counter = [0]
        pcm = capture.speech_from_chunks(
            self._chunks(plan, counter), rate=self.RATE,
            max_s=10.0, silence_s=0.8, min_speech_s=0.3, threshold=0.01, pre_roll_s=0.25)
        self.assertGreater(pcm.size, self.RATE)
        self.assertLess(pcm.size, self.RATE * 3)
        self.assertGreater(counter[0], 20)
        self.assertLess(counter[0], 35)

    def test_silence_only_returns_empty(self):
        pcm = capture.speech_from_chunks(self._chunks([(0.0, 30)]), rate=self.RATE,
                                         max_s=10.0, threshold=0.01)
        self.assertEqual(pcm.size, 0)

    def test_too_short_speech_rejected(self):
        pcm = capture.speech_from_chunks(self._chunks([(0.0, 5), (0.2, 1), (0.0, 20)]),
                                         rate=self.RATE, min_speech_s=0.5, threshold=0.01)
        self.assertEqual(pcm.size, 0)

    def test_warmup_ignores_open_transient(self):
        plan = [(0.5, 1)] + [(0.0, 30)]
        pcm = capture.speech_from_chunks(self._chunks(plan), rate=self.RATE,
                                         min_speech_s=0.1, threshold=0.01, warmup_s=0.4)
        self.assertEqual(pcm.size, 0)

    def test_dc_offset_does_not_trigger(self):
        def dc_chunks():
            for _ in range(15):
                yield np.full(1600, 0.2, dtype="float32")
        pcm = capture.speech_from_chunks(dc_chunks(), rate=self.RATE,
                                         min_speech_s=0.1, threshold=0.01, warmup_s=0.1)
        self.assertEqual(pcm.size, 0)

    def test_max_s_cap(self):
        pcm = capture.speech_from_chunks(self._chunks([(0.2, 100)]), rate=self.RATE,
                                         max_s=1.0, threshold=0.01)
        self.assertLessEqual(pcm.size, self.RATE * 2)

    def test_config_vad_defaults(self):
        self.assertGreater(config.VOICE_VAD_SILENCE_S, 0)
        self.assertGreater(config.VOICE_VAD_MIN_SPEECH_S, 0)
        self.assertGreater(config.VOICE_VAD_THRESHOLD, 0)


class FakeAgent:
    def __init__(self):
        self.seen = []
        self.memory = None
        self.ctx = types.SimpleNamespace(confirmer=None, memory=None, registry=None,
                                         settings=config, backends=None)

    def run(self, text):
        self.seen.append(text)

        class R:
            reply = "ok"
            used_tools = False
            route = "agent"
        return R()


class FakeTTS:
    def __init__(self):
        self.said = []

    def speak(self, text, out_wav=None, fx=None, model=None):
        self.said.append(text)
        return "/tmp/fake.wav"


class TestVoiceLoop(unittest.TestCase):
    def test_handle_wake_then_session(self):
        agent, tts = FakeAgent(), FakeTTS()
        loop = VoiceLoop(agent=agent, stt=object(), tts=tts, session_s=100)
        self.assertEqual(loop.handle_text("Hej Astro, zrób coś miłego"), "ok")
        self.assertEqual(agent.seen, ["zrób coś miłego"])
        self.assertEqual(loop.handle_text("a temperatura?"), "ok")
        self.assertEqual(agent.seen, ["zrób coś miłego", "a temperatura?"])
        self.assertEqual(tts.said, ["ok", "ok"])

    def test_ignores_without_wake(self):
        agent, tts = FakeAgent(), FakeTTS()
        loop = VoiceLoop(agent=agent, stt=object(), tts=tts, session_s=0)
        self.assertIsNone(loop.handle_text("zwykłe zdanie"))
        self.assertEqual(agent.seen, [])


class TestConfirmUncertain(unittest.TestCase):
    def _loop(self, answers):
        loop = VoiceLoop(agent=types.SimpleNamespace(memory=None), stt=object(),
                         tts=FakeTTS(), wake_detector=None, command_s=6, barge_in=False)
        seq = list(answers)
        seen = []

        def fake_record(max_s=None):
            seen.append(("record", max_s))
            return _alt(16000, 0.5)

        def fake_transcribe(pcm):
            seen.append(("transcribe",))
            return (seq.pop(0) if seq else ""), True

        loop._record_speech = fake_record
        loop.transcribe_ex = fake_transcribe
        loop._seen = seen
        return loop

    def _patches(self):
        from unittest import mock
        return (mock.patch.object(config, "TTS_PAUSE_SCALE", 0.0),
                mock.patch("astro.audio.loop.signals.done_signal"))

    def test_plays_beep_and_accepts_yes(self):
        loop = self._loop(["tak"])
        p_pause, p_beep = self._patches()
        with p_pause, p_beep as beep:
            self.assertTrue(loop.confirm_uncertain("wyłącz system"))
        self.assertTrue(beep.called)
        self.assertEqual(loop._seen[0], ("record", 6))

    def test_retries_silence_then_skips(self):
        loop = self._loop(["", ""])
        p_pause, p_beep = self._patches()
        with p_pause, p_beep as beep:
            self.assertFalse(loop.confirm_uncertain("wyłącz system"))
        self.assertEqual(beep.call_count, 2)
        self.assertEqual([s for s in loop._seen if s[0] == "record"],
                         [("record", 6), ("record", 6)])
        self.assertIn("Dobrze, pomijam.", loop.tts.said)

    def test_clear_no_skips_without_retry(self):
        loop = self._loop(["nie"])
        p_pause, p_beep = self._patches()
        with p_pause, p_beep as beep:
            self.assertFalse(loop.confirm_uncertain("wyłącz system"))
        self.assertEqual(beep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
