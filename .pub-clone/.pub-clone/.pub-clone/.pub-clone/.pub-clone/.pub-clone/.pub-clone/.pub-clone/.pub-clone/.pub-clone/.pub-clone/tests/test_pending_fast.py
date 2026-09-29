"""Testy: wiedza offline (fast-path), zasilanie za zgodą, pętla Potwierdź / Anuluj."""

import os
import tempfile
import time
import unittest

from astro import backends as B
from astro import config, memory
from astro.core import Agent, dispatch, pending
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


class ScriptedBackend(B.Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def __init__(self, script=None):
        self.script = list(script or [])

    def ready(self):
        return True

    def run(self, messages, **kw):
        if self.script:
            return self.script.pop(0)
        return B.BackendResult(text="Odpowiedź modelu.")


def make_agent(auto=False):
    breg = B.BackendRegistry()
    breg.register(ScriptedBackend())
    mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=auto),
                      registry=registry, backends=breg)
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx)


class TestKnowledgeFastPath(unittest.TestCase):
    def test_fact_answered_offline(self):
        agent = make_agent()
        out = dispatch("co to jest podatek Belki", agent)
        self.assertEqual(out.route, "fast")
        self.assertIn("19", out.reply)

    def test_reasoning_question_goes_to_agent(self):
        agent = make_agent()
        out = dispatch("czym się różni TCP od UDP", agent)
        self.assertEqual(out.route, "agent")


class TestPower(unittest.TestCase):
    def test_power_requires_confirm_and_can_cancel(self):
        agent = make_agent()
        out = dispatch("wyłącz system", agent)
        self.assertEqual(out.route, "fast")
        self.assertIn("potwierdz", out.reply.lower())
        self.assertIn("anuluj", out.reply.lower())
        conf = agent.ctx.confirmer
        self.assertIsNotNone(conf.pending)
        self.assertEqual(conf.pending["kind"], "power")
        out2 = dispatch("anuluj", agent)
        self.assertEqual(out2.route, "confirm-cancel")
        self.assertIsNone(conf.pending)

    def test_service_command_is_not_power(self):
        agent = make_agent()
        out = dispatch("wyłącz usługę ssh", agent)
        self.assertIsNone(agent.ctx.confirmer.pending)
        self.assertNotEqual(out.route, "fast")

    def test_reset_and_restart_are_power(self):
        for cmd in ("reset systemu", "restart systemu", "Restaart Systemu", "restartsystem",
                    "zrestartuj system", "uruchom ponownie system"):
            agent = make_agent()
            out = dispatch(cmd, agent)
            self.assertEqual(out.route, "fast", cmd)
            conf = agent.ctx.confirmer
            self.assertIsNotNone(conf.pending, cmd)
            self.assertEqual(conf.pending["kind"], "power", cmd)


class TestPendingLoop(unittest.TestCase):
    def _seed(self, agent, kind, payload):
        agent.ctx.confirmer.pending = {"announce": "akcja", "kind": kind, "payload": payload,
                                       "ts": time.time()}

    def test_confirm_executes_system_task_steps(self):
        agent = make_agent()
        self._seed(agent, "system_task",
                   {"goal": "test", "steps": [{"command": "echo pending-ok"}]})
        out = dispatch("potwierdzam", agent)
        self.assertEqual(out.route, "confirm-run")
        self.assertIn("pending-ok", out.reply)

    def test_short_confirm_words(self):
        for word in ("tak", "Tad!", "ok", "no", "dobrze"):
            agent = make_agent()
            self._seed(agent, "system_task",
                       {"goal": "test", "steps": [{"command": "echo tak-ok"}]})
            out = dispatch(word, agent)
            self.assertEqual(out.route, "confirm-run", word)
            self.assertIn("tak-ok", out.reply)

    def test_cancel_clears_pending(self):
        agent = make_agent()
        self._seed(agent, "skill", {"skill": "backup_now", "params": {}})
        out = dispatch("anuluj", agent)
        self.assertEqual(out.route, "confirm-cancel")
        self.assertIn("Anulowano", out.reply)
        self.assertIsNone(agent.ctx.confirmer.pending)

    def test_new_command_replaces_pending(self):
        agent = make_agent()
        self._seed(agent, "skill", {"skill": "backup_now", "params": {}})
        out = dispatch("co to jest podatek Belki", agent)
        self.assertEqual(out.route, "fast")
        self.assertIsNone(agent.ctx.confirmer.pending)

    def test_gated_tool_confirm_runs(self):
        # run_script (gated) z małym skryptem w piaskownicy -> po potwierdzeniu się wykonuje.
        ws = config.WORKSPACE
        os.makedirs(ws, exist_ok=True)
        script = os.path.join(str(ws), "pending_test.sh")
        with open(script, "w") as fh:
            fh.write("#!/bin/bash\necho from-script\n")
        os.chmod(script, 0o755)
        try:
            agent = make_agent()
            first = registry.execute("run_script", {"path": "pending_test.sh"}, agent.ctx)
            self.assertFalse(first.ok)
            self.assertTrue(agent.ctx.confirmer.pending)
            self.assertEqual(agent.ctx.confirmer.pending["kind"], "run_script")
            out = dispatch("potwierdzam", agent)
            self.assertEqual(out.route, "confirm-run")
            self.assertIn("from-script", out.reply)
        finally:
            try:
                os.remove(script)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
