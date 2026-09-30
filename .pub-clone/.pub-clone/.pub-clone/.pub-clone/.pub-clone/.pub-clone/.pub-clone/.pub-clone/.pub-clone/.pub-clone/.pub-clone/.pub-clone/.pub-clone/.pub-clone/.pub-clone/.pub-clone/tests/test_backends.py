"""Testy rejestru backendów: polityka, kaskada, capabilities, opt-in PC."""

import unittest
from unittest import mock

from astro import backends as B
from astro import config
from astro.backends import modes


class Dummy(B.Backend):
    def __init__(self, name, caps, ready=True, fail=False, text=None):
        self.name = name
        self.capabilities = set(caps)
        self._ready = ready
        self._fail = fail
        self._text = text or name
        self.calls = 0

    def ready(self):
        return self._ready

    def run(self, messages, **kw):
        self.calls += 1
        if self._fail:
            raise RuntimeError(f"{self.name} fail")
        return B.BackendResult(text=self._text)


class TestPolicy(unittest.TestCase):
    def test_choose_chat_quality_first_with_npu_optin(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
        reg.register(Dummy("npu", {"chat"}))
        # Hermetyczność: NPU-first istnieje tylko w trybie offline; bez tego test zależałby od
        # trwałego `runtime/mode.json` (usługa mogła zostawić tryb „komputer”).
        with mock.patch.object(modes, "get_mode", return_value=modes.OFFLINE):
            with mock.patch.object(config, "NPU_CHAT", False):
                self.assertEqual(reg.choose("chat").name, "cpu")
            with mock.patch.object(config, "NPU_CHAT", True):
                self.assertEqual(reg.choose("chat").name, "npu")
            self.assertEqual(reg.choose("tools").name, "cpu")
            self.assertEqual(reg.choose("json").name, "cpu")

    def test_pc_only_opt_in(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
        self.assertEqual(reg.choose("heavy").name, "cpu")
        reg.register(Dummy("pc", {"chat", "tools", "json", "plan"}))
        self.assertEqual(reg.choose("heavy").name, "pc")

    def test_local_only_never_falls_back_to_cloud(self):
        # Komendy wykonawcze NIGDY do chmury: bez lokalnego backendu lista jest PUSTA,
        # a nie „wszystkie" (co wpuszczało pc/remote).
        reg = B.BackendRegistry()
        reg.register(Dummy("pc", {"chat", "tools", "json", "plan"}))
        reg.register(Dummy("remote", {"chat", "tools", "json", "plan"}))
        self.assertEqual(reg.order("chat", local_only=True), [])
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
        self.assertEqual([b.name for b in reg.order("chat", local_only=True)], ["cpu"])


class CountingReady(B.Backend):
    def __init__(self, name="cpu", caps=("chat", "tools", "json", "plan")):
        self.name = name
        self.capabilities = set(caps)
        self.ready_calls = 0
        self.calls = 0

    def ready(self):
        self.ready_calls += 1
        return True

    def run(self, messages, **kw):
        self.calls += 1
        return B.BackendResult(text="ok")


class TestReadyCache(unittest.TestCase):
    def test_ready_cached_within_ttl(self):
        reg = B.BackendRegistry()
        b = CountingReady()
        reg.register(b)
        reg.choose("chat")
        reg.choose("chat")
        self.assertEqual(b.ready_calls, 1)

    def test_ready_ttl_zero_disables_cache(self):
        reg = B.BackendRegistry()
        b = CountingReady()
        reg.register(b)
        with mock.patch.object(config, "BACKEND_READY_TTL", 0):
            reg.choose("chat")
            reg.choose("chat")
        self.assertEqual(b.ready_calls, 2)


class TestCascade(unittest.TestCase):
    def test_fallback_on_failure(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("npu", {"chat"}, fail=True))
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}, text="odpowiedź cpu"))
        result = reg.run("chat", [{"role": "user", "content": "hej"}])
        self.assertEqual(result.text, "odpowiedź cpu")

    def test_tools_capability_filtered(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("npu", {"chat"}))
        reg.register(Dummy("cpu", {"chat", "tools"}, text="ok"))
        result = reg.run("tools", [{"role": "user", "content": "x"}], tools=[{"type": "function"}])
        self.assertEqual(result.text, "ok")

    def test_no_backend_raises(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("npu", {"chat"}, ready=False))
        with self.assertRaises(RuntimeError):
            reg.run("chat", [{"role": "user", "content": "x"}])


class TestCpuStreaming(unittest.TestCase):
    class FakeStream:
        def __init__(self, lines):
            self._lines = lines

        def __enter__(self):
            return iter(self._lines)

        def __exit__(self, *a):
            return False

    def test_run_stream_accumulates_and_calls_on_token(self):
        from astro.backends.cpu import CpuBackend
        be = CpuBackend("http://127.0.0.1:11434", "m")
        lines = [b'{"message":{"content":"Hej "},"done":false}\n',
                 b'{"message":{"content":"swiecie"},"done":false}\n',
                 b'{"message":{"content":""},"done":true}\n']
        seen = []
        with mock.patch("urllib.request.urlopen", return_value=self.FakeStream(lines)):
            res = be.run([{"role": "user", "content": "x"}], on_token=seen.append)
        self.assertEqual(res.text, "Hej swiecie")
        self.assertEqual("".join(seen), "Hej swiecie")

    def test_run_stream_passes_tool_calls(self):
        from astro.backends.cpu import CpuBackend
        be = CpuBackend("http://127.0.0.1:11434", "m")
        calls = [{"id": "c1", "type": "function",
                  "function": {"name": "system_info", "arguments": "{}"}}]
        import json as _json
        lines = [_json.dumps({"message": {"content": "", "tool_calls": calls}, "done": True})
                 .encode() + b"\n"]
        with mock.patch("urllib.request.urlopen", return_value=self.FakeStream(lines)):
            res = be.run([{"role": "user", "content": "x"}], tools=[{"type": "function"}],
                         on_token=lambda _t: None)
        self.assertEqual(res.tool_calls, calls)


if __name__ == "__main__":
    unittest.main()
