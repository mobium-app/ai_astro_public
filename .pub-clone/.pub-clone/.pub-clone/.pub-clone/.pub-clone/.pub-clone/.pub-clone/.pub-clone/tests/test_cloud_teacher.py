"""Testy chmurowego nauczyciela (offline; fake teacher, bez sieci)."""

import json
import os
import tempfile
import unittest

from astro import config
from astro import memory
from astro.safety import Confirmer
from astro.tools import ToolContext, registry
from astro.scripts import cloud_teacher as ct


class FakeTeacher:
    def __init__(self, script):
        self.script = list(script)
        self.providers = []

    def chat(self, messages, tools=None, fmt=None, timeout=120, temperature=0.2,
             max_tokens=None):
        return self.script.pop(0) if self.script else {"content": "koniec"}


def make_ctx():
    return ToolContext(settings=config,
                       memory=memory.Memory(os.path.join(tempfile.mkdtemp(), "t.db")),
                       confirmer=Confirmer(auto=True), registry=registry)


class TestValidation(unittest.TestCase):
    def test_parse_calls(self):
        msg = {"tool_calls": [{"function": {"name": "system_info", "arguments": "{}"}}]}
        self.assertEqual(ct.parse_calls(msg)[0]["name"], "system_info")

    def test_unknown_tool_rejected(self):
        ok, why = ct.validate_calls([{"name": "nie_ma", "args": {}}])
        self.assertFalse(ok)
        self.assertIn("nieznane", why)

    def test_missing_required_rejected(self):
        ok, why = ct.validate_calls([{"name": "read_file", "args": {}}])
        self.assertFalse(ok)
        self.assertIn("path", why)

    def test_valid_call(self):
        ok, why = ct.validate_calls([{"name": "read_file", "args": {"path": "/etc/hostname"}}])
        self.assertTrue(ok, why)

    def test_wrong_type_rejected(self):
        ok, _ = ct.validate_calls([{"name": "read_file", "args": {"path": 123}}])
        self.assertFalse(ok)


class RecordingTeacher:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, tools=None, fmt=None, timeout=120, temperature=0.2,
             max_tokens=None):
        self.calls.append([dict(m) for m in messages])
        return self.script.pop(0) if self.script else {"content": "koniec"}


class TestGenerate(unittest.TestCase):
    def test_tool_message_has_tool_call_id(self):
        teacher = RecordingTeacher([
            {"content": "", "tool_calls": [
                {"id": "abc", "function": {"name": "system_info", "arguments": "{}"}}]},
            {"content": "Sprawdzone."},
        ])
        ct.generate_trajectory("sprawdź temperaturę", teacher, registry.schemas(),
                               make_ctx(), execute=False)
        tool_msgs = [m for m in teacher.calls[1] if m.get("role") == "tool"]
        self.assertTrue(tool_msgs)
        self.assertEqual(tool_msgs[0].get("tool_call_id"), "abc")

    def test_generate_trajectory(self):
        teacher = FakeTeacher([
            {"content": "", "tool_calls": [
                {"function": {"name": "system_info", "arguments": "{}"}}]},
            {"content": "Temperatura i pamięć sprawdzone."},
        ])
        rec = ct.generate_trajectory("sprawdź temperaturę procesora", teacher,
                                     registry.schemas(), make_ctx(), execute=False)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["steps"][0]["name"], "system_info")
        self.assertIn("sprawdzon", rec["answer"].lower())

    def test_invalid_call_returns_none(self):
        teacher = FakeTeacher([{"content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": "{}"}}]}])
        rec = ct.generate_trajectory("x", teacher, registry.schemas(), make_ctx(),
                                     execute=False)
        self.assertIsNone(rec)


class TestJudge(unittest.TestCase):
    def test_judge_ok(self):
        teacher = FakeTeacher([{"content": json.dumps({"score": 5, "ok": True, "problems": []})}])
        ok, score, _ = ct.judge("q", [{"name": "system_info", "args": {}}], "a", teacher)
        self.assertTrue(ok)
        self.assertEqual(score, 5)

    def test_judge_bad_json(self):
        ok, score, note = ct.judge("q", [], "a", FakeTeacher([{"content": "nie json"}]))
        self.assertFalse(ok)
        self.assertIn("błąd", note)


