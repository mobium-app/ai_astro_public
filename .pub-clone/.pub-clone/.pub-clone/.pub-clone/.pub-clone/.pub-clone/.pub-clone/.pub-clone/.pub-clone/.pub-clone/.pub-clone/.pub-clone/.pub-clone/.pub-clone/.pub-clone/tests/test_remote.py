"""Testy wsparcia zdalnego: parser API, łańcuch dostawców, failover, nauka offline."""

import json
import os
import tempfile
import unittest
from unittest import mock

from astro import config, remote_support
from astro.core.agent import AgentResult
from astro.memory import Memory

API_FIXTURE = """konto@example.com
\tDeepSeek \t(https://platform.deepseek.com/)
\t\tKey: sk-deep-1
\tGemini \t(https://aistudio.google.com/api-keys)
\t\tKey: AQ.gem-1
\tGrok\t(https://console.x.ai/api-keys)
\t\tKey: xai-grok-1
\tOpenRouter\t(https://openrouter.ai/workspaces/default/keys)
\t\tKey: sk-or-1
\tOpenCode [$]\t(https://opencode.ai/workspace/)
\t\tKey: sk-oc-1
"""


def _api_file():
    path = os.path.join(tempfile.mkdtemp(), "API")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(API_FIXTURE)
    return path


class TestParse(unittest.TestCase):
    def test_keys_and_order(self):
        keys = remote_support.parse_api_file(_api_file())
        self.assertEqual(keys["deepseek"], ["sk-deep-1"])
        self.assertEqual(keys["gemini"], ["AQ.gem-1"])
        self.assertEqual(keys["grok"], ["xai-grok-1"])
        self.assertEqual(keys["openrouter"], ["sk-or-1"])
        chain = remote_support.provider_chain(path=_api_file(), include_pc=False)
        # Aktywne najpierw; nieczynne (deepseek/grok) za PC, tuż przed OpenCode.
        self.assertEqual([p.label for p in chain],
                         ["gemini", "openrouter", "deepseek", "grok", "opencode"])


class TestAskFailover(unittest.TestCase):
    def test_failover_to_second(self):
        chain = [remote_support.Provider("deepseek", "https://a/v1", "m", "k1"),
                 remote_support.Provider("grok", "https://b/v1", "m", "k2")]

        def fake_post(provider, payload):
            if provider.label == "deepseek":
                raise RuntimeError("HTTP 429")
            return {"choices": [{"message": {"content": "odpowiedź grok"}}],
                    "usage": {"total_tokens": 7}}

        with mock.patch.object(remote_support, "_post", side_effect=fake_post), \
             mock.patch.object(remote_support, "_log_usage"):
            result = remote_support.ask([{"role": "user", "content": "x"}], chain=chain)
        self.assertEqual(result[0], "odpowiedź grok")
        self.assertEqual(result[1], "grok")

    def test_pc_first_dormant_after_pc_opencode_last(self):
        chain = remote_support.provider_chain(path=_api_file(), include_pc=True)
        labels = [p.label for p in chain]
        self.assertEqual(labels[0], "pc")                        # PC-Kali na czele
        self.assertLess(labels.index("pc"), labels.index("gemini"))
        self.assertEqual(labels[-1], "opencode")                 # OpenCode zawsze ostatni
        self.assertLess(labels.index("pc"), labels.index("deepseek"))
        self.assertLess(labels.index("pc"), labels.index("grok"))  # nieczynne ZA PC

    def test_models_use_deepseek_v41_flash_where_choosable(self):
        self.assertIn("deepseek-v4.1-flash", remote_support.SPEC["openrouter"][1].lower())
        self.assertIn("deepseek-v4.1-flash", remote_support.SPEC["huggingface"][1].lower())

