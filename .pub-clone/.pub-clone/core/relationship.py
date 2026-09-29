"""Profil relacji (P3): ile i od kiedy znamy użytkownika — bez nowego stanu.

Korzysta wyłącznie z istniejącej pamięci (`conversations`) i profilu użytkownika, więc nie
wymaga migracji schematu. Daje:
  * `context_line` — krótki blok do kontekstu modelu („Znacie się od N dni, rozmów: M."),
  * `report` — dłuższą, głosową odpowiedź na pytanie „nasza relacja / jak długo się znamy".
Nie ujawnia pól prywatnych ponad to, co i tak trafia do kontekstu (imię z profilu).
"""

import time


def _profile(memory):
    try:
        store = getattr(memory, "profiles", None)
        return store.get() if store is not None else (memory.profile() or {})
    except Exception:
        return {}


def stats(memory):
    """(dni, tury, znacie_sie) — bezpieczne dla braku pamięci/danych."""
    try:
        st = memory.relationship_stats()
    except Exception:
        return 0, 0, False
    turns = int(st.get("turns") or 0)
    first = float(st.get("first_ts") or 0.0)
    days = int((time.time() - first) // 86400) if first else 0
    return max(0, days), turns, turns > 0


def context_line(memory, profile=None):
    """Krótka linia relacji do kontekstu (albo "" gdy brak danych)."""
    days, turns, known = stats(memory)
    if not known:
        return ""
    parts = []
    if days > 0:
        parts.append(f"znacie się od {days} dni")
    else:
        parts.append("pierwsza wspólna sesja")
    parts.append(f"rozmów: {turns}")
    prof = profile if profile is not None else _profile(memory)
    name = (prof or {}).get("preferred_name")
    if name:
        parts.append(f"użytkownik: {name}")
    return "Relacja: " + ", ".join(parts) + "."


def report(agent):
    """Głosowa odpowiedź o relacji; (tekst, route)."""
    memory = getattr(agent, "memory", None)
    days, turns, known = stats(memory)
    if not known:
        return "Dopiero się poznajemy — to nasza pierwsza rozmowa.", "relation"
    prof = _profile(memory)
    name = (prof or {}).get("preferred_name") or ""
    who = f" z {name}" if name else ""
    when = (f"Znamy się od {days} dni" if days > 0 else "To nasza pierwsza wspólna sesja")
    return (f"{when}{who}. Mamy za sobą {turns} wymienionych wypowiedzi. "
            f"Cieszę się, że mogę z Tobą pracować."), "relation"


__all__ = ["stats", "context_line", "report"]