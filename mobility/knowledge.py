"""M0 — wiedza bazowa dla telefonu: paczka + delta (eksport z tabeli `learned`).

Telefon ma być „lustrem" pamięci Pi, więc `/context` musi oddawać także wiedzę:
pełna paczka przy pierwszym sync (gdy `since=0`), a potem tylko delta (wpisy nowsze
niż znana wersja). Format: lista rekordów `{id, q, a, topic, source}` — ten sam
kształt, którego klient Flutterowy zapisuje w `VectorIndex`/`TfIdfIndex`.

Granice: eksport jest **tylko do odczytu** i **bez wektorów** (embeddingi zostają
na Pi; telefon liczy swój retrieval lokalnie). Przycięte odpowiedzi (`text` za długi
albo obcięty) są pomijane — telefon nie ma narzędzi do oczyszczania.
"""

import json
import os
import re
import sqlite3
import time
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "runtime" / "memory.db"
MAX_ANSWER_CHARS = 1200
MIN_ANSWER_CHARS = 8
# odpowiedzi urwane przez nauczyciela (kończą się na „…" lub bez kropki po cięciu)
_TRUNC_TAIL = re.compile(r"(\.\.\.|…)\s*$")


def _looks_truncated(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    return bool(_TRUNC_TAIL.search(t))


def open_db(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def count_usable(db_path: str | Path = DEFAULT_DB) -> int:
    conn = open_db(db_path)
    if conn is None:
        return 0
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM learned WHERE text IS NOT NULL AND LENGTH(text) > ?",
            (MIN_ANSWER_CHARS,)).fetchone()[0]
    finally:
        conn.close()


def pack(db_path: str | Path = DEFAULT_DB, limit: int = 20000) -> list[dict]:
    """Paczka wiedzy ( kolejność stabilna po `id` = przyrost delta)."""
    conn = open_db(db_path)
    if conn is None:
        return []
    out: list[dict] = []
    try:
        rows = conn.execute(
            "SELECT id, title, text, topic, source FROM learned "
            "WHERE text IS NOT NULL AND LENGTH(text) > ? "
            "ORDER BY id LIMIT ?", (MIN_ANSWER_CHARS, limit))
        for r in rows:
            text = (r["text"] or "").strip()
            if _looks_truncated(text):
                continue
            out.append({
                "id": r["id"],
                "q": (r["title"] or "").strip(),
                "a": text[:MAX_ANSWER_CHARS],
                "topic": r["topic"] or "",
                "source": r["source"] or "",
            })
    finally:
        conn.close()
    return out


def delta(db_path: str | Path, since: int, limit: int = 200) -> list[dict]:
    """Tylko wpisy z `id > since` (telefon zna już swoją paczkę do `since`)."""
    if since <= 0:
        return pack(db_path)[:limit]
    conn = open_db(db_path)
    if conn is None:
        return []
    out: list[dict] = []
    try:
        rows = conn.execute(
            "SELECT id, title, text, topic, source FROM learned "
            "WHERE id > ? AND text IS NOT NULL AND LENGTH(text) > ? "
            "ORDER BY id LIMIT ?", (since, MIN_ANSWER_CHARS, limit))
        for r in rows:
            text = (r["text"] or "").strip()
            if _looks_truncated(text):
                continue
            out.append({
                "id": r["id"],
                "q": (r["title"] or "").strip(),
                "a": text[:MAX_ANSWER_CHARS],
                "topic": r["topic"] or "",
                "source": r["source"] or "",
            })
    finally:
        conn.close()
    return out


def latest_id(db_path: str | Path = DEFAULT_DB) -> int:
    conn = open_db(db_path)
    if conn is None:
        return 0
    try:
        row = conn.execute("SELECT MAX(id) FROM learned").fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def write_pack(out_path: str | Path, db_path: str | Path = DEFAULT_DB) -> int:
    """Zapisuje paczkę do pliku JSON (przydatne: ręczny wgranie na telefon)."""
    items = pack(db_path)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_id": latest_id(db_path),
        "count": len(items),
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(items)


def export_bank(out_path: str | Path, db_path: str | Path = DEFAULT_DB,
                source: str = "qa_baza") -> int:
    """Eksport banku Q&A (stała wiedza bazowa) jako paczka JSON do pliku.

    Wybiera wyłącznie wpisy o zadanym `source` (domyślnie `qa_baza` — bank
    1020+ Q&A zaingestowany przez `scripts/ingest_qa.py`). Format pliku taki
    sam jak `write_pack` — `{generated_at, latest_id, count, items}` z itemami
    `{id, q, a, topic, source}` (kształt zgodny z `learned`), bez wektorów.

    Delta: telefon liczy ją lokalnie po `id` względem `latest_id` albo pobiera
    przez `GET /context?kdelta=` (serwer). Brak bazy = 0 wpisów, plik nie
    powstaje. Zwraca liczbę zapisanych wpisów.
    """
    conn = open_db(db_path)
    if conn is None:
        return 0
    items: list[dict] = []
    try:
        rows = conn.execute(
            "SELECT id, title, text, topic, source FROM learned "
            "WHERE source = ? AND text IS NOT NULL AND LENGTH(text) > ? "
            "ORDER BY id", (source, MIN_ANSWER_CHARS))
        for r in rows:
            text = (r["text"] or "").strip()
            if _looks_truncated(text):
                continue
            items.append({
                "id": r["id"],
                "q": (r["title"] or "").strip(),
                "a": text[:MAX_ANSWER_CHARS],
                "topic": r["topic"] or "",
                "source": r["source"] or "",
            })
    finally:
        conn.close()
    if not items:
        return 0
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_id": items[-1]["id"],
        "count": len(items),
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(items)