class TestPcKeepAlive(unittest.TestCase):
    def _post_ok(self, seen):
        def fake_post(provider, payload):
            seen.update(payload)
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        return fake_post

    def test_ask_sends_keep_alive_for_pc(self):
        pc = remote_support.Provider("pc", "http://127.0.0.1:11435/v1", "bielik-11b")
        seen = {}
        with mock.patch.object(remote_support, "_pc_online", return_value=True), \
             mock.patch.object(remote_support, "_post", side_effect=self._post_ok(seen)), \
             mock.patch.object(remote_support, "_log_usage"):
            remote_support.ask([{"role": "user", "content": "x"}], chain=[pc])
        self.assertEqual(seen.get("keep_alive"), config.PC_KEEP_ALIVE)

    def test_non_pc_has_no_keep_alive(self):
        p = remote_support.Provider("gemini", "https://g/v1", "m", "k")
        seen = {}
        with mock.patch.object(remote_support, "_post", side_effect=self._post_ok(seen)), \
             mock.patch.object(remote_support, "_log_usage"):
            remote_support.ask([{"role": "user", "content": "x"}], chain=[p])
        self.assertNotIn("keep_alive", seen)

    def test_warm_pc_posts_keep_alive(self):
        captured = {}

        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return FakeResp()

        with mock.patch.object(remote_support.urllib.request, "urlopen", side_effect=fake_urlopen):
            self.assertTrue(remote_support.warm_pc(model="bielik-11b"))
        self.assertTrue(captured["url"].endswith("/api/generate"))
        self.assertEqual(captured["body"]["model"], "bielik-11b")
        self.assertEqual(captured["body"]["keep_alive"], config.PC_KEEP_ALIVE)


class TestTeacherChain(unittest.TestCase):
    def test_free_excludes_pc_and_opencode(self):
        from astro.scripts import remote_knowledge as rk
        labels = [p.label for p in rk.teacher_chain("free")]
        self.assertNotIn("pc", labels)
        self.assertNotIn("opencode", labels)

    def test_pc_only(self):
        from astro.scripts import remote_knowledge as rk
        self.assertEqual([p.label for p in rk.teacher_chain("pc")], ["pc"])

    def test_all_pc_first_no_opencode(self):
        from astro.scripts import remote_knowledge as rk
        labels = [p.label for p in rk.teacher_chain("all")]
        self.assertEqual(labels[0], "pc")
        self.assertNotIn("opencode", labels)

    def test_generator_quality_excludes_pc(self):
        # Rotacja duplikatów: generator świeżych pytań = remote_ai + OpenCode, bez PC.
        from astro.scripts import remote_knowledge as rk
        labels = [p.label for p in rk.generator_chain("quality")]
        self.assertNotIn("pc", labels)

    def test_generator_same_is_teacher_chain(self):
        from astro.scripts import remote_knowledge as rk
        self.assertIsNone(rk.generator_chain("same"))

    def test_generator_opencode_only(self):
        from astro.scripts import remote_knowledge as rk
        labels = {p.label for p in rk.generator_chain("opencode")}
        self.assertTrue(labels <= {"opencode"})


class TestTopicRotation(unittest.TestCase):
    def test_sequence_weighted_priority_and_avoids_last(self):
        import pathlib
        from astro.scripts import remote_knowledge as rk
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(rk, "_CURSOR", pathlib.Path(d) / "cursor"):
                rk._save_last_topic(0)
                seq = rk._topic_sequence()
                self.assertEqual(len(seq), 240)
                self.assertTrue(all(0 <= i < len(rk._TOPICS) for i in seq))
                # Dziedziny priorytetowe dominują (~80/20, decyzja użytkownika 2026-09-28).
                prio = sum(1 for i in seq if i < rk._N_PRIORITY)
                self.assertGreaterEqual(prio / len(seq), 0.75)
                self.assertLessEqual(prio / len(seq), 0.85)
                self.assertNotEqual(seq[0], 0)   # nowy bieg startuje ZA ostatnio użytą dziedziną

    def test_needs_web_for_current_affairs(self):
        from astro.scripts import remote_knowledge as rk
        self.assertTrue(rk._needs_web("Kto jest obecnie prezydentem Polski w 2026 roku?"))
        self.assertTrue(rk._needs_web("Jakie jest aktualne poparcie partii?"))
        self.assertFalse(rk._needs_web("Co to jest fotosynteza?"))

    def test_excluded_topics_skipped(self):
        import pathlib
        from astro.scripts import remote_knowledge as rk
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(rk, "_CURSOR", pathlib.Path(d) / "cursor"), \
                 mock.patch.dict(os.environ, {"ASTRO_EXCLUDE_TOPICS": "Docker i kontenery,polityka bie"}):
                seq = rk._topic_sequence()
                labels = [rk._TOPICS[i].lower() for i in seq]
                self.assertFalse(any("docker i kontenery" in x for x in labels))
                self.assertFalse(any("polityka bie" in x for x in labels))
                self.assertEqual(len(seq), 240)

    def test_no_four_same_priority_in_a_row(self):
        import pathlib
        from astro.scripts import remote_knowledge as rk
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(rk, "_CURSOR", pathlib.Path(d) / "cursor"):
                seq = rk._topic_sequence()
        # Regresja: blok nie może zawierać 4× tej samej dziedziny (był to błąd → wysokie `dup`).
        for i in range(len(seq) - 3):
            self.assertFalse(seq[i] == seq[i + 1] == seq[i + 2] == seq[i + 3],
                             f"4× ta sama dziedzina pod rząd na pozycji {i}")


