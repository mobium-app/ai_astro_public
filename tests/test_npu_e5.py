"""Testy E5: telemetria NPU, status urządzenia, polityka NPU-first, fast-path."""

import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from astro import backends as B
from astro import config
from astro.backends import modes
from astro.backends.npu import NpuEngine
from astro.backends.telemetry import NpuTelemetry
from astro.core.fast_tools import try_fast
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


class TestTelemetry(unittest.TestCase):
    def test_record_summary(self):
        path = os.path.join(tempfile.mkdtemp(), "npu.jsonl")
        tel = NpuTelemetry(path)
        tel.record("stt", 0.44, ok=True, model="Whisper-Base")
        tel.record("stt", 0.56, ok=True)
        tel.record("chat", 5.0, ok=False)
        s = tel.summary()
        self.assertEqual(s["stt"]["count"], 2)
        self.assertEqual(s["stt"]["ok"], 2)
        self.assertEqual(s["chat"]["fail"], 1)
        self.assertGreater(s["stt"]["cpu_saved_secs"], 0)
        self.assertIn("stt", tel.text())
        with open(path) as f:
            lines = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(tel.totals()["count"], 3)
        tel.reset()
        self.assertEqual(tel.summary(), {})

    def test_text_empty(self):
        tel = NpuTelemetry(os.path.join(tempfile.mkdtemp(), "npu.jsonl"))
        self.assertIn("brak operacji", tel.text())


class FakeLLM:
    def clear_context(self):
        pass

    def generate_all(self, conv, **kw):
        return "Odpowiedź NPU"


class TestEngineTelemetry(unittest.TestCase):
    def test_chat_records(self):
        path = os.path.join(tempfile.mkdtemp(), "npu.jsonl")
        tel = NpuTelemetry(path)
        eng = NpuEngine(llm_hef=__file__, whisper_hef=__file__)
        eng._llm = FakeLLM()
        with mock.patch("astro.backends.npu.NPU_TELEMETRY", tel):
            out = eng.chat([{"role": "user", "content": "hej"}])
        self.assertEqual(out, "Odpowiedź NPU")
        self.assertEqual(tel.summary()["chat"]["count"], 1)

    def test_chat_records_failure(self):
        path = os.path.join(tempfile.mkdtemp(), "npu.jsonl")
        tel = NpuTelemetry(path)

        class BadLLM:
            def clear_context(self):
                pass

            def generate_all(self, conv, **kw):
                raise RuntimeError("boom")

        eng = NpuEngine(llm_hef=__file__, whisper_hef=__file__)
        eng._llm = BadLLM()
        with mock.patch("astro.backends.npu.NPU_TELEMETRY", tel):
            with self.assertRaises(RuntimeError):
                eng.chat([{"role": "user", "content": "hej"}])
        self.assertEqual(tel.summary()["chat"]["fail"], 1)


class TestStatus(unittest.TestCase):
    def test_device_and_hefs(self):
        self.assertIsInstance(B.device_present(), bool)
        self.assertIsInstance(B.device_holders(), list)
        hefs = B.available_hefs()
        self.assertIn("whisper", hefs)
        self.assertIn("llm", hefs)

    def test_status_text(self):
        text = B.npu_status_text()
        self.assertIn("NPU Hailo", text)
        self.assertIn("Telemetria NPU", text)

    def test_resolve_llm_hef_env(self):
        p = os.path.join(tempfile.mkdtemp(), "fake.hef")
        open(p, "w").close()
        with mock.patch.dict(os.environ, {"ASTRO_NPU_LLM_HEF": p}):
            self.assertEqual(B.resolve_npu_llm_hef(), p)


class TestNpuBackend(unittest.TestCase):
    def test_tools_not_supported(self):
        backend = B.NpuBackend(engine=object())
        with self.assertRaises(RuntimeError):
            backend.run([{"role": "user", "content": "x"}], tools=[{"type": "function"}])


