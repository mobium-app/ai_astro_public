"""Tryby pracy ASTRO (offline / komputer / premium) — trwały profil routingu backendów.

Przełączanie głosowe („tryb offline"/„tryb oflajn", „tryb komputer", „tryb premium") zmienia
TYLKO kolejność backendów per rodzaj zadania (`ORDERS`). Komendy wykonawcze i tak zawsze zostają
lokalne (twarda zasada `local_only` w rejestrze), więc tryb nie może wysłać zlecenia do chmury.

Stan jest trwały w `config.MODE_FILE` (JSON) i przeżywa restart usługi. Odczyt cache'ujemy po
mtime pliku, więc kolejne tury nie dotykają dysku.

Auto-degradacja: kolejność każdego trybu zawiera dalsze poziomy (CPU/NPU), a rejestr pomija
backendy niegotowe — brak PC/sieci schodzi więc płynnie na tryb lokalny bez osobnej logiki.
"""

import json
import os
import time
from datetime import datetime

from .. import config

OFFLINE = "offline"
KOMPUTER = "komputer"
PREMIUM = "premium"
ALL = (OFFLINE, KOMPUTER, PREMIUM)

# Zapowiedź głosowa po przełączeniu (wymóg użytkownika 2026-09-26): wyraźny komunikat.
ANNOUNCE = {
    OFFLINE: "Uruchamiam tryb offline.",
    KOMPUTER: "Uruchamiam tryb komputer.",
    PREMIUM: "Uruchamiam tryb premium.",
}

LABELS = {
    OFFLINE: "Tryb Offline",
    KOMPUTER: "Tryb Komputer",
    PREMIUM: "Tryb Premium",
}

# Kolejność backendów per tryb i rodzaj zadania (nazwy z rejestru backendów).
# Pierwszy GOTOWY wygrywa; kolejne pozycje to awaryjny fallback. Uwaga: PC-MAX (16 GB) jest
# świadomie pominięty (decyzja 2026-09-26) — tryb „komputer" celuje w PC-Kali (bielik-11b).
ORDERS = {
    OFFLINE: {
        "chat": ["cpu", "npu", "pc", "remote"],
        "tools": ["cpu_fast", "cpu", "pc", "remote"],
        "json": ["cpu_fast", "cpu", "pc", "remote"],
        "plan": ["cpu_fast", "cpu", "pc", "remote"],
        "embed": ["cpu", "pc", "remote"],
        "heavy": ["pc", "cpu", "remote"],
        "fresh": ["remote", "cpu", "pc"],
    },
    KOMPUTER: {
        "chat": ["pc", "cpu", "npu", "remote"],
        "tools": ["pc", "cpu_fast", "cpu", "remote"],
        "json": ["pc", "cpu_fast", "cpu", "remote"],
        "plan": ["pc", "cpu_fast", "cpu", "remote"],
        "embed": ["cpu", "pc", "remote"],
        "heavy": ["pc", "cpu", "remote"],
        "fresh": ["pc", "remote", "cpu"],
    },
    PREMIUM: {
        "chat": ["premium", "pc", "cpu", "npu"],
        "tools": ["premium", "pc", "cpu_fast", "cpu"],
        "json": ["premium", "pc", "cpu_fast", "cpu"],
        "plan": ["premium", "pc", "cpu_fast", "cpu"],
        "embed": ["cpu", "pc", "premium"],
        "heavy": ["premium", "pc", "cpu"],
        "fresh": ["premium", "pc", "cpu"],
    },
}

_cache = {"key": None, "mtime": None, "mode": ""}


def _read_file():
    try:
        with open(config.MODE_FILE, encoding="utf-8") as fh:
            mode = (json.load(fh) or {}).get("mode", "")
        return mode if mode in ALL else ""
    except Exception:
        return ""


def get_mode():
    """Aktywny tryb (cache po mtime); brak pliku = `config.MODE_DEFAULT` (offline)."""
    path = str(config.MODE_FILE)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if _cache["key"] == path and _cache["mtime"] == mtime:
        return _cache["mode"]
    mode = _read_file() or (config.MODE_DEFAULT if config.MODE_DEFAULT in ALL else OFFLINE)
    _cache.update(key=path, mtime=mtime, mode=mode)
    return mode


