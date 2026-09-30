"""Trwały stan humoru ASTRO w `memory.db`: cooldown + ostatnio użyte żarty (żeby nie nużyć)."""

import json
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS humor_state (
    user_id TEXT PRIMARY KEY,
    last_ts REAL DEFAULT 0,
    recent TEXT DEFAULT '[]');
"""


class HumorStore:
    def __init__(self, con, user_id="default", cooldown=None):
        from .. import config
        self.con = con
        self.user_id = user_id
        self.cooldown = config.HUMOR_COOLDOWN if cooldown is None else float(cooldown)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def _row(self):
        return self.con.execute(
            "SELECT last_ts, recent FROM humor_state WHERE user_id=?",
            (self.user_id,)).fetchone()

    def recent_ids(self):
        row = self._row()
        if not row:
            return []
        try:
            data = json.loads(row["recent"])
            return list(data) if isinstance(data, list) else []
        except Exception:
            return []

    def allow(self, now=None):
        row = self._row()
        if not row:
            return True
        now = time.time() if now is None else float(now)
        return (now - float(row["last_ts"] or 0)) >= self.cooldown

    def mark(self, joke_id, now=None):
        now = time.time() if now is None else float(now)
        recent = (self.recent_ids() + [joke_id])[-3:]
        self.con.execute(
            "INSERT INTO humor_state(user_id, last_ts, recent) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_ts=excluded.last_ts, recent=excluded.recent",
            (self.user_id, now, json.dumps(recent, ensure_ascii=False)))
        self.con.commit()
        return recent

    def reset(self):
        self.con.execute("DELETE FROM humor_state WHERE user_id=?", (self.user_id,))
        self.con.commit()
