"""Testy E6: generator trajektorii tool-calling, dataset, bramka."""

import unittest
from unittest import mock

from astro.tools import registry
from astro.scripts import build_dataset, e6_gate, toolcall_gen


class TestToolcallGen(unittest.TestCase):
    def test_scenarios_reference_real_tools(self):
        names = set(registry.names())
        for sc in toolcall_gen.SCENARIOS:
            self.assertIn(sc["tool"], names, sc["tool"])
            self.assertTrue(sc["answer"], sc["tool"])
        for ch in toolcall_gen.CHAINS:
            self.assertGreaterEqual(len(ch["steps"]), 2)
            for st in ch["steps"]:
                self.assertIn(st["tool"], names, st["tool"])

    def test_every_tool_has_scenario(self):
        covered = {sc["tool"] for sc in toolcall_gen.SCENARIOS}
        for ch in toolcall_gen.CHAINS:
            covered |= {st["tool"] for st in ch["steps"]}
        missing = set(registry.visible_names()) - covered
        self.assertEqual(missing, set(), f"brak scenariuszy dla: {sorted(missing)}")


class TestDataset(unittest.TestCase):
    def test_tool_record_builds_tool_calls(self):
        row = {"goal": "sprawdź temperaturę", "steps_json": '[{"name": "system_info", '
               '"args": {}, "ok": true, "result": "46C"}]', "answer": "Temperatura to 46C.",
               "source": "toolcall_gen", "kind": "agent"}
        rec = build_dataset.record_from_trajectory(row)
        self.assertIsNotNone(rec)
        self.assertTrue(rec["tools"])
        roles = [m["role"] for m in rec["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        self.assertEqual(rec["messages"][2]["tool_calls"][0]["function"]["name"], "system_info")

    def test_chat_record_without_steps(self):
        row = {"goal": "co to jest Linux", "steps_json": None, "answer": "Linux to system.",
               "source": "episode", "kind": "episode"}
        rec = build_dataset.record_from_trajectory(row)
        self.assertEqual(rec["tools"], [])
        self.assertEqual([m["role"] for m in rec["messages"]], ["system", "user", "assistant"])

    def test_bad_answer_filtered(self):
        row = {"goal": "x", "steps_json": None, "answer": "nie udało mi się",
               "source": "episode", "kind": "episode"}
        self.assertIsNone(build_dataset.record_from_trajectory(row))

    def test_dedup(self):
        rec = {"messages": [{"role": "system", "content": "s"},
                            {"role": "user", "content": "q"},
                            {"role": "assistant", "content": "a"}], "tools": []}
        self.assertEqual(len(build_dataset.dedup([rec, dict(rec)])), 1)


class TestE6Gate(unittest.TestCase):
    def test_tool_tests_reference_real_tools(self):
        names = set(registry.names())
        for _q, expect, _chk in e6_gate.TOOL_TESTS:
            for name in expect:
                self.assertIn(name, names, name)
                self.assertIn(name, e6_gate.FAKE_RESULTS)

    def test_chain_tests_reference_real_tools(self):
        names = set(registry.names())
        for _q, expect in e6_gate.CHAIN_TESTS:
            for name in expect:
                self.assertIn(name, names, name)
                self.assertIn(name, e6_gate.FAKE_RESULTS)

    def test_calls_parsing(self):
        msg = {"tool_calls": [{"function": {"name": "system_info", "arguments": {}}}]}
        calls = e6_gate._calls(msg)
        self.assertEqual(calls[0]["name"], "system_info")

    def test_text_tool_calls_parsed(self):
        msg = {"content": "[TOOL system_info {}]"}
        calls = e6_gate._calls(msg)
        self.assertEqual(calls[0]["name"], "system_info")


def _fake_chat(name, args=None, content=""):
    def _fn(_url, _model, _msgs, **kw):
        if name:
            return {"message": {"content": content,
                                "tool_calls": [{"function": {"name": name,
                                                             "arguments": args or {}}}]}}
        return {"message": {"content": content}}
    return _fn


class TestGateScoring(unittest.TestCase):
    def test_tool_pass_and_fail(self):
        tests = [("przeczytaj /etc/hostname", ["read_file"],
                  lambda a: "hostname" in str(a.get("path", "")))]
        with mock.patch.object(e6_gate, "_chat", _fake_chat("read_file", {"path": "/etc/hostname"})):
            ok, total, _ = e6_gate.test_tools("u", "m", tests, 3, registry.schemas())
        self.assertEqual((ok, total), (1, 1))
        with mock.patch.object(e6_gate, "_chat", _fake_chat("run_command", {"command": "df"})):
            ok, total, _ = e6_gate.test_tools("u", "m", tests, 3, registry.schemas())
        self.assertEqual((ok, total), (0, 1))

    def test_chat_pass_and_fail(self):
        with mock.patch.object(e6_gate, "_chat", _fake_chat(None, content="Jestem ASTRO, działam lokalnie.")):
            ok, total, _ = e6_gate.test_chat("u", "m", ["Kim jesteś?"], 3)
        self.assertEqual((ok, total), (1, 1))
        with mock.patch.object(e6_gate, "_chat", _fake_chat(None, content='{"tool": "x"}')):
            ok, total, _ = e6_gate.test_chat("u", "m", ["Kim jesteś?"], 3)
        self.assertEqual((ok, total), (0, 1))

    def test_chain_requires_two_tools_and_final(self):
        state = {"n": 0}

        def _fn(_url, _model, _msgs, **kw):
            state["n"] += 1
            if state["n"] == 1:
                return {"message": {"content": "", "tool_calls": [
                    {"function": {"name": "system_info", "arguments": {}}}]}}
            if state["n"] == 2:
                return {"message": {"content": "", "tool_calls": [
                    {"function": {"name": "web_search", "arguments": {"query": "x"}}}]}}
            return {"message": {"content": "Gotowe, sprawdzone."}}

        with mock.patch.object(e6_gate, "_chat", _fn):
            ok, total, _ = e6_gate.test_chains(
                "u", "m", [("q", {"system_info", "web_search"})], 3, registry.schemas())
        self.assertEqual((ok, total), (1, 1))


if __name__ == "__main__":
    unittest.main()