class TestPolicyNpu(unittest.TestCase):
    def test_chat_quality_first_with_npu_optin(self):
        reg = B.BackendRegistry()
        cpu = B.CpuBackend("http://127.0.0.1:11434", "m")
        # Hermetyczność (CI bez lokalnej Ollamy, 2026-10-03): backend cpu musi być „ready",
        # inaczej wybór spada na npu i test mierzy środowisko zamiast polityki NPU_CHAT.
        cpu.ready = lambda: True
        reg.register(cpu)
        npu = B.NpuBackend(engine=object())
        npu.ready = lambda: True
        reg.register(npu)
        # Hermetyczność: NPU-first tylko w trybie offline (nie zależymy od trwałego mode.json).
        with mock.patch.object(modes, "get_mode", return_value=modes.OFFLINE):
            with mock.patch.object(config, "NPU_CHAT", False):
                backend, reason = reg.choose_detail("chat")
                self.assertEqual(backend.name, "cpu")
            with mock.patch.object(config, "NPU_CHAT", True):
                backend, reason = reg.choose_detail("chat")
                self.assertEqual(backend.name, "npu")
                self.assertIn("npu", reason)

    def test_embed_not_npu(self):
        from astro.backends.registry import POLICY
        self.assertNotIn("npu", POLICY["embed"])
        self.assertEqual(POLICY["embed"][0], "cpu")


class TestFastPath(unittest.TestCase):
    def test_npu_fast(self):
        ctx = ToolContext(settings=config, memory=None, confirmer=Confirmer(auto=True),
                          registry=registry)
        out = try_fast("sprawdź stan npu i telemetrię", ctx)
        self.assertIsNotNone(out)
        self.assertIn("NPU", out)

    def test_selection_includes_npu_status(self):
        names = registry.select_names("pokaż stan hailo npu")
        self.assertIn("npu_status", names)


class TestNpuGate(unittest.TestCase):
    """Faza 4: priorytetowa kolejka NPU — STT wyprzedza wizję, FIFO w obrębie priorytetu."""

    def _run(self, tasks, hold=0.4):
        import threading
        from astro.backends.npu import NpuGate
        gate = NpuGate()
        order = []
        lock = threading.Lock()
        holding = threading.Event()
        threads = []

        def worker(prio, name, is_first):
            with gate(prio):
                with lock:
                    order.append(name)
                if is_first:
                    holding.set()
                time.sleep(hold)

        for i, (p, n) in enumerate(tasks):
            if i == 0:
                t = threading.Thread(target=worker, args=(p, n, True))
                t.start()
                self.assertTrue(holding.wait(2.0), "v1 nie trzyma bramki")
            else:
                before = gate.summary()["waits"]
                t = threading.Thread(target=worker, args=(p, n, False))
                t.start()
                deadline = time.time() + 2.0
                while time.time() < deadline and gate.summary()["waits"] <= before:
                    time.sleep(0.01)
                self.assertGreater(gate.summary()["waits"], before,
                                   f"{n} nie doszedł do kolejki")
            threads.append(t)
            time.sleep(0.05)
        time.sleep(0.05)
        for t in threads:
            t.join()
        return gate, order

    def test_fifo_same_priority(self):
        _, order = self._run([(2, "v1"), (2, "v2"), (2, "v3")])
        self.assertEqual(order, ["v1", "v2", "v3"])

    def test_stt_jumps_ahead_of_vision(self):
        # Długie trzymanie v1 (0,6 s) — stt zdąży na pewno wejść do kolejki przed zwolnieniem.
        _, order = self._run([(2, "v1"), (2, "v2"), (0, "stt")], hold=0.6)
        self.assertEqual(order, ["v1", "stt", "v2"])

    def test_llm_before_vision(self):
        _, order = self._run([(2, "v1"), (1, "chat")], hold=0.6)
        self.assertEqual(order, ["v1", "chat"])

    def test_summary_counts_waits(self):
        gate, _ = self._run([(2, "v1"), (2, "v2"), (0, "stt")], hold=0.6)
        s = gate.summary()
        self.assertEqual(s["acquires"], 3)
        self.assertEqual(s["waits"], 2)

    def test_reentrant_same_thread(self):
        """Zagnieżdżone wejście tego samego wątku nie wisi (wizja: detect_* -> get_vdevice).

        Regresja 2026-09-29: `NpuGate` nie był reentrantny — `detect_faces`/`detect_objects`
        trzymały bramkę i wołały `get_vdevice`, które brało ją ponownie -> martwy punkt,
        ASTRO zawieszał się na pierwszej komendzie kamery.
        """
        import threading
        from astro.backends.npu import NpuGate
        gate = NpuGate()
        result = {}

        def nested():
            with gate(2):                     # zewnętrzne wejście (wizja)
                with gate(2):                 # zagnieżdżone (get_vdevice)
                    result["inner"] = True
                result["outer"] = True

        t = threading.Thread(target=nested)
        t.start()
        t.join(3.0)
        self.assertFalse(t.is_alive(), "zagnieżdżone wejście zablokowało wątek")
        self.assertTrue(result.get("inner") and result.get("outer"))

        # Po zwolnieniu kolejka działa normalnie — inny wątek wchodzi.
        got = []
        def other():
            with gate(2):
                got.append("ok")
        t2 = threading.Thread(target=other)
        t2.start()
        t2.join(2.0)
        self.assertEqual(got, ["ok"])


