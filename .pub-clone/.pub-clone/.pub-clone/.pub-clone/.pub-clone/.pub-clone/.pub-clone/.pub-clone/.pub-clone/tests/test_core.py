"""Testy rdzenia agenta: pętla, fast-tools, dyspozycja, brama E1."""

import os
import tempfile
import unittest

from astro import config
from astro import backends as B
from astro import memory
from astro.core import Agent, dispatch
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


class ScriptedBackend(B.Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def __init__(self, script):
        self.script = list(script)

    def ready(self):
        return True

    def run(self, messages, **kw):
        if self.script:
            return self.script.pop(0)
        return B.BackendResult(text="koniec")


def tool_call(name, **args):
    return B.BackendResult(text="", tool_calls=[{"function": {"name": name, "arguments": args}}])


def make_agent(script, auto=True):
    backend = ScriptedBackend(script)
    breg = B.BackendRegistry()
    breg.register(backend)
    mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=auto),
                      registry=registry)
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx), backend, mem


class TestAgentLoop(unittest.TestCase):
    def test_uses_tool_then_answers(self):
        script = [tool_call("system_info"),
                  B.BackendResult(text="Temperatura i dysk są sprawdzone.")]
        agent, backend, mem = make_agent(script)
        result = agent.run("sprawdź temperaturę procesora i wolne miejsce na dysku")
        self.assertTrue(result.used_tools)
        self.assertEqual(result.route, "agent")
        self.assertEqual(result.tool_calls[0]["name"], "system_info")
        self.assertIn("sprawdzone", result.reply)
        self.assertEqual(mem.trajectory_count("episode"), 1)
        self.assertEqual(mem.trajectory_count("agent"), 1)
        agent_rows = mem.trajectories("agent")
        self.assertEqual(agent_rows[0]["steps_json"].count("system_info"), 1)

    def test_verifier_nudges_without_tools(self):
        agent, backend, mem = make_agent([B.BackendResult(text="Nie mam danych.")])
        result = agent.run("sprawdź temperaturę procesora")
        self.assertFalse(result.used_tools)
        self.assertGreaterEqual(result.steps, 2)

    def test_ask_user_route(self):
        script = [tool_call("ask_user", question="Jaki jest twój adres?")]
        agent, backend, mem = make_agent(script)
        result = agent.run("znajdź najbliższy paczkomat")
        self.assertEqual(result.route, "ask_user")
        self.assertIn("adres", result.reply)


class TestDispatch(unittest.TestCase):
    def test_fast_path(self):
        agent, backend, mem = make_agent([B.BackendResult(text="nieużywane")])
        out = dispatch("sprawdź temperaturę procesora i wolne miejsce na dysku", agent)
        self.assertEqual(out.route, "fast")
        self.assertIn("°C", out.reply)
        self.assertIn("GB", out.reply)
        self.assertEqual(backend.script, [B.BackendResult(text="nieużywane")])

    def test_question_goes_to_agent(self):
        agent, backend, mem = make_agent([B.BackendResult(text="Odpowiedź modelu.")])
        out = dispatch("czym się różni TCP od UDP", agent)
        self.assertEqual(out.route, "agent")
        self.assertEqual(out.reply, "Odpowiedź modelu.")

    def test_fact_question_answered_offline(self):
        agent, backend, mem = make_agent([B.BackendResult(text="Odpowiedź modelu.")])
        out = dispatch("co to jest podatek Belki", agent)
        self.assertEqual(out.route, "fast")
        self.assertIn("19", out.reply)
        self.assertEqual(backend.script, [B.BackendResult(text="Odpowiedź modelu.")])


class TestE1Gate(unittest.TestCase):
    """Bramka E1: zadanie 'temperatura + wolne miejsce' narzędziami na CPU (bez PC, bez głosu)."""

    def test_gate_task_via_tools(self):
        script = [tool_call("system_info"),
                  B.BackendResult(text="Sprawdzone.")]
        agent, backend, mem = make_agent(script)
        result = agent.run("sprawdź temperaturę procesora i wolne miejsce na dysku")
        self.assertTrue(result.used_tools)
        self.assertEqual(backend.name, "cpu")
        self.assertIn("system_info", [c["name"] for c in result.tool_calls])
        self.assertTrue(all(c["ok"] for c in result.tool_calls))


if __name__ == "__main__":
    unittest.main()
