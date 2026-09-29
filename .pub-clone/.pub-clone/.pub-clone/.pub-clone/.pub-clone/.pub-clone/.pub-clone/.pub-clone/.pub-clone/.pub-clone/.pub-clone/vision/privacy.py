"""Prywatność wizji (Faza 6): twardy „watch off" + audyt dostępu do biometrii.

Dwa niezależne mechanizmy:
  * **watch-off** (`runtime/vision_watch.off`): trwała flaga — nasłuch (`astro-vision-watch`)
    pomija CAŁĄ analizę (nie tylko mówienie). Włącz/wyłącz komendą głosową („wyłącz nasłuch
    kamery" / „włącz nasłuch kamery") albo `scripts/vision_watch_off.sh`.
  * **audyt** (`runtime/logs/biometria_audit.jsonl`): append-only zapis operacji na danych
    biometrycznych (zapis/usunięcie twarzy i sylwetki, czyszczenie zobaczeń, odczyt listy) —
    z czasem, operacją i celem. Danych biometrycznych NIGDY nie wysyłamy do chmury.

Trwały plik flagi jest poza repo (`runtime/`) — nie kasuje się przy restarcie usługi.
"""

from __future__ import annotations

import json
import os
import time

from .. import config


def _off_path():
    return os.path.join(str(config.RUNTIME_DIR), "vision_watch.off")


def audit_path():
    return os.path.join(str(config.LOGS_DIR), "biometria_audit.jsonl")


def watch_off():
    """True = nasłuch wyłączony (twardo)."""
    try:
        return os.path.isfile(_off_path())
    except OSError:
        return False


def set_watch_off(on):
    """Ustawia trwały stan nasłuchu. Zwraca nowy stan (True = wyłączony)."""
    p = _off_path()
    if on:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(str(int(time.time())))
        except OSError:
            pass
        return True
    try:
        os.remove(p)
    except OSError:
        pass
    return False


def audit(action, target="", note=""):
    """Dopisuje wpis audytu dostępu do biometrii (append-only). Best-effort."""
    row = {"ts": round(time.time(), 3), "action": str(action), "target": str(target),
           "note": str(note)}
    try:
        os.makedirs(os.path.dirname(audit_path()), exist_ok=True)
        with open(audit_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def audit_tail(limit=50):
    """Ostatnie wpisy audytu (najnowsze pierwsze)."""
    try:
        with open(audit_path(), encoding="utf-8") as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
    except (OSError, ValueError):
        return []
    return list(reversed(rows))[: max(0, int(limit))]


def status_line():
    return (f"nasłuch kamery={'wyłączony' if watch_off() else 'włączony'}, "
            f"audyt biometrii={'on' if os.path.isfile(audit_path()) else 'brak wpisów'}")
