"""Testy pamięci roboczej rozmowy (P1): sesja + wstrzykiwanie historii tylko do czatu."""

import os
import tempfile
import time
import unittest
from unittest import mock

from astro import backends as B
from astro import config
from astro import memory
from astro.core import Agent, dispatch
from astro.core.context import build_context
from astro.core.session import Session
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


class CaptureBackend(B.Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def __init__(self, reply="Odpowiedź."):
        self.reply = reply
        self.calls = []

    def ready(self):
        return True

    def run(self, messages, **kw):
        self.calls.append([dict(m) for m in messages])
        return B.BackendResult(text=self.reply)


def make_agent(reply="Odpowiedź."):
    backend = CaptureBackend(reply)
    breg = B.BackendRegistry()
    breg.register(backend)
    mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=True),
                      registry=registry)
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx), backend, mem


def _contents(backend):
    return [(m.get("role"), m.get("content")) for m in backend.calls[0]]


class TestSessionUnit(unittest.TestCase):
    def test_order_and_limit(self):
        s = Session(max_turns=3, gap_s=1000, max_chars=10 ** 6)
        for i in range(5):
            s.record(f"u{i}", f"a{i}", now=100 + i)
        self.assertEqual([t["user"] for t in s.turns], ["u2", "u3", "u4"])
        hist = s.history(now=104)
        self.assertEqual(hist[0], {"role": "user", "content": "u2"})
        self.assertEqual(hist[-1], {"role": "assistant", "content": "a4"})

    def test_gap_resets_session(self):
        s = Session(max_turns=5, gap_s=10, max_chars=10 ** 6)
        s.record("a", "b", now=1000)
        s.record("c", "d", now=1005)
        self.assertEqual(len(s.turns), 2)
        s.record("e", "f", now=1100)
        self.assertEqual([t["user"] for t in s.turns], ["e"])
        self.assertEqual(s.history(now=1100)[0]["content"], "e")

    def test_expired_history_empty(self):
        s = Session(max_turns=5, gap_s=10, max_chars=10 ** 6)
        s.record("a", "b", now=1000)
        self.assertEqual(s.history(now=2000), [])

    def test_char_budget_keeps_newest(self):
        s = Session(max_turns=10, gap_s=10 ** 6, max_chars=12)
        s.record("stareeeee", "odpowiedz1", now=100)
        s.record("n1", "n2", now=101)
        s.record("ostatnie", "ok", now=102)
        hist = s.history(now=102)
        joined = " ".join(m["content"] for m in hist)
        self.assertIn("ostatnie", joined)
        self.assertNotIn("stareeeee", joined)

    def test_clear(self):
        s = Session()
        s.record("a", "b", now=1)
        s.clear()
        self.assertEqual(s.turns, [])
        self.assertEqual(s.history(now=1), [])


class TestSessionPersistence(unittest.TestCase):
    def _mem(self):
        return memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))

    def test_survives_restart(self):
        mem = self._mem()
        s1 = Session(max_turns=4, gap_s=10 ** 6, store=mem)
        s1.record("lubisz ze mną pracować", "tak, bardzo")
        s1.record("a jak bardzo", "ogromnie")
        s2 = Session(max_turns=4, gap_s=10 ** 6, store=mem)
        self.assertEqual([t["user"] for t in s2.turns],
                         ["lubisz ze mną pracować", "a jak bardzo"])
        hist = s2.history()
        self.assertEqual(hist[0], {"role": "user", "content": "lubisz ze mną pracować"})

    def test_gap_starts_fresh(self):
        mem = self._mem()
        s1 = Session(max_turns=4, gap_s=10 ** 6, store=mem)
        s1.record("stary temat", "ok", now=time.time() - 10 ** 6)
        s2 = Session(max_turns=4, gap_s=10, store=mem)
        self.assertEqual(s2.turns, [])

    def test_forget_clears_store(self):
        mem = self._mem()
        s1 = Session(max_turns=4, gap_s=10 ** 6, store=mem)
        s1.record("temat", "ok")
        s1.clear(forget=True)
        s2 = Session(max_turns=4, gap_s=10 ** 6, store=mem)
        self.assertEqual(s2.turns, [])


