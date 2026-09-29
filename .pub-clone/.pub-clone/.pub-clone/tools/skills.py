"""Narzędzia skili: model może odkryć przepisy i uruchomić te tylko do odczytu.

To rozszerza tool-calling o gotowe, deterministyczne receptury ASTRO (journal, du, git,
systemd, procesy). Przepisy zmieniające system (`confirm: always`) NIE są uruchamiane
przez model - wymagają świadomego potwierdzenia użytkownika (ścieżka w `dispatch`).
"""

from .registry import ToolResult, tool


def _find(name):
    from ..skills import load_skills
    for skill in load_skills():
        if skill.name == name:
            return skill
    return None


def register():
    @tool("list_skills", "Lista dostępnych przepisów (skilli) ASTRO z opisem i zakresem.",
          {"type": "object", "properties": {}}, scopes=("read",))
    def list_skills(ctx):
        from ..skills import list_skills_text
        return ToolResult(list_skills_text(), ok=True)

    @tool("run_skill", "Uruchamia przepis ASTRO tylko do odczytu (np. journal, dir_size, top_memory).",
          {"type": "object",
           "properties": {"name": {"type": "string", "description": "nazwa przepisu"},
                          "params": {"type": "object", "description": "parametry przepisu"}},
           "required": ["name"]},
          scopes=("read",))
    def run_skill_tool(ctx, name, params=None):
        from ..skills import run_skill
        skill = _find(name)
        if skill is None:
            return ToolResult(f"nieznany przepis: {name}", ok=False)
        if skill.confirm != "never":
            return ToolResult(
                f"Przepis '{name}' zmienia system - wymaga potwierdzenia użytkownika.", ok=False)
        text, ok, pending = run_skill(ctx, skill, params or {})
        return ToolResult(text, ok=ok)
