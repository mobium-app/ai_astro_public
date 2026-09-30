"""Deterministyczne komendy nastroju ASTRO (E7.2): podgląd stanu afektywnego.

Bez modelu i bez sieci. Wpięte w `dispatch` przed agentem; działa też głosowo.
"""

import re

from ..safety import normalize_facts

QUERY_RE = re.compile(
    r"\bco czujesz\b|\bjak sie czujesz\b|\bjaki masz nastroj\b|\btwoj nastroj\b|"
    r"\bjaki masz humor\b|\bjak sie masz\b")


def handle(text, agent=None):
    norm = normalize_facts(text or "")
    if not norm or not QUERY_RE.search(norm):
        return None
    memory = getattr(agent, "memory", None) or getattr(
        getattr(agent, "ctx", None), "memory", None)
    store = getattr(memory, "affect", None) if memory is not None else None
    if store is None:
        return None
    label, guidance = store.load().describe()
    return f"Mój nastrój: {label}. {guidance}.".capitalize(), "affect"
