"""Testy nauki w runtime (A): retrieval trajektorii, few-shot, cache planów (CBR)."""

import os
import tempfile
import unittest
from unittest import mock

from astro import backends as B
from astro import config
from astro import memory
from astro.core import Agent, dispatch
from astro.core.context import build_context, tool_example_text
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


def make_tmp_memory():
    return memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))


class FakeEmbedder:
    """Deterministyczny pseudo-embedder (bez sieci) do testów retrieval wektorowego."""

    def __init__(self, dim=16):
        self.dim = dim

    def __call__(self, text):
        vec = [0.0] * self.dim
        for tok in str(text).lower().split():
            vec[hash(tok) % self.dim] += 1.0
        return vec


def make_embed_memory():
    return memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"), embedder=FakeEmbedder())


def store_agent_traj(mem, goal, steps, answer="Gotowe."):
    mem.add_trajectory(kind="agent", goal=goal, steps=steps, result=steps[0]["name"],
                       answer=answer, source="test", ok=True)


class ScriptedBackend(B.Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def ready(self):
        return True

    def run(self, messages, **kw):
        self.seen.append(messages)
        if self.script:
            return self.script.pop(0)
        return B.BackendResult(text="koniec")


def make_agent(script, mem, auto=True):
    backend = ScriptedBackend(script)
    breg = B.BackendRegistry()
    breg.register(backend)
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=auto),
                      registry=registry)
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx), backend


class TestSimilarTrajectories(unittest.TestCase):
    def test_retrieves_matching(self):
        mem = make_tmp_memory()
        store_agent_traj(mem, "sprawdź temperaturę procesora i wolne miejsce na dysku",
                         [{"name": "system_info", "args": {}, "ok": True, "result": "46C"}])
        hits = mem.similar_trajectories("sprawdź temperaturę procesora", k=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["steps"][0]["name"], "system_info")

    def test_ignores_dissimilar_and_failed(self):
        mem = make_tmp_memory()
        store_agent_traj(mem, "pokaż stronę man rsync",
                         [{"name": "man_page", "args": {"name": "rsync"}, "ok": True,
                           "result": "RSYNC(1)"}])
        self.assertEqual(mem.similar_trajectories("jaka jest pogoda w Poznaniu"), [])
        mem.add_trajectory(kind="agent", goal="zepsuło się", steps=[{"name": "x", "args": {}}],
                           result="x", answer="błąd", source="test", ok=False)
        self.assertEqual(mem.similar_trajectories("zepsuło się"), [])


class TestContextFewShot(unittest.TestCase):
    def test_example_injected(self):
        mem = make_tmp_memory()
        goal = "Pokaż stronę man polecenia rsync"
        store_agent_traj(mem, goal, [{"name": "man_page", "args": {"name": "rsync"},
                                      "ok": True, "result": "RSYNC(1) synopsis"}])
        messages = build_context(goal, mem)
        blob = " ".join(m["content"] for m in messages)
        # A1: pokazujemy tylko WZORZEC WYWOŁANIA (bez wyniku), by model wołał narzędzie TERAZ.
        self.assertIn("WZORCE WYWOŁAŃ", blob)
        self.assertIn("man_page", blob)
        self.assertNotIn("RSYNC(1) synopsis", blob)

    def test_no_example_for_unrelated(self):
        mem = make_tmp_memory()
        store_agent_traj(mem, "Pokaż stronę man polecenia rsync",
                         [{"name": "man_page", "args": {"name": "rsync"}, "ok": True,
                           "result": "RSYNC(1)"}])
        messages = build_context("opowiedz mi żart", mem)
        self.assertNotIn("WZORCE WYWOŁAŃ", " ".join(m["content"] for m in messages))

    def test_agent_uses_config_fewshot(self):
        mem = make_tmp_memory()
        goal = "Pokaż stronę man polecenia rsync"
        store_agent_traj(mem, goal, [{"name": "man_page", "args": {"name": "rsync"},
                                      "ok": True, "result": "RSYNC(1) synopsis"}])
        agent, backend = make_agent([B.BackendResult(text="ok")], mem)
        with mock.patch.object(config, "FEWSHOT", 2):
            agent.run(goal)
        blob = " ".join(m.get("content", "") for m in backend.seen[0])
        self.assertIn("man_page", blob)


