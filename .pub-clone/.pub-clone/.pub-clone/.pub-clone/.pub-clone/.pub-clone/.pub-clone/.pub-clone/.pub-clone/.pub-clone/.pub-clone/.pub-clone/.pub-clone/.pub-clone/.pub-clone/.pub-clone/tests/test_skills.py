"""Testy skili (receptur): ładowanie, dopasowanie, wykonanie, integracja z dispatch."""

import os
import tempfile
import unittest

from astro import backends as B
from astro import config
from astro import memory
from astro.core import Agent, dispatch
from astro.safety import Confirmer
from astro.skills import Skill, list_skills_text, load_skills, match_skill, run_skill
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


def make_ctx(auto=False):
    return ToolContext(settings=config, confirmer=Confirmer(auto=auto), registry=registry)


def make_agent(mem, auto=True):
    backend = ScriptedBackend([B.BackendResult(text="nieużywane")])
    breg = B.BackendRegistry()
    breg.register(backend)
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=auto),
                      registry=registry)
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx), backend


class TestSkillRegistry(unittest.TestCase):
    def test_recipes_loaded(self):
        skills = load_skills(reload=True)
        self.assertGreaterEqual(len(skills), 10)
        for s in skills:
            self.assertTrue(s.patterns, s.name)
            self.assertTrue(s.commands, s.name)

    def test_match_common(self):
        cases = {
            "pokaż ostatnie logi usługi astro": "journal",
            "ile miejsca zajmuje ~/astro": "dir_size",
            "status repozytorium": "git_status",
            "jakie usługi działają": "running_services",
            "otwarte porty": "listening_ports",
        }
        for text, name in cases.items():
            m = match_skill(text)
            self.assertIsNotNone(m, text)
            self.assertEqual(m[0].name, name, text)

    def test_no_match_for_chat(self):
        self.assertIsNone(match_skill("opowiedz mi żart"))

    def test_no_match_generic_questions(self):
        # „ping_host" był zbyt łapczywy („sprawdź pisownię" → ping „pisownię") — regresja 2026-09-29.
        for text in ("sprawdź pisownię tego zdania", "czy lubisz kawę",
                     "co to jest Linux", "wyjaśnij mi działanie DNS"):
            self.assertIsNone(match_skill(text), text)

    def test_ping_needs_target(self):
        for text in ("ping router", "sprawdź połączenie z 8.8.8.8", "czy działa google.pl"):
            m = match_skill(text)
            self.assertIsNotNone(m, text)
            self.assertEqual(m[0].name, "ping_host", text)

    def test_match_diagnostics(self):
        cases = {
            "ile jest wolnego miejsca": "disk_usage",
            "kto jest zalogowany": "who_logged",
            "kto jest w sieci": "lan_hosts",
            "zaplanowane zadania": "cron_jobs",
            "temperatura czujników": "sensors_temp",
            "znajdź duże pliki": "find_large",
        }
        for text, name in cases.items():
            m = match_skill(text)
            self.assertIsNotNone(m, text)
            self.assertEqual(m[0].name, name, text)

    def test_list_text(self):
        blob = list_skills_text()
        self.assertIn("journal", blob)
        self.assertIn("git_status", blob)


class TestRunSkill(unittest.TestCase):
    def test_readonly_runs(self):
        skill = Skill(name="echo", commands=[{"command": "echo astro-skill-ok"}], confirm="never")
        text, ok, pending = run_skill(make_ctx(), skill, {})
        self.assertTrue(ok)
        self.assertIsNone(pending)
        self.assertIn("astro-skill-ok", text)

    def test_changing_requires_confirmation(self):
        skill = Skill(name="mkfile", commands=[{"command": "echo x > /tmp/astro-skill-test"}],
                      confirm="always")
        text, ok, pending = run_skill(make_ctx(auto=False), skill, {})
        self.assertFalse(ok)
        self.assertTrue(pending and pending.get("pending"))
        self.assertIn("Wymaga potwierdzenia", text)

    def test_blocked_command_refused(self):
        skill = Skill(name="bad", commands=[{"command": "rm -rf /"}], confirm="never")
        text, ok, _ = run_skill(make_ctx(), skill, {})
        self.assertFalse(ok)


class TestSkillTools(unittest.TestCase):
    def test_tools_registered(self):
        self.assertIn("list_skills", registry.names())
        self.assertIn("run_skill", registry.names())

    def test_run_skill_tool_refuses_changing(self):
        res = registry.execute("run_skill", {"name": "git_commit"}, make_ctx(auto=True))
        self.assertFalse(res.ok)
        self.assertIn("potwierdzenia", res.text)

    def test_run_skill_tool_readonly(self):
        res = registry.execute("run_skill",
                               {"name": "dir_size", "params": {"path": "~/astro/docs"}},
                               make_ctx())
        self.assertTrue(res.ok)


class TestSkillDispatch(unittest.TestCase):
    def test_skill_fast_path(self):
        mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        agent, backend = make_agent(mem)
        out = dispatch("stan repozytorium", agent)
        self.assertEqual(out.route, "skill")
        self.assertTrue(backend.script)  # agent nie został użyty (deterministyczny skill)

    def test_question_phrased_command_runs_skill(self):
        # Komendy zaczynające się od słowa pytającego („ile", „kto") też mają iść deterministycznie.
        mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
        agent, backend = make_agent(mem)
        out = dispatch("ile jest wolnego miejsca", agent)
        self.assertEqual(out.route, "skill")
        self.assertTrue(backend.script)


if __name__ == "__main__":
    unittest.main()
