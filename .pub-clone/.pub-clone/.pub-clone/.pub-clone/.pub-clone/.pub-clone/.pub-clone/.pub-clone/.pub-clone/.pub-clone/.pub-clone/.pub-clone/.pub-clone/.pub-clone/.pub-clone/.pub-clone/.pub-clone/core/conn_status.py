"""Realny status łączności przy przełączaniu trybów (2026-09-27).

Wymóg użytkownika: „gotowe / błąd" ma być PRAWDĄ, nie halucynacją. Każdy tryb ma własny,
tani i realny test (bez modelu):
* **offline**  → łańcuch wsparcia `remote_ai`: klucze + sieć + osiągalność dostawcy;
* **komputer** → tunel do PC-Kali: HTTP `/api/tags` na `ASTRO_PC_URL`;
* **premium**  → OpenCode Go: klucz + **realne wywołanie** (1 token).

Dodatkowo sprawdzamy sieć (aktywna karta Wi-Fi / trasa domyślna / realny connect), żeby
odróżnić „dostawca padł" od „w ogóle nie ma sieci".
"""

import os
import socket
import time
import urllib.parse

from .. import config

# Komunikaty dokładnie wg specyfikacji użytkownika.
MESSAGES = {
    "offline": {
        "ok": "Status support - gotowe.",
        "err": "Status support - błąd: żaden dostawca (remote_ai) nie jest podłączony.",
    },
    "komputer": {
        "ok": "Status komputer - gotowe.",
        "err": "Status komputer - błąd: komputer nie jest podłączony.",
    },
    "premium": {
        "ok": "Status premium - gotowe.",
        "err": "Status premium - błąd: opencode nie działa.",
    },
}

_NET_CACHE = {"ts": 0.0, "ok": False}
_NET_TTL = 10.0


def network_ok(timeout=1.5, ttl=None):
    """Realna sieć: aktywna karta Wi-Fi albo trasa domyślna, albo realny connect do IP:port."""
    ttl = _NET_TTL if ttl is None else float(ttl)
    now = time.time()
    if now - _NET_CACHE["ts"] < ttl:
        return _NET_CACHE["ok"]
    ok = False
    try:
        from .. import wifi
        if wifi.active_ssid():
            ok = True
        elif getattr(wifi, "_has_default_route", lambda: False)():
            ok = True
    except Exception:
        ok = False
    if not ok:
        for host, port in (("1.1.1.1", 53), ("8.8.8.8", 53), ("1.1.1.1", 443)):
            try:
                socket.create_connection((host, port), timeout=timeout).close()
                ok = True
                break
            except Exception:
                continue
    _NET_CACHE.update(ts=now, ok=ok)
    return ok


def _host_ok(url, timeout=1.5):
    try:
        host = urllib.parse.urlsplit(url or "").hostname
        if not host:
            return False
        socket.create_connection((host, 443), timeout=timeout).close()
        return True
    except Exception:
        return False


def pc_ok(url=None):
    """Realny test tunelu/Ollamy na PC-Kali (`/api/tags` przez ASTRO_PC_URL)."""
    try:
        from .. import remote_support as rs
        return bool(rs._pc_online(url or config.PC_URL))
    except Exception:
        return False


def skynet_ok(host=None, timeout=1.5):
    """Realny test stałego tunelu do Pi4 „skynet" (lokalny port -> Pi4 SSH).

    Adres lokalnego końca tunelu: `ASTRO_SKYNET_SSH` (domyślnie `127.0.0.1:2200`)."""
    target = host or os.environ.get("ASTRO_SKYNET_SSH", "127.0.0.1:2200")
    try:
        h, _, p = target.partition(":")
        socket.create_connection((h or "127.0.0.1", int(p or 2200)), timeout=timeout).close()
        return True
    except Exception:
        return False


def _probe(provider, timeout=6):
    """Realne wywołanie dostawcy (1 token) — HTTP 200 = działa (auth/limit poprawne)."""
    from .. import remote_support as rs
    payload = {"model": provider.model,
               "messages": [{"role": "user", "content": "ping"}],
               "max_tokens": 1, "stream": False}
    old = provider.timeout
    provider.timeout = timeout
    try:
        rs._post_full(provider, payload)
        return True
    except Exception:
        return False
    finally:
        provider.timeout = old


def remote_ok(probe=False, timeout=6):
    """Łańcuch wsparcia remote_ai: klucze + sieć (+ realny 1-token, gdy `probe`)."""
    if not getattr(config, "REMOTE_ENABLED", False):
        return False
    try:
        from .. import remote_support as rs
        chain = [p for p in rs.provider_chain(include_pc=False) if p.ready()]
    except Exception:
        return False
    if not chain:
        return False
    if not network_ok():
        return False
    if probe:
        return any(_probe(p, timeout) for p in chain[:3])
    return any(_host_ok(p.url) for p in chain[:3])


def opencode_ok(probe=True, timeout=8):
    """OpenCode Go: klucz obecny + (domyślnie) realne wywołanie 1 tokena."""
    try:
        from .. import remote_support as rs
        chain = rs.opencode_chain()
    except Exception:
        return False
    if not chain:
        return False
    if not network_ok():
        return False
    if probe:
        return any(_probe(p, timeout) for p in chain[:2])
    return _host_ok(chain[0].url)


def snapshot(deep=False):
    """Wszystkie czynniki: sieć / komputer (tunel) / remote_ai / opencode / Pi4 skynet."""
    return {
        "network": network_ok(),
        "pc": pc_ok(),
        "remote": remote_ok(probe=deep),
        "opencode": opencode_ok(probe=deep),
        "skynet": skynet_ok(),
    }


def snapshot_text(deep=False):
    s = snapshot(deep=deep)
    mark = lambda ok: "OK" if ok else "brak"  # noqa: E731
    return (f"sieć={mark(s['network'])} komputer={mark(s['pc'])} "
            f"remote_ai={mark(s['remote'])} opencode={mark(s['opencode'])} "
            f"skynet={mark(s['skynet'])}")


def mode_ok(mode, probe=None):
    """Czy zaplecze trybu jest realnie gotowe (bez modelu, nie halucynacja)."""
    mode = (mode or "").strip().lower()
    if mode == "offline":
        return remote_ok(probe=bool(probe))
    if mode == "komputer":
        return pc_ok()
    if mode == "premium":
        return opencode_ok(probe=True if probe is None else bool(probe))
    return False


def mode_status(mode, probe=None):
    """Zdanie statusu dla trybu (dokładne komunikaty użytkownika)."""
    m = (mode or "").strip().lower()
    if m not in MESSAGES:
        return ""
    return MESSAGES[m]["ok" if mode_ok(m, probe=probe) else "err"]


def mode_reply(mode):
    """Pełna zapowiedź głosowa: tryb + realny status + (gdy błąd) praca lokalna."""
    from ..backends import modes as modes_mod
    m = (mode or "").strip().lower()
    if m not in MESSAGES:
        return modes_mod.announce(m)
    ok = mode_ok(m)
    status = MESSAGES[m]["ok" if ok else "err"]
    parts = [modes_mod.announce(m), status]
    if not network_ok():
        parts.insert(0, "Brak sieci Wi-Fi.")
    if not ok and m in (modes_mod.KOMPUTER, modes_mod.PREMIUM):
        parts.append("Pracuję lokalnie.")
    return " ".join(p for p in parts if p)


__all__ = ["network_ok", "pc_ok", "skynet_ok", "remote_ok", "opencode_ok", "snapshot",
           "snapshot_text", "mode_ok", "mode_status", "mode_reply", "MESSAGES"]