class TestFewShotFormat(unittest.TestCase):
    def test_same_tool_only_and_single_call(self):
        trajs = [
            {"goal": "a", "steps": [{"name": "read_file", "args": {"path": "/etc/hostname"}},
                                    {"name": "web_search", "args": {"query": "hostname"}}]},
            {"goal": "b", "steps": [{"name": "man_page", "args": {"name": "rsync"}}]},
        ]
        text = tool_example_text(trajs)
        # hint (pierwsze trafienie) = read_file -> tylko to narzędzie i tylko pierwsze wywołanie
        self.assertIn("read_file", text)
        self.assertNotIn("web_search", text)
        self.assertNotIn("man_page", text)

    def test_keeps_all_same_tool_examples(self):
        trajs = [
            {"goal": "a", "steps": [{"name": "list_dir", "args": {"path": "/etc"}}]},
            {"goal": "b", "steps": [{"name": "list_dir", "args": {"path": "/home"}},
                                    {"name": "run_command", "args": {"command": "ls"}}]},
        ]
        text = tool_example_text(trajs)
        self.assertIn("/etc", text)
        self.assertIn("/home", text)
        self.assertNotIn("run_command", text)

    def test_empty_when_no_steps(self):
        self.assertEqual(tool_example_text([{"goal": "x", "steps": []}]), "")


class TestTrajectoryVectors(unittest.TestCase):
    def test_vector_persisted_and_retrieved(self):
        mem = make_embed_memory()
        store_agent_traj(mem, "sprawdź temperaturę procesora",
                         [{"name": "system_info", "args": {}, "ok": True, "result": "46C"}])
        row = mem.con.execute("SELECT COUNT(*) c FROM trajectory_vectors").fetchone()["c"]
        self.assertEqual(row, 1)
        hits = mem.similar_trajectories("sprawdź temperaturę procesora", k=1, min_score=0.5)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["steps"][0]["name"], "system_info")

    def test_backfill_fills_missing(self):
        mem = make_embed_memory()
        store_agent_traj(mem, "policz pliki",
                         [{"name": "run_command", "args": {"command": "ls"}, "ok": True,
                           "result": "x"}])
        mem.con.execute("DELETE FROM trajectory_vectors")
        mem.con.commit()
        self.assertEqual(mem.backfill_trajectory_vectors(), 1)
        row = mem.con.execute("SELECT COUNT(*) c FROM trajectory_vectors").fetchone()["c"]
        self.assertEqual(row, 1)


class TestPlanCache(unittest.TestCase):
    def test_dispatch_uses_cached_plan(self):
        mem = make_tmp_memory()
        goal = "zainstaluj i skonfiguruj nginx na serwerze"
        mem.record_plan_result(goal, [{"command": "apt-get install -y nginx"}], success=True)
        agent, backend = make_agent([B.BackendResult(text="Zrobione.")], mem)
        # Hermetyczność CI (2026-10-03): obrazy CI mają nginx preinstalowany, a walidacja
        # odrzuca plan „zainstaluj X", gdy X już istnieje — mockujemy detekcję pakietu.
        with mock.patch("astro.safety.plans.already_installed", return_value=False):
            out = dispatch(goal, agent, use_plan=True)
        self.assertEqual(out.route, "plan-cache")
        self.assertIn("nginx", out.reply)

    def test_planner_gets_hint(self):
        from astro.core import planner
        backend = ScriptedBackend(
            [B.BackendResult(text='{"steps":[{"command":"apt-get install -y nginx"}]}')])
        breg = B.BackendRegistry()
        breg.register(backend)
        steps = planner.goal_to_steps("zainstaluj nginx", breg,
                                      hint="apt-get install -y nginx")
        self.assertEqual(steps[0]["command"], "apt-get install -y nginx")
        sent = backend.seen[0][-1]["content"]
        self.assertIn("Sprawdzony wcześniej plan", sent)


class TestLearningStats(unittest.TestCase):
    def test_stats(self):
        mem = make_tmp_memory()
        store_agent_traj(mem, "q", [{"name": "system_info", "args": {}, "ok": True,
                                     "result": "r"}])
        stats = mem.learning_stats()
        self.assertEqual(stats["agent_trajectories"], 1)
        self.assertIn("plans", stats)


if __name__ == "__main__":
    unittest.main()


