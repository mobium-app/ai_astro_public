"""Trwały stan afektywny ASTRO w `memory.db` (tabela `affect`, jeden wiersz na użytkownika)."""

import time

from .affect import AffectState

SCHEMA = """
CREATE TABLE IF NOT EXISTS affect (
    user_id TEXT PRIMARY KEY,
    ts REAL,
    mood_p REAL DEFAULT 0, mood_a REAL DEFAULT 0, mood_d REAL DEFAULT 0,
    emo_p REAL DEFAULT 0, emo_a REAL DEFAULT 0, emo_d REAL DEFAULT 0);
"""


class AffectStore:
    def __init__(self, con, user_id="default"):
        self.con = con
        self.user_id = user_id
        self.con.executescript(SCHEMA)
        self.con.commit()

    def load(self, now=None):
        row = self.con.execute(
            "SELECT ts, mood_p, mood_a, mood_d, emo_p, emo_a, emo_d FROM affect WHERE user_id=?",
            (self.user_id,)).fetchone()
        if not row:
            return AffectState(ts=now)
        state = AffectState(mood=(row["mood_p"], row["mood_a"], row["mood_d"]),
                            emotion=(row["emo_p"], row["emo_a"], row["emo_d"]),
                            ts=row["ts"])
        state.decay(now)
        return state

    def save(self, state):
        now = time.time()
        self.con.execute(
            "INSERT INTO affect(user_id, ts, mood_p, mood_a, mood_d, emo_p, emo_a, emo_d) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "ts=excluded.ts, mood_p=excluded.mood_p, mood_a=excluded.mood_a, mood_d=excluded.mood_d, "
            "emo_p=excluded.emo_p, emo_a=excluded.emo_a, emo_d=excluded.emo_d",
            (self.user_id, now, state.mood[0], state.mood[1], state.mood[2],
             state.emotion[0], state.emotion[1], state.emotion[2]))
        self.con.commit()
        return state

    def reset(self):
        self.con.execute("DELETE FROM affect WHERE user_id=?", (self.user_id,))
        self.con.commit()
        return AffectState()