class TestMemoryConcurrency(unittest.TestCase):
    def test_wal_and_busy_timeout(self):
        # Usługa i batch piszą równolegle: WAL + busy_timeout chronią przed „database is locked".
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        self.assertEqual(mem.con.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(mem.con.execute("PRAGMA busy_timeout").fetchone()[0], 5000)


class TestLearnedCache(unittest.TestCase):
    def _mem(self):
        return Memory(os.path.join(tempfile.mkdtemp(), "m.db"))

    def test_qkey_dedup_scales_punctuation(self):
        mem = self._mem()
        a = mem.add_learned("remote", "Co to jest fotosynteza?",
                            "Fotosynteza to proces, w którym rośliny wytwarzają cukry.",
                            source="remote:x")
        b = mem.add_learned("remote", "co, to jest fotosynteza",
                            "Inna wersja odpowiedzi na to samo pytanie.",
                            source="remote:x")
        self.assertIsNotNone(a)
        self.assertEqual(a, b)

    def test_verified_not_a_bypass_for_junk(self):
        # verified=True z sieci/legacy to nie przepustka: angielski/odmowy nadal odrzucane.
        mem = self._mem()
        self.assertIsNone(mem.add_learned(
            "web", "Karol G - Wikipedia",
            "Karol G is a Colombian singer and songwriter from Medellin.",
            source="web", verified=True))
        # źródła kuratorowane nadal przechodzą bez bramki
        self.assertIsNotNone(mem.add_learned(
            "facts", "woda", "Woda wrze w 100 stopniach Celsjusza.", source="facts",
            verified=True))

    def test_exact_normalized_hit(self):
        mem = self._mem()
        mem.add_learned("remote", "Co to jest fotosynteza?",
                        "Fotosynteza to proces, w którym rośliny wytwarzają cukry.",
                        source="remote:x")
        self.assertEqual(mem.best_learned("co to jest fotosynteza"),
                         "Fotosynteza to proces, w którym rośliny wytwarzają cukry.")
        self.assertEqual(mem.best_learned("Co to jest fotosynteza!"),
                         "Fotosynteza to proces, w którym rośliny wytwarzają cukry.")

    def test_variant_word_order(self):
        mem = self._mem()
        mem.add_learned("remote", "co to jest fotosynteza",
                        "Fotosynteza to proces, w którym rośliny wytwarzają cukry.",
                        source="remote:x")
        self.assertEqual(mem.best_learned("fotosynteza co to jest"),
                         "Fotosynteza to proces, w którym rośliny wytwarzają cukry.")

    def test_no_false_positive(self):
        mem = self._mem()
        mem.add_learned("remote", "co to jest fotosynteza",
                        "Fotosynteza to proces, w którym rośliny wytwarzają cukry.",
                        source="remote:x")
        self.assertIsNone(mem.best_learned("jak dziala silnik diesla"))


class TestLearning(unittest.TestCase):
    def test_learn_and_offline_recall(self):
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        remote_support.learn_from_remote(
            mem, "co to jest fotosynteza",
            "Fotosynteza to proces, w którym rośliny wytwarzają cukry ze światła.", source="remote:x")
        hit = mem.best_learned("co to jest fotosynteza")
        self.assertIsNotNone(hit)
        self.assertIn("Fotosynteza", hit)


class _FakeAgent:
    def __init__(self, memory):
        import types
        self.memory = memory
        self.ctx = types.SimpleNamespace(confirmer=None, memory=memory, registry=None)

    def run(self, text):
        return AgentResult("Nie rozumiem, o co chodzi.", [], 1, "agent", False)


class TestDispatchFallback(unittest.TestCase):
    def test_remote_logic_learns(self):
        from astro.core.dispatch import dispatch
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        agent = _FakeAgent(mem)
        with mock.patch.object(remote_support, "available", return_value=True), \
             mock.patch.object(remote_support, "ask",
                               return_value=("Fotosynteza to proces...", "gemini", {})):
            result = dispatch(
                "wyjaśnij krok po kroku jak działa fotosynteza", agent)
        self.assertEqual(result.route, "remote-learn")
        self.assertIn("Fotosynteza", result.reply)
        self.assertIsNotNone(mem.best_learned("jak działa fotosynteza"))

    def test_no_remote_for_commands(self):
        from astro.core.dispatch import dispatch
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        agent = _FakeAgent(mem)
        with mock.patch.object(remote_support, "available", return_value=True), \
             mock.patch.object(remote_support, "ask",
                               return_value=("nie wolno", "gemini", {})) as ask:
            result = dispatch("uruchom aktualizacje repozytoriow", agent)
        self.assertNotEqual(result.route, "remote-learn")
        self.assertFalse(ask.called)

    def test_unknown_question_recorded(self):
        # Pytanie bez odpowiedzi (remote nieosiągalny) trafia do kolejki `unknowns`.
        from astro.core.dispatch import dispatch
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        agent = _FakeAgent(mem)
        with mock.patch.object(remote_support, "available", return_value=False):
            dispatch("co to jest ksylofon termiczny", agent)
        self.assertEqual(mem.unknown_count(), 1)
        self.assertIn("ksylofon", mem.top_unknowns()[0][0])

    def test_command_not_recorded_as_unknown(self):
        from astro.core.dispatch import dispatch
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        agent = _FakeAgent(mem)
        with mock.patch.object(remote_support, "available", return_value=False):
            dispatch("zrob cos dziwnego w systemie", agent)
        self.assertEqual(mem.unknown_count(), 0)


class OpenCodeSessionTest(unittest.TestCase):
    """OpenCode Go bez `x-opencode-session` zwraca 400 (MissingSessionID) — musimy go dodać."""

    def test_ensure_session_header_added(self):
        p = remote_support.Provider("opencode", "https://opencode.ai/zen/go/v1", "m", "k")
        headers = {"Content-Type": "application/json"}
        remote_support._ensure_opencode_session(p, headers)
        self.assertIn("x-opencode-session", headers)

    def test_ensure_session_not_added_for_others(self):
        p = remote_support.Provider("groq", "https://api.groq.com/openai/v1", "m", "k")
        headers = {"Content-Type": "application/json"}
        remote_support._ensure_opencode_session(p, headers)
        self.assertNotIn("x-opencode-session", headers)

    def test_retry_on_missing_session(self):
        import io
        import urllib.error
        p = remote_support.Provider("opencode", "https://opencode.ai/zen/go/v1", "m", "k")
        p.timeout = 5
        err = urllib.error.HTTPError(
            p.endpoint(), 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"type":"MissingSessionID"}}'))
        seen = {}

        class _Resp:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        def fake_urlopen(req, timeout=None):
            hl = {k.lower(): v for k, v in req.headers.items()}
            seen["session"] = hl.get("x-opencode-session")
            if "retried" not in seen:
                seen["retried"] = True
                raise err
            return _Resp()

        with mock.patch("astro.remote_support.urllib.request.urlopen", fake_urlopen):
            data, _h = remote_support._post_full(
                p, {"model": "m", "messages": [{"role": "user", "content": "ping"}]})
        self.assertTrue(seen["retried"])
        self.assertTrue(seen["session"])  # nagłówek sesji poszedł przy ponowieniu
        self.assertEqual(data["choices"][0]["message"]["content"], "ok")


if __name__ == "__main__":
    unittest.main()
