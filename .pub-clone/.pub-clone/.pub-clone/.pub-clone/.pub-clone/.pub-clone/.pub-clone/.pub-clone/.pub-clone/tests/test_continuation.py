"""P3: deterministyczny rewrite kontynuacji + wpięcie w `dispatch`."""

import os
import tempfile
import unittest

from astro import backends as B
from astro import config
from astro import memory
from astro.core import Agent, dispatch
from astro.core.continuation import rewrite_continuation as R
from astro.core.fast_tools import FOLLOWUP_LEAD
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
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx), backend


class TestRewrite(unittest.TestCase):
    def test_merges_degree_followup(self):
        out = R("a jak bardzo?", "lubisz ze mną pracować?", FOLLOWUP_LEAD)
        self.assertEqual(out, "jak bardzo lubisz ze mną pracować?")

    def test_merges_reason_followup(self):
        out = R("a dlaczego?", "podatek Belki wynosi 19 procent", FOLLOWUP_LEAD)
        self.assertEqual(out, "dlaczego podatek Belki wynosi 19 procent")

    def test_ignores_own_topic(self):
        self.assertIsNone(R("a jak bardzo lubisz zieloną herbatę?",
                            "lubisz ze mną pracować", FOLLOWUP_LEAD))
        self.assertIsNone(R("co to jest fotosynteza", "cokolwiek", FOLLOWUP_LEAD))

    def test_ignores_non_lead(self):
        self.assertIsNone(R("sprawdź temperaturę", "cokolwiek", FOLLOWUP_LEAD))

    def test_bare_pronoun(self):
        out = R("a to?", "to jest fotosynteza", FOLLOWUP_LEAD)
        self.assertEqual(out, "co z jest fotosynteza")
        self.assertIsNone(R("a", "lubisz ze mną pracować", FOLLOWUP_LEAD))


class TestDispatchContinuation(unittest.TestCase):
    def test_dispatch_rewrites_using_session(self):
        agent, backend = make_agent()
        agent.session.record("lubisz ze mną pracować?", "tak, bardzo")
        dispatch("a jak bardzo?", agent)
        user_msgs = [m["content"] for m in backend.calls[0] if m["role"] == "user"]
        self.assertIn("jak bardzo lubisz ze mną pracować?", user_msgs)

    def test_dispatch_keeps_command_text(self):
        agent, backend = make_agent()
        agent.session.record("lubisz ze mną pracować?", "tak, bardzo")
        out = dispatch("sprawdź temperaturę procesora", agent)
        self.assertEqual(out.route, "fast")


if __name__ == "__main__":
    unittest.main()