class TestProviders(unittest.TestCase):
    def test_json_providers(self):
        raw = json.dumps([{"url": "https://x/v1", "model": "m", "key": "k", "label": "lab"}])
        provs = ct._json_providers(raw)
        self.assertEqual(provs[0].label, "lab")

    def test_api_file_parse(self):
        import tempfile as tf
        path = os.path.join(tf.mkdtemp(), "API")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("konto@example.com\n"
                     "\tDeepSeek \t(https://platform.deepseek.com/)\n"
                     "\t\tKey: sk-deep-1\n"
                     "\tGemini \t(https://aistudio.google.com/)\n"
                     "\t\tKey: AQ.gem-1\n"
                     "\tGrok\t(https://console.x.ai/)\n"
                     "\t\tKey: xai-grok-1\n")
        provs = ct._atena_providers(path)
        labels = [p.label for p in provs]
        # Aktywne (gemini) najpierw; nieczynne (deepseek/grok) dalej.
        self.assertEqual(labels, ["gemini#1", "deepseek#1", "grok#1"])
        self.assertEqual(provs[0].url,
                         "https://generativelanguage.googleapis.com/v1beta/openai")

    def test_failover(self):
        calls = {"n": 0}

        def flaky(provider, *a, **k):
            calls["n"] += 1
            if provider.label == "bad":
                raise RuntimeError("429")
            return {"content": "ok"}

        orig = ct._chat_one
        ct._chat_one = flaky
        try:
            t = ct.Teacher([ct.Provider("u", "m", "k", "bad"),
                            ct.Provider("u", "m", "k", "good")], verbose=False)
            msg = t.chat([{"role": "user", "content": "x"}])
        finally:
            ct._chat_one = orig
        self.assertEqual(msg["content"], "ok")
        self.assertEqual(calls["n"], 2)


class TestStore(unittest.TestCase):
    def test_store_and_retrieve(self):
        mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        rec = {"goal": "sprawdź temperaturę procesora", "steps": [
            {"name": "system_info", "args": {}, "ok": True, "result": "46C"}],
            "answer": "Temperatura to 46C.", "result": "system_info"}
        ct.store(mem, rec, score=5)
        self.assertEqual(mem.trajectory_count("agent"), 1)
        hits = mem.similar_trajectories("sprawdź temperaturę procesora")
        self.assertEqual(hits[0]["answer"], "Temperatura to 46C.")


class TestContentCalls(unittest.TestCase):
    def test_json_object_in_content(self):
        calls = ct.parse_calls({"content": '{"name": "system_info", "arguments": {}}'})
        self.assertEqual(calls[0]["name"], "system_info")

    def test_json_array_in_content(self):
        calls = ct.parse_calls({"content": '[{"name":"read_file","arguments":{"path":"/etc/hosts"}}]'})
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["args"]["path"], "/etc/hosts")

    def test_tool_calls_wrapper_in_content(self):
        msg = {"content": '{"tool_calls": [{"function": {"name": "system_info", '
                          '"arguments": "{}"}}]}'}
        self.assertEqual(ct.parse_calls(msg)[0]["name"], "system_info")

    def test_prose_not_parsed(self):
        self.assertEqual(ct.parse_calls({"content": "Temperatura to 46 stopni."}), [])

    def test_unknown_name_ignored(self):
        self.assertEqual(ct.parse_calls({"content": '{"name": "nope", "arguments": {}}'}), [])

    def test_dsml_invoke(self):
        text = ('<|DSML|invoke name="run_command"><|DSML|parameter name="command">df -h'
                '</|DSML|parameter></|DSML|invoke>')
        calls = ct.parse_calls({"content": text})
        self.assertEqual(calls[0]["name"], "run_command")
        self.assertEqual(calls[0]["args"]["command"], "df -h")


class TestNudge(unittest.TestCase):
    def test_invalid_call_then_fixed(self):
        teacher = RecordingTeacher([
            {"content": "", "tool_calls": [
                {"function": {"name": "read_file", "arguments": "{}"}}]},
            {"content": "", "tool_calls": [
                {"function": {"name": "system_info", "arguments": "{}"}}]},
            {"content": "Gotowe, sprawdzone."},
        ])
        rec = ct.generate_trajectory("sprawdź temperaturę", teacher, registry.schemas(),
                                     make_ctx(), execute=False)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["steps"][0]["name"], "system_info")

    def test_content_call_recovered(self):
        teacher = FakeTeacher([
            {"content": '{"name": "system_info", "arguments": {}}'},
            {"content": "Sprawdzone."},
        ])
        rec = ct.generate_trajectory("sprawdź temperaturę", teacher, registry.schemas(),
                                     make_ctx(), execute=False)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["steps"][0]["name"], "system_info")

    def test_no_calls_no_steps_returns_none(self):
        rec = ct.generate_trajectory("x", FakeTeacher([{"content": "nie wiem"}]), registry.schemas(),
                                     make_ctx(), execute=False)
        self.assertIsNone(rec)


class TestCommandSeeds(unittest.TestCase):
    def test_real_commands_mapped(self):
        hints = ct.command_seed_hints()
        # Plik must-have ma teraz poprawne polskie znaki („wyłącz system").
        self.assertIn("wyłącz system", hints)
        self.assertEqual(hints["wyłącz system"], ["system_power"])
        self.assertTrue(all(v for v in hints.values()))

    def test_category_not_a_command(self):
        self.assertNotIn("KALKULATOR", ct.command_seed_hints())

    def test_pronunciation_hint_stripped(self):
        phrases = ct._parse_command_phrases()
        # Wskazówka fonetyczna w nawiasie usunięta; zostaje „podaj aj pi" (fonetyczny zapis IP).
        self.assertNotIn("podaj aj pi (aj pi fonetycznie)", phrases)
        self.assertTrue(any("podaj" in p and "aj pi" in p for p in phrases), phrases)


if __name__ == "__main__":
    unittest.main()
