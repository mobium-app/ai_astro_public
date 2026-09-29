"""Narzędzie złożonych zadań systemowych: plan -> walidacja -> potwierdzenie -> wykonanie."""

import subprocess

from .. import mirror
from .registry import ToolResult, tool


def run_shell(cmd, timeout=600):
    try:
        p = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"przekroczono limit {timeout}s"
    except Exception as e:
        return 1, str(e)


def execute_steps(ctx, goal, steps):
    """Wykonuje zatwierdzone kroki planu i raportuje wynik (używane też przy potwierdzeniu)."""
    lines, success = [], True
    for i, step in enumerate(steps, 1):
        mirror.command(step["command"], root=bool(step.get("root")))
        code, out = run_shell(step["command"])
        mirror.command(step["command"], out[:1500], code, root=bool(step.get("root")))
        lines.append(f"{i}. $ {step['command']} -> kod {code}: {out[:300]}")
        if code != 0:
            success = False
        if ctx.memory:
            ctx.memory.record_plan_result(goal, steps[:i], success=(code == 0))
    return ToolResult("Wynik planu:\n" + "\n".join(lines), ok=success,
                      data={"steps": steps})


def register():
    @tool("system_task", "Planuje złożone zadanie systemowe i wykonuje je po potwierdzeniu.",
          {"type": "object", "properties": {"goal": {"type": "string"}},
           "required": ["goal"]},
          scopes=("gated",), self_gated=True,
          confirm_text="Wykonać zaplanowane zadanie systemowe?")
    def system_task(ctx, goal):
        from ..core import planner

        if ctx.backends is None:
            return ToolResult("brak backendu do planowania", ok=False)
        cached = ctx.memory.find_plan(goal, reuse=0.90) if ctx.memory else None
        if cached and cached.get("steps"):
            steps, problem = planner.safe_plan(goal, cached["steps"])
        else:
            steps = planner.goal_to_steps(goal, ctx.backends)
            steps, problem = planner.safe_plan(goal, steps)
        if not steps:
            return ToolResult(problem or "nie udało się zaplanować zadania", ok=False)
        plan_text = "Plan: " + "; ".join(s["command"] for s in steps)
        confirmed = False
        if ctx.confirmer is not None and not getattr(ctx, "assume_confirmed", False):
            confirmed = ctx.confirmer.require_confirm(f"{plan_text} — wykonać?", "system_task",
                                                      {"steps": steps, "goal": goal})
        else:
            confirmed = True
        if not confirmed:
            return ToolResult(f"Wymaga potwierdzenia: {plan_text}", ok=False,
                              data={"pending": True, "kind": "system_task",
                                    "payload": {"steps": steps, "goal": goal}})
        return execute_steps(ctx, goal, steps)
