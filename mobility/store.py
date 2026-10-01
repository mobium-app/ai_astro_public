"""Lokalny magazyn sync (mobility.db): rekordy z telefonu + wersjonowanie LWW."""

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_records (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, content TEXT NOT NULL,
    version INTEGER NOT NULL, updated_at TEXT NOT NULL, source TEXT DEFAULT 'phone',
    client_version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, when_ts TEXT,
    done INTEGER DEFAULT 0, version INTEGER, updated_at TEXT, source TEXT DEFAULT 'phone',
    client_version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sync_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _ensure_columns(conn) -> None:
    """Migracja lekka: kolumna client_version dodana po M0 (LWW per rekord)."""
    for table in ("phone_records", "reminders"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and "client_version" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN client_version INTEGER NOT NULL DEFAULT 1")


class MobilityStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        _ensure_columns(self._conn)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def server_version(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM sync_meta WHERE key='server_version'").fetchone()
        return int(row[0]) if row else 0

    def _bump_version(self) -> int:
        version = self.server_version() + 1
        self._conn.execute(
            "INSERT INTO sync_meta(key,value) VALUES('server_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(version),))
        return version

    def upsert_record(self, rec_id: str, rec_type: str, content: str,
                      updated_at: str, source: str = "phone") -> int:
        with self._lock:
            return self._upsert_record_locked(rec_id, rec_type, content, updated_at, source)

    def _upsert_record_locked(self, rec_id: str, rec_type: str, content: str,
                      updated_at: str, source: str = "phone") -> int:
        # LWW: `client_version` (wersja rekordu po stronie telefonu) decyduje o wygranej;
        # `version` to monotoniczny licznik serwera — JEST numerem delty dla `since`.
        # Nie wolno ich porównywać (dwie różne przestrzenie wersji → odrzucanie
        # świeższych pushy z telefonu).
        existing = self._conn.execute(
            "SELECT version, client_version, updated_at FROM phone_records WHERE id=?",
            (rec_id,)).fetchone()
        incoming_version = self._client_version(content)
        if existing:
            old_version, old_client, old_updated = existing
            if old_client > incoming_version:
                return old_version
            if old_client == incoming_version and old_updated > updated_at:
                return old_version
        version = self._bump_version()
        self._conn.execute(
            "INSERT INTO phone_records(id,type,content,version,updated_at,source,client_version) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET type=excluded.type, content=excluded.content, "
            "version=excluded.version, updated_at=excluded.updated_at, source=excluded.source, "
            "client_version=excluded.client_version",
            (rec_id, rec_type, content, version, updated_at, source, incoming_version))
        self._conn.commit()
        return version

    @staticmethod
    def _client_version(content: str) -> int:
        """Wersja rekordu z treści (JSON `version`) — brak = 1."""
        try:
            data = json.loads(content)
        except Exception:
            return 1
        if isinstance(data, dict):
            try:
                return int(data.get("version", 1))
            except (TypeError, ValueError):
                return 1
        return 1

    def records_since(self, since: int, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id,type,content,version,updated_at,source FROM phone_records "
            "WHERE version>? ORDER BY version LIMIT ?", (since, limit)).fetchall()
        return [{"id": r[0], "type": r[1], "content": r[2], "version": r[3],
                 "updated_at": r[4], "source": r[5]} for r in rows]

    def add_reminder(self, rec_id: str, text: str, when_ts: str | None,
                     updated_at: str) -> int:
        with self._lock:
            return self._add_reminder_locked(rec_id, text, when_ts, updated_at)

    def _add_reminder_locked(self, rec_id: str, text: str, when_ts: str | None,
                     updated_at: str) -> int:
        version = self._bump_version()
        self._conn.execute(
            "INSERT INTO reminders(id,text,when_ts,done,version,updated_at,source,client_version) "
            "VALUES(?,?,?,0,?,?,'phone',1) "
            "ON CONFLICT(id) DO UPDATE SET text=excluded.text, when_ts=excluded.when_ts, "
            "version=excluded.version, updated_at=excluded.updated_at, "
            "client_version=excluded.client_version",
            (rec_id, text, when_ts, version, updated_at))
        self._conn.commit()
        return version

    def due_reminders(self) -> list[dict]:
        now = time.time()
        rows = self._conn.execute(
            "SELECT id,text,when_ts FROM reminders WHERE done=0 "
            "AND (when_ts IS NULL OR when_ts=? OR CAST(when_ts AS REAL)<=?)",
            ("", now)).fetchall()
        return [{"id": r[0], "text": r[1], "when": r[2]} for r in rows]

    def counts(self) -> dict:
        records = self._conn.execute("SELECT COUNT(*) FROM phone_records").fetchone()[0]
        reminders = self._conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
        return {"phone_records": records, "reminders": reminders}