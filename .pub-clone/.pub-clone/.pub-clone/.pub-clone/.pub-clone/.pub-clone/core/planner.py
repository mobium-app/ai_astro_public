"""Planowanie zadań (JSON) + walidacja planu."""

import json
import re

from ..safety import is_executable_command, validate_plan

PLAN_PROMPT = (
    "Jesteś planistą. Zwróć WYŁĄCZNIE JSON: {\"steps\":[{\"command\":\"...\"}]}. "
    "Kroki to konkretne polecenia powłoki. Nie instaluj pakietów, jeśli cel tego nie wymaga."
)


def parse_plan(raw):
    raw = (raw or "").strip()
    if not raw:
        return []
    m = re.search(r"\{.*\}|\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    steps = data.get("steps") if isinstance(data, dict) else data
    out = []
    for s in steps or []:
        if isinstance(s, str):
            s = {"command": s}
        cmd = (s.get("command") or "").strip() if isinstance(s, dict) else ""
        if cmd:
            out.append({"command": cmd})
    return out


def goal_to_steps(goal, backends, max_tokens=400, hint=None):
    content = f"Cel: {goal}"
    if hint:
        content += ("\n\nSprawdzony wcześniej plan dla podobnego celu (możesz go użyć, jeśli "
                    "pasuje):\n" + hint)
    messages = [
        {"role": "system", "content": PLAN_PROMPT},
        {"role": "user", "content": content},
    ]
    # Plan dla komendy wykonawczej generujemy TYLKO lokalnie (bez pc/remote) — spójnie z zasadą
    # „komendy nigdy do chmury" (plan zawiera konkretne polecenia powłoki).
    result = backends.run("plan", messages, fmt="json", max_tokens=max_tokens, temperature=0.1,
                          local_only=is_executable_command(goal))
    return parse_plan(result.text)


def safe_plan(goal, steps):
    if not steps:
        return None, "nie udało się zaplanować"
    problem = validate_plan(steps, goal)
    if problem:
        return None, problem
    return steps, None
