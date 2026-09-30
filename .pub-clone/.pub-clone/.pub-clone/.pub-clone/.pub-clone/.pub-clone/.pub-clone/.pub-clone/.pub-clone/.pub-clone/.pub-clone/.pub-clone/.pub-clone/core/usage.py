"""Telemetria użycia (runtime w tle): co ASTRO realnie woła -> kolejność curriculum.

Każda tura zapisuje jeden rekord do `runtime/logs/usage.jsonl` (trasa, narzędzia, backend,
znormalizowany temat). Ranking (`usage_summary`) mówi, które intencje/narzędzia są najczęstsze,
żeby trenować i budować wiedzę od najczęściej używanych do rzadkich/nieużywanych.
"""

import json
import os
import re
import time
from collections import Counter

from .. import config
from ..safety import normalize_facts

USAGE_FILE = os.path.join(str(config.LOGS_DIR), "usage.jsonl")


def _topic(text):
    return re.sub(r"\s+", " ", normalize_facts(text or "")).strip()[:160]


def log_usage(text, result):
    """Zapisuje jedną turę. Nie rzuca wyjątków (telemetria nie może psuć runtime)."""
    try:
        tools = []
        agent_result = getattr(result, "agent_result", None)
        for call in (getattr(agent_result, "tool_calls", None) or []):
            name = call.get("name") if isinstance(call, dict) else None
            if name:
                tools.append(name)
        rec = {"ts": round(time.time(), 1), "route": getattr(result, "route", "") or "",
               "tools": tools, "chars": len(text or ""), "topic": _topic(text),
               "used_tools": bool(getattr(agent_result, "used_tools", False))}
        os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
        with open(USAGE_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_usage():
    if not os.path.exists(USAGE_FILE):
        return []
    out = []
    with open(USAGE_FILE, errors="replace") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def usage_summary(top=25):
    """Ranking tras i narzędzi oraz najczęstsze tematy (do curriculum)."""
    rows = read_usage()
    routes, tools, topics = Counter(), Counter(), Counter()
    for r in rows:
        routes[r.get("route") or "?"] += 1
        for t in (r.get("tools") or []):
            tools[t] += 1
        if r.get("topic"):
            topics[r["topic"]] += 1
    return {"total": len(rows), "routes": routes.most_common(top),
            "tools": tools.most_common(top), "topics": topics.most_common(top)}
