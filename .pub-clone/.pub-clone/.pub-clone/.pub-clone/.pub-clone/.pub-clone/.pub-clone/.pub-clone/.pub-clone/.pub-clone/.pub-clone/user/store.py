"""Trwały magazyn profilu użytkownika: tabele `profile` + `profile_history` (audyt).

Aktywny profil jest nadpisywany, ale historia zmian jest append-only (możliwość cofnięcia
i wykrycia regresu). Wartości list są kodowane jako JSON. Pola prywatne nie są nigdzie
wysyłane — trafiają wyłącznie do lokalnej bazy i są maskowane w mirrorze/logach.
"""

import json
import time

from . import profile as P

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    user_id TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT DEFAULT 'user',
    confidence REAL DEFAULT 1.0,
    sensitivity TEXT DEFAULT 'internal',
    updated_at REAL,
    PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS profile_history (
    id INTEGER PRIMARY KEY,
    ts REAL,
    user_id TEXT,
    action TEXT,
    key TEXT,
    old_value TEXT,
    new_value TEXT,
    source TEXT);
"""


class ProfileStore:
    def __init__(self, con, user_id="default"):
        self.con = con
        self.user_id = user_id
        self.con.executescript(SCHEMA)
        self.con.commit()

    def _decode(self, key, raw):
        spec = P.FIELDS.get(key) or {}
        if spec.get("type") == "list":
            try:
                val = json.loads(raw)
                return val if isinstance(val, list) else [str(raw)]
            except Exception:
                return [str(raw)]
        return raw

    def _encode(self, value):
        if isinstance(value, list):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def get(self, user_id=None):
        uid = user_id or self.user_id
        rows = self.con.execute(
            "SELECT key, value FROM profile WHERE user_id=?", (uid,)).fetchall()
        return {r["key"]: self._decode(r["key"], r["value"]) for r in rows}

    def get_field(self, key, user_id=None):
        return self.get(user_id).get(key)

    def _history(self, action, key, old, new, source):
        self.con.execute(
            "INSERT INTO profile_history(ts, user_id, action, key, old_value, new_value, source) "
            "VALUES(?,?,?,?,?,?,?)",
            (time.time(), self.user_id, action, key, old, new, source))

    def merge(self, values, source="user"):
        """Dopisuje/nadpisuje wskazane pola (reszta profilu zostaje)."""
        now = time.time()
        for key, value in (values or {}).items():
            if key not in P.FIELDS or value in (None, "", []):
                continue
            old_row = self.con.execute(
                "SELECT value FROM profile WHERE user_id=? AND key=?",
                (self.user_id, key)).fetchone()
            old = old_row["value"] if old_row else None
            enc = self._encode(value)
            self.con.execute(
                "INSERT INTO profile(user_id, key, value, source, sensitivity, updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(user_id, key) DO UPDATE SET "
                "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at",
                (self.user_id, key, enc, source, "private" if P.is_private(key) else "internal",
                 now))
            self._history("set", key, old, enc, source)
        self.con.commit()
        self._sync_redactions()
        return self.get()

    def replace(self, values, source="user"):
        """Nadpisuje CAŁY profil (stare pola, których nie ma w nowych, są czyszczone)."""
        now = time.time()
        new = {k: v for k, v in (values or {}).items()
               if k in P.FIELDS and v not in (None, "", [])}
        for r in self.con.execute("SELECT key, value FROM profile WHERE user_id=?",
                                  (self.user_id,)).fetchall():
            if r["key"] not in new:
                self._history("clear", r["key"], r["value"], None, source)
        self.con.execute("DELETE FROM profile WHERE user_id=?", (self.user_id,))
        for key, value in new.items():
            enc = self._encode(value)
            self.con.execute(
                "INSERT INTO profile(user_id, key, value, source, sensitivity, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (self.user_id, key, enc, source, "private" if P.is_private(key) else "internal",
                 now))
            self._history("set", key, None, enc, source)
        self.con.commit()
        self._sync_redactions()
        return self.get()

    def forget(self, key=None):
        """Usuwa jedno pole albo cały profil (z wpisem audytowym)."""
        if key:
            row = self.con.execute("SELECT value FROM profile WHERE user_id=? AND key=?",
                                   (self.user_id, key)).fetchone()
            if not row:
                return 0
            self._history("clear", key, row["value"], None, "forget")
            self.con.execute("DELETE FROM profile WHERE user_id=? AND key=?",
                             (self.user_id, key))
            n = 1
        else:
            for r in self.con.execute("SELECT key, value FROM profile WHERE user_id=?",
                                      (self.user_id,)).fetchall():
                self._history("clear", r["key"], r["value"], None, "forget")
            cur = self.con.execute("DELETE FROM profile WHERE user_id=?", (self.user_id,))
            n = cur.rowcount
        self.con.commit()
        self._sync_redactions()
        return n

    def history(self, limit=50, user_id=None):
        uid = user_id or self.user_id
        rows = self.con.execute(
            "SELECT ts, action, key, old_value, new_value, source FROM profile_history "
            "WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
        return [dict(r) for r in rows]

    def export(self, user_id=None):
        return {"schema_version": 1, "user_id": user_id or self.user_id,
                "exported_at": time.time(), "profile": self.get(user_id)}

    def _sync_redactions(self):
        try:
            from .. import mirror
            mirror.set_redactions(P.private_values(self.get()))
        except Exception:
            pass

    def summary(self, masked=True):
        return P.summary_lines(self.get(), masked=masked)