def set_mode(mode):
    """Ustawia tryb i zapisuje trwale. Zwraca nazwę trybu albo "" dla nieznanego."""
    mode = (mode or "").strip().lower()
    if mode not in ALL:
        return ""
    try:
        config.ensure_dirs()
        tmp = str(config.MODE_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"mode": mode, "ts": time.time()}, fh, ensure_ascii=False)
        os.replace(tmp, config.MODE_FILE)
    except Exception:
        pass
    _cache.update(key=str(config.MODE_FILE), mtime=None, mode=mode)
    return mode


def order_for(kind, mode=None):
    """Kolejność nazw backendów dla rodzaju zadania w danym trybie."""
    mode = mode or get_mode()
    table = ORDERS.get(mode) or ORDERS[OFFLINE]
    names = table.get(kind) or ORDERS[OFFLINE].get(kind) or ORDERS[OFFLINE]["chat"]
    if kind == "chat" and mode == OFFLINE and config.NPU_CHAT:
        # Zachowanie E5: `ASTRO_NPU_CHAT=1` przywraca NPU-first tylko w trybie offline.
        return ["npu", "cpu", "pc", "remote"]
    return list(names)


def label(mode=None):
    return LABELS.get(mode or get_mode(), "")


def announce(mode=None):
    return ANNOUNCE.get(mode or get_mode(), "")


# --- dzienny budżet trybu premium (OpenCode Go) ---------------------------------------------
_budget_cache = {"ts": 0.0, "tokens": 0, "requests": 0}


def premium_spend_today(now=None, ttl=30.0):
    """Zużycie OpenCode (tokeny, liczba requestów) od początku dnia lokalnego.

    Liczone z `logs/remote_usage.jsonl`; wynik cache'owany przez `ttl` s (wołane co turę)."""
    now = time.time() if now is None else now
    if now - _budget_cache["ts"] < ttl:
        return _budget_cache["tokens"], _budget_cache["requests"]
    day = datetime.fromtimestamp(now).date()
    tokens = requests = 0
    path = getattr(config, "LOGS_DIR", None)
    try:
        with open(os.path.join(str(path), "remote_usage.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("provider") != "opencode":
                    continue
                try:
                    ts = float(entry.get("ts") or 0)
                except (TypeError, ValueError):
                    continue
                if datetime.fromtimestamp(ts).date() != day:
                    continue
                tokens += int(entry.get("total") or 0)
                requests += 1
    except OSError:
        pass
    _budget_cache.update(ts=now, tokens=tokens, requests=requests)
    return tokens, requests


def premium_budget_ok(now=None):
    """True, gdy wolno jeszcze użyć backendu `premium` (0 = brak limitu)."""
    tok_cap = int(getattr(config, "PREMIUM_DAILY_TOKENS", 0) or 0)
    req_cap = int(getattr(config, "PREMIUM_DAILY_REQUESTS", 0) or 0)
    if tok_cap <= 0 and req_cap <= 0:
        return True
    tokens, requests = premium_spend_today(now)
    if tok_cap > 0 and tokens >= tok_cap:
        return False
    if req_cap > 0 and requests >= req_cap:
        return False
    return True


def status_line():
    """Jednolinijkowy status: tryb + (dla premium) dzienne zużycie/limit."""
    mode = get_mode()
    line = f"{LABELS.get(mode, mode)} ({mode})"
    if mode == PREMIUM:
        tokens, requests = premium_spend_today()
        tok_cap = int(getattr(config, "PREMIUM_DAILY_TOKENS", 0) or 0)
        req_cap = int(getattr(config, "PREMIUM_DAILY_REQUESTS", 0) or 0)
        cap = []
        if tok_cap > 0:
            cap.append(f"{tokens}/{tok_cap} tok")
        if req_cap > 0:
            cap.append(f"{requests}/{req_cap} req")
        if cap:
            line += " | premium dziś: " + ", ".join(cap)
            if not premium_budget_ok():
                line += " (limit wyczerpany → lokalnie)"
    return line


__all__ = ["OFFLINE", "KOMPUTER", "PREMIUM", "ALL", "ANNOUNCE", "LABELS", "ORDERS",
           "get_mode", "set_mode", "order_for", "label", "announce",
           "premium_spend_today", "premium_budget_ok", "status_line"]
