"""Powiadomienia push (M4): zaległe przypomnienia z mobility.db -> ntfy.sh.

Uruchomienie: python -m astro.mobility.notify
Topik:      secrets/ntfy_topic (600) — domyślnie "astro-mob-<hash hostname>".
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astro.mobility.store import MobilityStore  # noqa: E402

NTFY_BASE = "https://ntfy.sh"


def default_topic() -> str:
    host = Path("/etc/hostname").read_text().strip() if Path("/etc/hostname").exists() else "astro"
    digest = hashlib.sha256(host.encode()).hexdigest()[:10]
    return f"astro-mob-{digest}"


def publish(topic: str, text: str, base: str = NTFY_BASE,
            timeout: float = 10.0) -> int:
    req = urllib.request.Request(
        f"{base}/{topic}", data=text.encode("utf-8"),
        headers={"Content-Type": "text/plain", "Title": "Astro: przypomnienie"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def notify(store: MobilityStore, topic: str, base: str = NTFY_BASE,
           dry_run: bool = False, now: float | None = None) -> dict:
    ts = now if now is not None else time.time()
    rows = store._conn.execute(
        "SELECT id, text, when_ts FROM reminders WHERE done=0 "
        "AND when_ts IS NOT NULL AND when_ts != '' "
        "AND CAST(when_ts AS REAL) <= ?", (ts,)).fetchall()
    sent = []
    for rec_id, text, when_ts in rows:
        if dry_run:
            sent.append(rec_id)
            continue
        try:
            publish(topic, text, base=base)
            store._conn.execute("UPDATE reminders SET done=1 WHERE id=?", (rec_id,))
            sent.append(rec_id)
        except Exception as exc:
            print(f"[notify] błąd {rec_id}: {exc}", file=sys.stderr)
    store._conn.commit()
    return {"sent": sent, "count": len(sent), "topic": topic}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="astro-mobility-notify")
    parser.add_argument("--db", default=str(ROOT / "data" / "mobility.db"))
    parser.add_argument("--topic", default=None)
    parser.add_argument("--base", default=NTFY_BASE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    topic = args.topic or default_topic()
    store = MobilityStore(args.db)
    result = notify(store, topic, base=args.base, dry_run=args.dry_run)
    store.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())