class TestVlmEngine(unittest.TestCase):
    def test_resolve_vlm_hef_env(self):
        p = os.path.join(tempfile.mkdtemp(), "fake-vlm.hef")
        open(p, "w").close()
        with mock.patch.dict(os.environ, {"ASTRO_VLM_HEF": p}):
            self.assertEqual(B.resolve_vlm_hef(), p)

    def test_resolve_vlm_hef_prefers_qwen3(self):
        """Qwen3-VL-2B jest preferowany, gdy jest; fallback Qwen2-VL-2B."""
        import pathlib
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "models" / "hailo").mkdir(parents=True)
            (repo / "models" / "hailo" / "Qwen3-VL-2B-Instruct.hef").touch()
            (repo / "models" / "hailo" / "Qwen2-VL-2B-Instruct.hef").touch()
            with mock.patch.object(config, "REPO", repo), \
                    mock.patch.dict(os.environ, {"ASTRO_VLM_HEF": ""}), \
                    mock.patch.object(config, "VLM_HEF", ""):
                self.assertTrue(str(B.resolve_vlm_hef()).endswith("Qwen3-VL-2B-Instruct.hef"))
            (repo / "models" / "hailo" / "Qwen3-VL-2B-Instruct.hef").unlink()
            with mock.patch.object(config, "REPO", repo), \
                    mock.patch.dict(os.environ, {"ASTRO_VLM_HEF": ""}), \
                    mock.patch.object(config, "VLM_HEF", ""):
                self.assertTrue(str(B.resolve_vlm_hef()).endswith("Qwen2-VL-2B-Instruct.hef"))

    def test_npu_status_has_gate(self):
        s = B.npu_status()
        self.assertIn("gate", s)
        self.assertIn("acquires", s["gate"])

    def test_vlm_ready_false_without_hef(self):
        eng = NpuEngine(llm_hef=__file__, whisper_hef=__file__)
        eng.vlm_hef = ""
        self.assertFalse(eng.vlm_ready())

    def test_describe_frame_records(self):
        path = os.path.join(tempfile.mkdtemp(), "npu.jsonl")
        tel = NpuTelemetry(path)

        class FakeVLM:
            def __init__(self):
                self.clears = 0

            def clear_context(self):
                self.clears += 1

            def generate_all(self, prompt, frames, **kw):
                return "Widzę dwie osoby przy biurku.<|im_end|>"

        eng = NpuEngine(llm_hef=__file__, whisper_hef=__file__)
        eng._vlm = FakeVLM()
        with mock.patch("astro.backends.npu.NPU_TELEMETRY", tel):
            out = eng.describe_frame([[0, 0, 0]], "kto jest?")
        self.assertEqual(out, "Widzę dwie osoby przy biurku.")
        self.assertEqual(eng._vlm.clears, 1)
        self.assertEqual(tel.summary()["vlm"]["count"], 1)
        self.assertEqual(tel.summary()["vlm"]["ok"], 1)

    def test_describe_frame_retries_empty(self):
        """Faza 4: pusty wynik (Qwen3-VL) -> jedna ponowna próba z próbkowaniem."""
        calls = []

        class FakeVLM:
            def clear_context(self):
                pass

            def generate_all(self, prompt, frames, **kw):
                calls.append(kw)
                return "<|im_end|>" if len(calls) == 1 else "Widzę monitor.<|im_end|>"

        eng = NpuEngine(llm_hef=__file__, whisper_hef=__file__)
        eng._vlm = FakeVLM()
        out = eng.describe_frame([[0, 0, 0]], "co widzisz?")
        self.assertEqual(out, "Widzę monitor.")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1]["do_sample"])
        self.assertGreater(calls[1]["temperature"], 0.1)

    def test_describe_frame_sampling_params(self):
        """Faza VLM: describe_frame przekazuje top_p/top_k/frequency_penalty/do_sample."""
        seen = {}

        class FakeVLM:
            def clear_context(self):
                pass

            def generate_all(self, prompt, frames, **kw):
                seen.update(kw)
                return "Opis."

        eng = NpuEngine(llm_hef=__file__, whisper_hef=__file__)
        eng._vlm = FakeVLM()
        eng.describe_frame([[0, 0, 0]], "co widzisz?")
        self.assertEqual(seen["top_p"], config.VLM_TOP_P)
        self.assertEqual(seen["top_k"], config.VLM_TOP_K)
        self.assertEqual(seen["frequency_penalty"], config.VLM_REPEAT_PENALTY)
        self.assertEqual(seen["do_sample"], config.VLM_DO_SAMPLE)
        self.assertEqual(seen["temperature"], config.VLM_TEMPERATURE)

    def test_vlm_config_defaults_avoid_loops(self):
        # Kara za powtórzenia włączona, próbkowanie jądrowe nie-zerowe (mniej zapętleń PL).
        self.assertGreater(config.VLM_REPEAT_PENALTY, 1.0)
        self.assertGreater(config.VLM_TOP_P, 0.0)
        self.assertGreater(config.VLM_TOP_K, 0)


