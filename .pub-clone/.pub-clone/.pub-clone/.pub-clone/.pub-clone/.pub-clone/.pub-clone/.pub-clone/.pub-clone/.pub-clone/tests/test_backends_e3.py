"""Testy E3: polityka backendów, remote opt-in, metryki, selekcja narzędzi."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astro import config
from astro import backends as B
from astro.backends import modes
from astro.tools import registry


class Dummy(B.Backend):
    def __init__(self, name, caps, ready=True, text=None, fail=False):
        self.name = name
        self.capabilities = set(caps)
        self._ready = ready
        self._text = text or name
        self._fail = fail

    def ready(self):
        return self._ready

    def run(self, messages, **kw):
        if self._fail:
            raise RuntimeError("fail")
        return B.BackendResult(text=self._text)


class TestPolicy(unittest.TestCase):
    def test_chat_quality_first_cpu_tools(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
        reg.register(Dummy("npu", {"chat"}))
        # Hermetyczność: NPU-first tylko w trybie offline (nie zależymy od trwałego mode.json).
        with mock.patch.object(modes, "get_mode", return_value=modes.OFFLINE):
            with mock.patch.object(config, "NPU_CHAT", False):
                self.assertEqual(reg.choose("chat").name, "cpu")
            with mock.patch.object(config, "NPU_CHAT", True):
                self.assertEqual(reg.choose("chat").name, "npu")
            self.assertEqual(reg.choose("tools").name, "cpu")
            self.assertEqual(reg.choose("json").name, "cpu")
            self.assertEqual(reg.choose("plan").name, "cpu")

    def test_choose_detail_reason(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
        backend, reason = reg.choose_detail("tools")
        self.assertEqual(backend.name, "cpu")
        self.assertIn("CPU", reason)

    def test_npu_skipped_for_tools(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("npu", {"chat"}))
        reg.register(Dummy("cpu", {"chat", "tools"}, text="cpu-tools"))
        result = reg.run("tools", [{"role": "user", "content": "x"}], tools=[{"type": "function"}])
        self.assertEqual(result.text, "cpu-tools")

    def test_pc_and_remote_opt_in(self):
        reg = B.BackendRegistry()
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
        self.assertEqual(sorted(reg.backends), ["cpu"])


class TestBuildDefaultOptIn(unittest.TestCase):
    def test_default_has_only_local_cpu(self):
        reg = B.build_default()
        self.assertTrue(set(reg.backends) <= {"cpu", "cpu_fast"})

    def test_remote_registered_when_enabled(self):
        with mock.patch.object(config, "REMOTE_ENABLED", True), \
             mock.patch.object(config, "REMOTE_URL", "https://api.example.com/v1"), \
             mock.patch.object(config, "REMOTE_MODEL", "model-x"):
            reg = B.build_default()
        self.assertIn("remote", reg.backends)
        self.assertEqual(reg.backends["remote"].endpoint(),
                         "https://api.example.com/v1/chat/completions")

    def test_pc_registered_when_enabled(self):
        with mock.patch.object(config, "PC_ENABLED", True):
            reg = B.build_default()
        self.assertIn("pc", reg.backends)


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def read(self, *a):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestRemoteBackend(unittest.TestCase):
    def test_endpoints(self):
        self.assertTrue(B.RemoteBackend("https://x.com", "m").endpoint()
                        .endswith("/v1/chat/completions"))
        self.assertTrue(B.RemoteBackend("https://x.com/v1", "m").endpoint()
                        .endswith("/v1/chat/completions"))
        self.assertEqual(B.RemoteBackend("https://x.com/v1/chat/completions", "m").endpoint(),
                         "https://x.com/v1/chat/completions")
        self.assertEqual(B.RemoteBackend("", "m").endpoint(), "")

    def test_run_parses_response(self):
        captured = {}
        payload = {"choices": [{"message": {"content": "cześć",
                                            "tool_calls": [{"function": {"name": "man_page",
                                                                         "arguments": "{}"}}]}}]}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.headers)
            return FakeResponse(payload)

        backend = B.RemoteBackend("https://api.example.com/v1", "model-x", key="secret")
        with mock.patch("astro.backends.remote.urllib.request.urlopen", fake_urlopen):
            res = backend.run([{"role": "user", "content": "hej"}], tools=[{"type": "function"}],
                              fmt="json")
        self.assertEqual(res.text, "cześć")
        self.assertEqual(res.tool_calls[0]["function"]["name"], "man_page")
        self.assertEqual(captured["body"]["tools"], [{"type": "function"}])
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})
        self.assertIn("Bearer secret", captured["headers"].get("Authorization", ""))

    def test_ready(self):
        self.assertTrue(B.RemoteBackend("https://x.com", "m").ready())
        self.assertFalse(B.RemoteBackend("", "m").ready())


class TestMetrics(unittest.TestCase):
    def test_metrics_written_and_summarized(self):
        path = os.path.join(tempfile.mkdtemp(), "metrics.jsonl")
        reg = B.BackendRegistry()
        reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}, text="ok"))
        with mock.patch.object(config, "METRICS_FILE", Path(path)):
            reg.run("chat", [{"role": "user", "content": "x"}])
            entries = reg.read_metrics()
            summary = reg.metrics_summary()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["backend"], "cpu")
        self.assertTrue(entries[0]["ok"])
        self.assertIn("cpu:chat", summary)


class TestSelection(unittest.TestCase):
    def test_subset_bounded(self):
        names = registry.select_names("sprawdź stronę man polecenia grep")
        self.assertIn("man_page", names)
        self.assertLessEqual(len(names), config.MAX_TOOLS)
        self.assertLess(len(names), len(registry.names()))

    def test_general_fallback_bounded(self):
        names = registry.select_names("no i tak dalej")
        self.assertLessEqual(len(names), config.MAX_TOOLS)
        self.assertIn("system_info", names)


if __name__ == "__main__":
    unittest.main()
