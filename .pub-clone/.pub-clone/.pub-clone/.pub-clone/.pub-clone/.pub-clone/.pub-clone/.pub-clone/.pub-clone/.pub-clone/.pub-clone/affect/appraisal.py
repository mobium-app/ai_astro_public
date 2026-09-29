"""Appraisal ASTRO (E7.3): deterministyczna ocena zdarzeń → delty PAD (model OCC-like).

Oceniamy zdarzenie pod kątem celu ASTRO (czy pomogło/zaszkodziło), zgodnie z teorią oceny:
sukces → przyjemność/sprawczość, porażka → przykrość/pobudzenie, pochwała → przyjemność,
krytyka → przykrość, ryzyko → czujność (pobudzenie, spadek sprawczości). Bez modelu i sieci.
"""

import re

from ..safety import normalize_facts

# Zdarzenie -> (przyjemność, pobudzenie, sprawczość) przy sile 1.0.
EVENTS = {
    "greeting": (0.10, 0.05, 0.05),
    "tool_ok": (0.15, 0.10, 0.15),
    "tool_fail": (-0.25, 0.25, -0.20),
    "task_done": (0.20, 0.15, 0.20),
    "task_fail": (-0.30, 0.30, -0.25),
    "praise": (0.35, 0.25, 0.15),
    "critique": (-0.30, 0.30, -0.20),
    "risk": (-0.20, 0.35, -0.25),
    "calm": (0.10, -0.20, 0.05),
}

_PRAISE_RE = re.compile(
    r"\b(dziekuje|dzieki|super|swietnie|brawo|doskonale|doskonala|dobra robota|"
    r"wspaniala|wspaniale|kocham|rewelacja|ekstra|perfekcyjnie|jestes genialna|"
    r"swietna robota|jestes najlepsza|podziwiam)\b")
_CRITIQUE_RE = re.compile(
    r"\b(glupia|glupie|beznadziejna|beznadziejne|do niczego|nie dziala|nie dzialasz|"
    r"bezuzytaczna|bezuzyteczna|bezuzyteczne|nie pomoglas|nie pomogla|idiotka|"
    r"durnowata|nie tak|zle zrobilas|zle|nieudolna|zawiodlam)\b")
_RISK_RE = re.compile(
    r"\b(awaria|pozar|wlamanie|zagrozenie|zagrozone|niebezpiecz\w*|wypadek|alarm|"
    r"emergency|pomocy|ratunku|krytyczn\w*|pilne)\b")


def appraise(event, strength=1.0):
    base = EVENTS.get(event)
    if not base:
        return (0.0, 0.0, 0.0)
    s = float(strength)
    return tuple(v * s for v in base)


# Wyraz twarzy (wizja) -> delty PAD (przyjemność, pobudzenie, sprawczość). Mapowanie
# z koła emocji Russella: radość = +przyjemność/+pobudzenie, smutek = -, gniew = pobudzenie
# bez przyjemności, strach = silne pobudzenie, obrzydzenie = -przyjemność, zaskoczenie = pobudzenie.
EXPRESSION_PAD = {
    "happy": (0.6, 0.4, 0.2),
    "neutral": (0.0, 0.0, 0.0),
    "sad": (-0.5, -0.3, -0.3),
    "angry": (-0.4, 0.5, 0.1),
    "surprised": (0.2, 0.6, 0.0),
    "fearful": (-0.4, 0.6, -0.4),
    "disgust": (-0.5, 0.2, -0.2),
}


def expression_pad(expression, strength=1.0):
    """Delty PAD dla wyrazu twarzy z wizji (np. „happy" -> radosny bodziec)."""
    base = EXPRESSION_PAD.get((expression or "").strip().lower())
    if not base:
        return (0.0, 0.0, 0.0)
    s = float(strength)
    return tuple(v * s for v in base)


def detect(text):
    """Zdarzenia tonu/ryzyka w wypowiedzi użytkownika (priorytet: ryzyko > krytyka > pochwała)."""
    norm = normalize_facts(text or "")
    out = []
    if _RISK_RE.search(norm):
        out.append("risk")
    if _CRITIQUE_RE.search(norm):
        out.append("critique")
    if _PRAISE_RE.search(norm):
        out.append("praise")
    return out


def outcome_events(calls_log):
    """Zdarzenia z wyniku narzędzi: sukces vs porażka (z siłą zależną od liczby błędów)."""
    if not calls_log:
        return []
    fails = sum(1 for c in calls_log if not c.get("ok", True))
    total = len(calls_log)
    if fails == 0:
        return [("task_done" if total > 1 else "tool_ok", 1.0)]
    strength = min(1.0, 0.6 + 0.2 * fails)
    return [("tool_fail", strength)]