if __name__ == "__main__":
    unittest.main()


class RecordingLLM:
    def __init__(self):
        self.clears = 0
        self.feeds = []

    def clear_context(self):
        self.clears += 1

    def generate_all(self, conv, **kw):
        self.feeds.append([dict(m) for m in conv])
        return "ok"


class TestKvReuse(unittest.TestCase):
    def _eng(self):
        eng = NpuEngine(llm_hef=__file__, whisper_hef=__file__)
        eng._llm = RecordingLLM()
        return eng

    def test_clears_by_default(self):
        eng = self._eng()
        c1 = [{"role": "system", "content": "s"}, {"role": "user", "content": "a"}]
        c2 = c1 + [{"role": "assistant", "content": "r"}, {"role": "user", "content": "b"}]
        with mock.patch.object(config, "NPU_KV_REUSE", False):
            eng.chat(c1)
            eng.chat(c2)
        self.assertEqual(eng._llm.clears, 2)
        self.assertEqual(len(eng._llm.feeds[1]), 4)

    def test_reuse_on_prefix_extension(self):
        eng = self._eng()
        c1 = [{"role": "system", "content": "s"}, {"role": "user", "content": "a"}]
        c2 = c1 + [{"role": "assistant", "content": "r"}, {"role": "user", "content": "b"}]
        with mock.patch.object(config, "NPU_KV_REUSE", True):
            eng.chat(c1)
            eng.chat(c2)
        self.assertEqual(eng._llm.clears, 1)
        self.assertEqual(eng._llm.feeds[1], c2[2:])

    def test_reuse_resets_on_changed_prefix(self):
        eng = self._eng()
        with mock.patch.object(config, "NPU_KV_REUSE", True):
            eng.chat([{"role": "user", "content": "a"}])
            eng.chat([{"role": "user", "content": "zupelnie inne"}])
        self.assertEqual(eng._llm.clears, 2)
