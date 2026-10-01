"""Proxy /chat: agent Astro przez rejestr backendów (CPU/NPU/PC/remote)."""

import re

from astro.backends import registry
from astro import config

PERSONA = (
    "Jesteś Astro — domowy asystent głosowy użytkownika, ciepły i rzeczowy, "
    "mówisz po polsku, krótko (max 3–4 zdania), bez wyliczeń i gwiazdek. "
    "Nie udajesz człowieka; jesteś pomocnym robotem-asystentem."
)

SAFE_TOOLS = {}


def agent_reply(messages: list[dict], language: str = "pl") -> str:
    backend = registry.choose("chat", text=messages[-1]["content"] if messages else "")
    system = {"role": "system", "content": PERSONA}
    reply = backend.run([system, *messages], max_tokens=400, temperature=0.3)
    text = (reply.text or "").strip()
    return text


def validate_messages(messages: list) -> bool:
    if not isinstance(messages, list) or not messages:
        return False
    for m in messages:
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            return False
        if m["role"] not in ("system", "user", "assistant"):
            return False
    return True