class TestLearnedQualityGate(unittest.TestCase):
    def test_rejects_noise_and_accepts_polish(self):
        mem = make_tmp_memory()
        # odrzucane: za krótkie, odmowa, angielski, JSON/tool_call
        self.assertIsNone(mem.add_learned("remote", "krótkie", "za krótko", source="remote:x"))
        self.assertIsNone(mem.add_learned("remote", "odmowa",
                                          "Nie wiem, nie potrafię tego wyjaśnić.", source="remote:x"))
        self.assertIsNone(mem.add_learned("remote", "en",
                                          "The answer is that this is of the system.", source="remote:x"))
        self.assertIsNone(mem.add_learned("remote", "json",
                                          '{"tool": "run_command", "args": {}}', source="remote:x"))
        # akceptowany poprawny fakt po polsku
        ok = mem.add_learned("remote", "fotosynteza",
                             "Fotosynteza to proces, w którym rośliny wytwarzają cukry ze światła.",
                             source="remote:x")
        self.assertIsNotNone(ok)
        self.assertIn("Fotosynteza", mem.best_learned("fotosynteza"))
        # polskie „to" nie może być liczone jako angielski stopword
        ok2 = mem.add_learned("remote", "prawo jazdy",
                              "Prawo jazdy to dokument, który uprawnia do kierowania pojazdem. "
                              "Aby je uzyskać, trzeba to zdać egzamin teoretyczny i praktyczny.",
                              source="remote:x")
        self.assertIsNotNone(ok2)

    def test_verified_bypasses_gate(self):
        mem = make_tmp_memory()
        # źródła zweryfikowane (facts/first_aid) przechodzą nawet jeśli krótkie
        self.assertIsNotNone(mem.add_learned("fakt", "prawo", "19% od zysków kapitałowych",
                                             source="facts", verified=True, confidence=1.0))


class TestLearnedFTS(unittest.TestCase):
    def test_index_and_search(self):
        mem = make_tmp_memory()
        mem.add_learned("remote", "fotosynteza roslin",
                        "Fotosynteza zachodzi w zielonych roślinach, wytwarzając cukry.",
                        source="remote:x")
        hits = mem.search_learned_fts("fotosynteza")
        self.assertTrue(any("Fotosynteza" in t for _ti, t in hits))
        best = mem.find_learned_fts("fotosynteza roslin")
        self.assertIn("Fotosynteza", best or "")

    def test_delete_trigger_syncs(self):
        mem = make_tmp_memory()
        rid = mem.add_learned("remote", "fotosynteza roslin",
                              "Fotosynteza zachodzi w zielonych roślinach.",
                              source="remote:x")
        self.assertIsNotNone(rid)
        mem.con.execute("DELETE FROM learned WHERE id=?", (rid,))
        mem.con.commit()
        self.assertEqual(mem.search_learned_fts("fotosynteza"), [])


class TestLearnedIndexC2(unittest.TestCase):
    def test_matrix_cached_until_change(self):
        mem = make_embed_memory()
        mem.add_learned("remote", "fotosynteza",
                        "Fotosynteza zachodzi w zielonych roślinach i wytwarza cukry.",
                        source="remote:x")
        mem.best_learned("jak przebiega fotosynteza")   # buduje cache macierzy
        info1 = mem.learned_index_info()
        self.assertTrue(info1["cached"])
        mem.best_learned("jak przebiega fotosynteza")   # reuse
        self.assertEqual(mem.learned_index_info()["sig"], info1["sig"])
        mem.add_learned("remote", "prawo jazdy",
                        "Prawo jazdy uprawnia do kierowania pojazdem mechanicznym.",
                        source="remote:x")
        mem.best_learned("jak przebiega fotosynteza")   # przebudowa po zmianie
        self.assertNotEqual(mem.learned_index_info()["sig"], info1["sig"])

    def test_delete_cascades_vectors(self):
        mem = make_embed_memory()
        rid = mem.add_learned("remote", "fotosynteza",
                              "Fotosynteza zachodzi w zielonych roślinach.",
                              source="remote:x")
        assert rid is not None
        self.assertGreaterEqual(mem.learned_vector_count(), 1)
        mem.con.execute("DELETE FROM learned WHERE id=?", (rid,))
        mem.con.commit()
        orphans = mem.con.execute(
            "SELECT COUNT(*) c FROM learned_vectors WHERE learned_id NOT IN "
            "(SELECT id FROM learned)").fetchone()["c"]
        self.assertEqual(orphans, 0)


class TestTrajectoryFTS(unittest.TestCase):
    def test_ids_and_fallback(self):
        mem = make_tmp_memory()
        mem.add_trajectory(kind="agent", goal="sprawdź temperaturę procesora",
                           steps=[{"name": "system_info", "args": {}}], answer="ok")
        mem.add_trajectory(kind="agent", goal="przeczytaj plik konfiguracji",
                           steps=[{"name": "read_file", "args": {"path": "/etc/hosts"}}],
                           answer="ok")
        self.assertTrue(mem.fts_traj)
        ids = mem.search_trajectory_ids_fts("temperatura procesora")
        self.assertEqual(len(ids), 1)
        # retrieval dalej działa (FTS prefiltr), zwraca właściwy cel
        hits = mem.similar_trajectories("sprawdź temperaturę procesora", k=1)
        self.assertEqual(hits[0]["goal"], "sprawdź temperaturę procesora")
