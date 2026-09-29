"""Testy brakujących modułów runtime (C8): verifier, usage, remote_chain."""

import os
import tempfile
import types
import unittest
from unittest import mock

from astro.backends import remote_chain
from astro.core import usage, verifier


class TestVerifier(unittest.TestCase):
    def test_empty_answer(self):
        ok, nudge = verifier.check("", False, "cześć")
        self.assertFalse(ok)
        self.assertIn("pusta", nudge)

    def test_needs_tools_nudges_once(self):
        ok, nudge = verifier.check("Nie wiem.", False, "jaka jest temperatura procesora?")
        self.assertFalse(ok)
        self.assertIn("narzędzi", nudge)
        # po ponagleniu już nie ponaglamy
        ok2, _ = verifier.check("Nie wiem.", False, "jaka jest temperatura procesora?",
                                already_nudged=True)
        self.assertTrue(ok2)

    def test_with_tools_ok(self):
        ok, nudge = verifier.check("Temperatura to 47 stopni.", True, "jaka temperatura procesora?")
        self.assertTrue(ok)
        self.assertIsNone(nudge)


class TestUsage(unittest.TestCase):
    def test_log_read_summary(self):
        path = os.path.join(tempfile.mkdtemp(), "usage.jsonl")
        result = types.SimpleNamespace(route="fast", agent_result=None)
        with mock.patch.object(usage, "USAGE_FILE", path):
            usage.log_usage("która godzina", result)
            usage.log_usage("pokaż zasoby", result)
            rows = usage.read_usage()
            summary = usage.usage_summary()
        self.assertEqual(len(rows), 2)
        self.assertEqual(summary["total"], 2)
        self.assertTrue(any(r == "fast" for r, _ in summary["routes"]))

    def test_log_usage_never_raises(self):
        with mock.patch.object(usage, "USAGE_FILE", "/proc/nie/da/sie/zapisac.jsonl"):
            usage.log_usage("x", types.SimpleNamespace(route="x", agent_result=None))


class TestRemoteChain(unittest.TestCase):
    def test_run_uses_remote_support(self):
        be = remote_chain.RemoteChainBackend(chain=["fake"])
        with mock.patch.object(remote_chain.remote_support, "ask_full",
                               return_value=("Odpowiedź", "deepseek", {}, [])):
            res = be.run([{"role": "user", "content": "hej"}])
        self.assertEqual(res.text, "Odpowiedź")
        self.assertEqual(be.model, "deepseek")

    def test_run_passes_tool_calls(self):
        be = remote_chain.RemoteChainBackend(chain=["fake"])
        calls = [{"id": "c1", "type": "function",
                  "function": {"name": "system_info", "arguments": "{}"}}]
        with mock.patch.object(remote_chain.remote_support, "ask_full",
                               return_value=("", "opencode", {}, calls)):
            res = be.run([{"role": "user", "content": "hej"}], tools=[{"type": "function"}])
        self.assertEqual(res.text, "")
        self.assertEqual(res.tool_calls, calls)
        self.assertEqual(be.model, "opencode")

    def test_run_raises_when_no_provider(self):
        be = remote_chain.RemoteChainBackend(chain=["fake"])
        with mock.patch.object(remote_chain.remote_support, "ask_full", return_value=None):
            with self.assertRaises(RuntimeError):
                be.run([{"role": "user", "content": "hej"}])

    def test_ready_and_endpoint(self):
        be = remote_chain.RemoteChainBackend(chain=[])
        with mock.patch.object(remote_chain.remote_support, "provider_chain", return_value=[]):
            self.assertFalse(be.ready())
            self.assertEqual(be.endpoint(), "")


if __name__ == "__main__":
    unittest.main()
