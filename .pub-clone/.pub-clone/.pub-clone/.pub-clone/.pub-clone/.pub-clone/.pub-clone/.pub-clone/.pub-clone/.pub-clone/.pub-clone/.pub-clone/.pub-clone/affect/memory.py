"""Pamięć afektywna ASTRO (E8): zdarzenia z ładunkiem PAD + przypominanie (sprzężenie emocji z pamięcią).

Każda tura zapisuje oceniony stan (PAD) wraz z treścią, a przy podobnym temacie ASTRO
„przypomina sobie" skojarzenie i delikatnie przesuwa nastrój — to przenoszenie emocji między
sesjami (inspiracja: Sentipolis, emotion–memory coupling). Bez modelu i bez sieci.
"""

import re
import time

from .. import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS affect_events (
    id INTEGER PRIMARY KEY,
    ts REAL,
    goal TEXT,
    p REAL, a REAL, d REAL,
    source TEXT DEFAULT 'turn');
CREATE INDEX IF NOT EXISTS idx_affect_events_ts ON affect_events(ts);
"""


def _tokens(text):
    return set(re.findall(r"\w+", (text or "").lower()))


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class AffectMemory:
    def __init__(self, con, max_events=None):
        self.con = con
        self.max_events = getattr(config, "AFFECT_MEMORY_MAX", 500) if max_events is None \
            else int(max_events)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def record(self, goal, pad, source="turn"):
        goal = (goal or "").strip()
        if not goal:
            return None
        p, a, d = (float(x) for x in pad)
        cur = self.con.execute(
            "INSERT INTO affect_events(ts, goal, p, a, d, source) VALUES(?,?,?,?,?,?)",
            (time.time(), goal[:300], p, a, d, source))
        self.con.commit()
        self._prune()
        return cur.lastrowid

    def _prune(self):
        if not self.max_events:
            return
        self.con.execute(
            "DELETE FROM affect_events WHERE id NOT IN "
            "(SELECT id FROM affect_events ORDER BY id DESC LIMIT ?)", (self.max_events,))
        self.con.commit()

    def count(self):
        return self.con.execute("SELECT COUNT(*) c FROM affect_events").fetchone()["c"]

    def recall(self, query, k=3, min_score=None, now=None):
        """Zwraca ((P,A,D), trafienia) — skojarzone PAD z podobnych zdarzeń, ważone świeżością."""
        if not (query or "").strip():
            return None, []
        if min_score is None:
            min_score = getattr(config, "AFFECT_RECALL_MIN_SCORE", 0.34)
        now = time.time() if now is None else float(now)
        half_life = getattr(config, "AFFECT_MOOD_HALF_LIFE", 10800)
        target = _tokens(query)
        rows = self.con.execute("SELECT ts, goal, p, a, d FROM affect_events").fetchall()
        scored = []
        for r in rows:
            score = _jaccard(target, _tokens(r["goal"]))
            if score < min_score:
                continue
            recency = 0.5 ** (max(0.0, now - r["ts"]) / half_life) if half_life > 0 else 1.0
            scored.append((score * recency, r))
        if not scored:
            return None, []
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:max(1, k)]
        wsum = sum(w for w, _ in top) or 1.0
        pad = (sum(w * r["p"] for w, r in top) / wsum,
               sum(w * r["a"] for w, r in top) / wsum,
               sum(w * r["d"] for w, r in top) / wsum)
        hits = [{"goal": r["goal"], "score": round(w, 3)} for w, r in top]
        return pad, hits

    def reset(self):
        self.con.execute("DELETE FROM affect_events")
        self.con.commit()
