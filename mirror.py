"""Mirror pracy ASTRO na terminale: zalogowane sesje SSH/konsola oraz (opcjonalnie) VT.

Port z Ateny (`wall_write`/`mirror_tty`): każda wypowiedź i każda komenda systemowa ma być
widoczna we wszystkich aktywnych sesjach. Bez roota piszemy do własnych tty; do nieaktywnych
VT i `/dev/console` piszemy przez `sudo -n` (tekst przekazywany przez środowisko — bez injection).
"""

import os
import subprocess
import time

from . import config

_TTY_CACHE = {"t": 0.0, "paths": []}
# Wartości prywatne (np. adres z profilu) maskowane we WSZYSTKICH lustrzanych zapisach.
_REDACTIONS = {"values": []}
# Dedup/throttling (C5): nie powtarzaj identycznej treści w krótkim oknie (mniej zapisów do VT).
_LAST = {"msg": None, "ts": 0.0}


def set_redactions(values):
    """Ustawia listę wartości prywatnych, które nigdy nie mogą wyciec na terminal/SSH."""
    _REDACTIONS["values"] = [str(v) for v in (values or []) if v and len(str(v)) >= 3]


def redact(text):
    out = str(text or "")
    for v in sorted(_REDACTIONS["values"], key=len, reverse=True):
        out = out.replace(v, "[prywatne]")
    return out


def logged_in_ttys():
    """Ścieżki terminali zalogowanych sesji (konsola ttyN, SSH pts/N)."""
    paths = []
    try:
        out = subprocess.run(["who", "-s"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return paths
    for line in out.splitlines():
        for tok in line.split():
            # Kolumny `who` bywają różne (użytkownik, typ, tty...) — szukamy tokenu terminala.
            if tok.startswith("tty") or tok.startswith("pts/"):
                paths.append("/dev/" + tok)
                break
    return paths


def cached_ttys(ttl=5):
    now = time.time()
    if now - _TTY_CACHE["t"] > ttl:
        _TTY_CACHE["paths"] = logged_in_ttys()
        _TTY_CACHE["t"] = now
    return _TTY_CACHE["paths"]


def all_vt_paths():
    return [f"/dev/tty{n}" for n in range(1, 64)] + ["/dev/console"]


def _sudo_wall(msg, paths):
    script = 'for t in "$@"; do [ -c "$t" ] && printf "%s" "$MSG" >> "$t" 2>/dev/null; done'
    try:
        env = dict(os.environ, MSG=msg)
        subprocess.run(["sudo", "-n", "bash", "-c", script, "astro-mirror"] + paths,
                       capture_output=True, timeout=5, env=env)
    except Exception:
        pass


def enabled():
    return bool(getattr(config, "MIRROR", True))


def wall_write(text, skip=None):
    """Pisze tekst na wszystkie terminale (zalogowane sesje + VT, jeśli włączone)."""
    if not enabled() or not text:
        return
    msg = redact(text).rstrip() + "\n"
    now = time.time()
    dedup = float(getattr(config, "MIRROR_DEDUP_S", 0.8))
    if dedup > 0 and msg == _LAST["msg"] and (now - _LAST["ts"]) < dedup:
        return
    _LAST["msg"], _LAST["ts"] = msg, now
    skip_real = os.path.realpath(skip) if skip else None
    targets, seen = [], set()
    pool = list(cached_ttys())
    if getattr(config, "MIRROR_VT", True):
        vts = all_vt_paths()
        cap = int(getattr(config, "MIRROR_VT_MAX", 64))
        pool += (vts[:max(0, cap)] if cap > 0 else vts)
    for path in pool:
        rp = os.path.realpath(path)
        if skip_real and rp == skip_real:
            continue
        if rp in seen:
            continue
        seen.add(rp)
        targets.append(path)
    if not targets:
        return
    failed = []
    for path in targets:
        try:
            with open(path, "a") as fh:
                fh.write(msg)
        except Exception:
            failed.append(path)
    if failed:
        _sudo_wall(msg, failed)


def reply(text, prefix="[ASTRO]"):
    wall_write(f"{prefix} {text}" if prefix else text)


def command(cmd, out="", code=None, root=False):
    """Pokazuje komendę, jej wynik i kod na terminalach (`[bash]`)."""
    prefix = "root$ " if root else "$ "
    wall_write("[bash] " + prefix + cmd)
    if out:
        wall_write(str(out)[:4000])
    if code is not None:
        wall_write(f"[bash] (kod {code})")
