"""Kontekst trwały (P4, 2026-09-27): dzienne skróty + archiwum `.md` + stały blok startowy.

Dlaczego nie wstrzykujemy surowej historii inline: prefill na CPU Pi 5 (qwen2.5:7b) to
~7 tok/s, więc 7 dni rozmowy (~64k tok) to ~2,4 h liczenia — nie do przyjęcia. Zamiast tego:

* **archiwum** — każdy dzień zapisujemy jako `runtime/context/RRRR-MM-DD.md` (dźwięk→tekst,
  do wglądu, backupu i retrieval offline);
* **digest** — zwięzły skrót dnia z `session_turns` → tabela `context_digests` (przeżywa prune
  surowych tur i restart);
* **blok startowy** — ostatnie N dni jako ZWIĘZŁY, STAŁY tekst. Wstawiany tuż za promptem
  systemowym, więc prefiks jest byte-identyczny między turami i Ollama liczy go tylko raz
  (cache prefiksu; pomiar: 2110 tok 289 s → 2,2 s przy trafieniu).

Surowe tury nie trafiają do promptu. Gdy pytasz o szczegóły z przeszłości, właściwą drogą jest
retrieval z `session_turns`/`conversations` (FTS/wektory) — kolejny krok.
"""

import os
import time
from datetime import date, datetime, timedelta

from .. import config

DAY_FMT = "%Y-%m-%d"


def day_key(ts=None):
    """Lokalny dzień (RRRR-MM-DD) dla znacznika czasu (domyślnie teraz)."""
    return datetime.fromtimestamp(time.time() if ts is None else float(ts)).strftime(DAY_FMT)


def _parse_day(day):
    return datetime.strptime(str(day), DAY_FMT)


def _day_bounds(day):
    start = _parse_day(day).timestamp()
    end = (_parse_day(day) + timedelta(days=1)).timestamp()
    return start, end


def day_turns(memory, day):
    """Surowe tury z danego dnia (lokalnie). Pusty przy braku pamięci/błędzie."""
    if memory is None:
        return []
    try:
        start, end = _day_bounds(day)
        return memory.session_turns_between(start, end)
    except Exception:
        return []


def summarize_turns(turns, max_chars=320):
    """Zwięzły skrót dnia: unikalne wypowiedzi użytkownika (bez powtórzeń), obcięte do budżetu."""
    seen = set()
    parts = []
    for turn in turns or []:
        text = (turn.get("user") or "").strip() if isinstance(turn, dict) else ""
        if not text:
            continue
        key = " ".join(text.lower().split())
        if key in seen:
            continue
        seen.add(key)
        parts.append(text if len(text) <= 100 else text[:97] + "...")
    out = "; ".join(parts)
    if len(out) > max_chars:
        out = out[:max_chars - 3].rstrip() + "..."
    return out


def refresh(memory, days=None, today=None):
    """Uzupełnia i zapisuje digesty dla dni z surowymi turami (poza dzisiejszym).

    Zwraca liczbę zapisanych digestów. Idempotentne; ciche (nie rzuca)."""
    if memory is None:
        return 0
    days = int(config.CONTEXT_DAYS if days is None else days)
    today = today or day_key()
    base = _parse_day(today).date()
    saved = 0
    for i in range(1, days + 1):
        day = (base - timedelta(days=i)).strftime(DAY_FMT)
        turns = day_turns(memory, day)
        summary = summarize_turns(turns)
        if not summary:
            continue
        try:
            memory.set_context_digest(day, summary, turns=len(turns))
            saved += 1
        except Exception:
            pass
    return saved


def build_block(memory, days=None, max_chars=None, today=None):
    """Stały blok startowy: ostatnie N dni (digesty) + ostatni wątek rozmowy.

    Pusty, gdy brak danych. Deterministyczny dla danego stanu bazy — wołany raz na proces
    (Agent cache'uje), by prefiks promptu pozostał niezmienny w trakcie sesji."""
    if memory is None:
        return ""
    days = int(config.CONTEXT_DAYS if days is None else days)
    max_chars = int(config.CONTEXT_MAX_CHARS if max_chars is None else max_chars)
    if max_chars <= 0:
        return ""
    today = today or day_key()
    # 1) digesty: najpierw zapisane (szybkie), brakujące policz na bieżąco z surowych tur.
    stored = {}
    try:
        for d in memory.context_digests(limit=days + 2):
            stored[d.get("day")] = d.get("summary") or ""
    except Exception:
        stored = {}
    base = _parse_day(today).date()
    lines = []
    for i in range(1, days + 1):
        day = (base - timedelta(days=i)).strftime(DAY_FMT)
        summary = stored.get(day) or summarize_turns(day_turns(memory, day))
        if summary:
            lines.append(f"{day}: {summary}")
    # 2) ostatni znany wątek (ciągłość między sesjami).
    try:
        summary, _ts = memory.session_summary()
    except Exception:
        summary = ""
    body = "\n".join(lines)
    if summary:
        body = (body + "\n" if body else "") + "Ostatni wątek rozmowy: " + summary
    body = body.strip()
    if not body:
        return ""
    text = ("Kontekst z poprzednich dni (skrót, do ciągłości rozmowy — to NIE są bieżące dane "
            "systemowe; fakty czerp z narzędzi):\n" + body)
    if len(text) > max_chars:
        text = text[:max_chars - 3].rstrip() + "..."
    return text


def export_day(memory, day, out_dir=None):
    """Zapisuje dzień jako czytelny `RRRR-MM-DD.md`. Zwraca ścieżkę albo None."""
    turns = day_turns(memory, day)
    if not turns:
        return None
    out_dir = str(out_dir or config.CONTEXT_DIR)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        return None
    path = os.path.join(out_dir, f"{day}.md")
    lines = [f"# ASTRO — rozmowa {day}", ""]
    for turn in turns:
        ts = datetime.fromtimestamp(turn.get("ts") or 0).strftime("%H:%M")
        if turn.get("user"):
            lines.append(f"- **{ts} ty:** {turn['user']}")
        if turn.get("assistant"):
            lines.append(f"- **{ts} ASTRO:** {turn['assistant']}")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        return None
    return path


def export_recent(memory, days=None, out_dir=None):
    """Mirror `.md` ostatnich N dni + dzisiejszego. Zwraca listę ścieżek."""
    days = int(config.CONTEXT_DAYS if days is None else days)
    today = date.today()
    out = []
    for i in range(days, -1, -1):
        day = (today - timedelta(days=i)).strftime(DAY_FMT)
        path = export_day(memory, day, out_dir)
        if path:
            out.append(path)
    return out


def warm_start(memory, days=None):
    """Start usługi: odśwież digesty + zapisz archiwum `.md`. Ciche; zwraca podsumowanie."""
    if memory is None:
        return {}
    result = {"digests": 0, "files": 0}
    try:
        result["digests"] = refresh(memory, days=days)
    except Exception:
        pass
    try:
        result["files"] = len(export_recent(memory, days=days))
    except Exception:
        pass
    return result
