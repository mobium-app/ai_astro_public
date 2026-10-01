"""Ingest: rekordy z telefonu (mobility.db) -> memory.db (trajektorie) — nauka z podróży.

Uruchomienie: python -m astro.mobility.ingest [--db mobility.db]
Dedyplikacja: wbudowana w add_trajectory (kind+goal+answer); flaga ingested per rekord.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astro.mobility.store import MobilityStore  # noqa: E402

KIND_MAP = {
    "episode": "phone_episode",
    "episodes": "phone_episode",
    "lesson": "phone_lesson",
    "lessons": "phone_lesson",
    "plan": "phone_plan",
    "plans": "phone_plan",
    "note": "phone_note",
}


def _goal_and_text(content: str) -> tuple[str, str]:
    text = content or "{}"
    try:
        data = json.loads(text) if isinstance(text, str) else text
    except Exception:
        return text[:200], text
    if not isinstance(data, dict):
        return str(data)[:200], str(data)
    goal = (data.get("goal") or data.get("text") or data.get("opis")
            or data.get("temat") or "notatka")
    return str(goal), text


def ingest(store: MobilityStore, memory, dry_run: bool = False) -> dict:
    store._conn.execute(
        "ALTER TABLE phone_records ADD COLUMN ingested INTEGER DEFAULT 0"
    ) if "ingested" not in [r[1] for r in store._conn.execute(
        "PRAGMA table_info(phone_records)").fetchall()] else None
    store._conn.commit()

    rows = store._conn.execute(
        "SELECT id,type,content,updated_at FROM phone_records "
        "WHERE ingested=0 AND source='phone' ORDER BY version").fetchall()
    stats = {}
    for rec_id, rec_type, content, updated_at in rows:
        kind = KIND_MAP.get(rec_type)
        if kind is None:
            store._conn.execute("UPDATE phone_records SET ingested=1 WHERE id=?", (rec_id,))
            continue
        stats[kind.removeprefix("phone_")] = stats.get(kind.removeprefix("phone_"), 0) + 1
        goal, text = _goal_and_text(content)
        if dry_run:
            continue
        memory.add_trajectory(kind=kind, goal=goal, steps=None,
                              result=text, answer=text, source="phone")
        store._conn.execute("UPDATE phone_records SET ingested=1 WHERE id=?", (rec_id,))
    store._conn.commit()
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="astro-mobility-ingest")
    parser.add_argument("--db", default=str(ROOT / "data" / "mobility.db"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from astro.memory.store import default_memory

    store = MobilityStore(args.db)
    memory = None if args.dry_run else default_memory()
    stats = ingest(store, memory, dry_run=args.dry_run)
    store.close()
    if memory is not None:
        memory.close()
    print(json.dumps({"ingested": stats, "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())