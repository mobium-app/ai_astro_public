"""Testy złożonych zadań systemowych (plan -> walidacja -> potwierdzenie -> wykonanie)."""

import os
import tempfile
import unittest

from astro import backends as B
from astro import config, memory
from astro.safety import Confirmer
from astro.tools import ToolContext, registry


class PlanBackend(B.Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def __init__(self, plan):
        self.plan = plan

    def ready(self):
        return True

    def run(self, messages, **kw):
        return B.BackendResult(text=self.plan)


def make_ctx(plan, auto):
    breg = B.BackendRegistry()
    breg.register(PlanBackend(plan))
    mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
    return ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=auto),
                       registry=registry, backends=breg), mem


class TestSystemTask(unittest.TestCase):
    GOOD = '{"steps":[{"command":"echo astro-plan-ok"}]}'
    BAD = '{"steps":[{"command":"rm -rf /"}]}'

    def test_auto_executes(self):
        ctx, mem = make_ctx(self.GOOD, auto=True)
        res = registry.execute("system_task", {"goal": "wykonaj test"}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("astro-plan-ok", res.text)
        self.assertGreaterEqual(mem.plan_stats()["ok"], 1)

    def test_requires_confirm(self):
        ctx, mem = make_ctx(self.GOOD, auto=False)
        res = registry.execute("system_task", {"goal": "wykonaj test"}, ctx)
        self.assertFalse(res.ok)
        self.assertTrue(res.data and res.data.get("pending"))
        self.assertEqual(mem.plan_stats()["ok"], 0)

    def test_dangerous_plan_rejected(self):
        ctx, mem = make_ctx(self.BAD, auto=True)
        res = registry.execute("system_task", {"goal": "posprzątaj system"}, ctx)
        self.assertFalse(res.ok)
        self.assertIn("odrzucono", res.text)


if __name__ == "__main__":
    unittest.main()