class TestSessionSummary(unittest.TestCase):
    def test_old_turns_folded_into_summary(self):
        s = Session(max_turns=2, gap_s=10 ** 6, max_chars=10 ** 6,
                    summary_max_chars=1000, store=None)
        s.record("temat pierwszy", "a1", now=1)
        s.record("temat drugi", "a2", now=2)
        s.record("temat trzeci", "a3", now=3)
        s.record("temat czwarty", "a4", now=4)
        self.assertEqual([t["user"] for t in s.turns], ["temat trzeci", "temat czwarty"])
        self.assertIn("temat pierwszy", s.summary)
        self.assertIn("temat drugi", s.summary)

    def test_summary_in_build_context(self):
        msgs = build_context("a co dalej", memory.Memory(":memory:"),
                             history=[{"role": "assistant", "content": "ok"}],
                             summary="rozmowa o pracy")
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertIn("Wcześniejszy wątek rozmowy: rozmowa o pracy", system_text)

    def test_summary_absent_without_history(self):
        msgs = build_context("cześć", memory.Memory(":memory:"), summary="stary wątek")
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertNotIn("stary wątek", system_text)


class TestBuildContextHistory(unittest.TestCase):
    def test_history_between_system_and_user(self):
        mem = memory.Memory(":memory:")
        msgs = build_context("a jak bardzo", mem, history=[
            {"role": "user", "content": "lubisz ze mną pracować"},
            {"role": "assistant", "content": "tak, bardzo"},
        ])
        self.assertEqual(msgs[-1], {"role": "user", "content": "a jak bardzo"})
        self.assertIn(("assistant", "tak, bardzo"), [(m["role"], m["content"]) for m in msgs])
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("Jesteś ASTRO", msgs[0]["content"])

    def test_no_history_backward_compatible(self):
        mem = memory.Memory(":memory:")
        msgs = build_context("cześć", mem)
        self.assertEqual(msgs[-1], {"role": "user", "content": "cześć"})


class TestAgentHistoryGating(unittest.TestCase):
    def test_chat_gets_history(self):
        agent, backend, _mem = make_agent()
        agent.session.record("lubisz ze mną pracować", "tak, bardzo")
        agent.run("a jak bardzo")
        self.assertIn(("assistant", "tak, bardzo"), _contents(backend))

    def test_command_excludes_history(self):
        agent, backend, _mem = make_agent()
        agent.session.record("lubisz ze mną pracować", "tak, bardzo")
        agent.run("sprawdź temperaturę procesora")
        self.assertNotIn("tak, bardzo", [c for _r, c in _contents(backend)])

    def test_disabled_flag(self):
        agent, backend, _mem = make_agent()
        agent.session.record("lubisz ze mną pracować", "tak, bardzo")
        with mock.patch.object(config, "SESSION_ENABLED", False):
            agent.run("a jak bardzo")
        self.assertNotIn("tak, bardzo", [c for _r, c in _contents(backend)])


class TestDispatchRecords(unittest.TestCase):
    def test_fast_route_records_turn(self):
        agent, _backend, _mem = make_agent()
        out = dispatch("co to jest podatek Belki", agent)
        self.assertEqual(out.route, "fast")
        self.assertEqual(len(agent.session.turns), 1)
        self.assertEqual(agent.session.turns[0]["user"], "co to jest podatek Belki")
        self.assertTrue(agent.session.turns[0]["assistant"])


class TestFollowupSkipsFastKnowledge(unittest.TestCase):
    def test_is_followup(self):
        from astro.core.fast_tools import is_followup
        self.assertTrue(is_followup("a jak bardzo?"))
        self.assertTrue(is_followup("i co dalej"))
        self.assertTrue(is_followup("a dlaczego?"))
        self.assertFalse(is_followup("co to jest podatek Belki"))
        self.assertFalse(is_followup("a co to jest podatek Belki"))
        self.assertFalse(is_followup("powiedz mi o systemie plików"))

    def test_followup_not_answered_from_learned(self):
        from astro.core import fast_tools
        agent, _backend, mem = make_agent()
        mem.best_learned = lambda text: "OGOLNIK"
        self.assertIsNone(fast_tools.try_fast("a jak bardzo?", agent.ctx))
        self.assertEqual(fast_tools.try_fast("czym jest blibblob", agent.ctx), "OGOLNIK")


if __name__ == "__main__":
    unittest.main()
