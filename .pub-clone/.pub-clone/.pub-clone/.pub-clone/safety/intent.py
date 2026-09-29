"""SWITCH intencji: KOMENDA WYKONYWALNA vs PYTANIE/TEORIA/ROZMOWA.

Zasada nadrzędna (decyzja użytkownika, 2026-09-20) — rozstrzyga PIERWSZE słowo wypowiedzi:

  * KOMENDA WYKONYWALNA (zadanie na systemie/plikach) zaczyna się słownie od czasownika
    rozkazującego: uruchom / włącz / wyłącz / pokaż / wyświetl / oblicz / formatuj / kopiuj /
    przenies / resetuj / znajdź / wyszukaj / raportuj ... (`EXEC_VERBS`).
  * PYTANIE / rozmowa / analiza TEORETYCZNA zaczyna się od słowa pytającego lub frazy:
    powiedz co to / co to jest / dlaczego / czemu / z jakiego powodu / dokonaj analizy /
    jaki / jaka / jakie / czy / gdzie / kiedy / ile ... (`QUESTION_WORDS`, `QUESTION_PHRASE_RE`).
  * DOMYŚLNA REGUŁA BEZPIECZEŃSTWA: komend wykonywalnych **nigdy** nie wysyłamy do modelu
    zdalnego (remote potrafi „opowiedzieć teorię" zamiast wykonać). Patrz `is_executable_command`.

Kontekst (przyszłość): `classify_intent(text, history=...)` przyjmuje historię tur; krótkie,
niejednoznaczne kontynuacje dziedziczą etykietę poprzedniej tury. Dziś to konserwatywny
mechanizm wspomagający — pełne rozumienie kontekstu jest rozwijane etapami.
"""

import re

from . import verbs
from .normalize import (
    CLS_CHAT,
    CLS_IMPERATIVE,
    CLS_POLITE_CMD,
    CLS_QUESTION_START,
    CLS_THEORY,
    normalize_facts,
)

# --- 1) czasowniki wykonawcze (pierwsze słowo = komenda do wykonania) -------------------------
# Definicja w jednym miejscu: `safety/verbs.py` (C7).
EXEC_VERBS = verbs.EXEC_FIRST

# --- 2) słowa pytające (pierwsze słowo = pytanie / rozmowa) -----------------------------------
QUESTION_WORDS = frozenset({
    "co", "czym", "czemu", "czego", "jak", "jaki", "jaka", "jakie", "jakim", "jakich", "jakiego",
    "czy", "gdzie", "kiedy", "dlaczego", "ile", "kto", "kim", "czyj", "czyja", "czyje",
    "skad", "ktory", "ktora", "ktore", "po",
})

# Czasowniki „teoretyczne" (pierwsze słowo = pytanie/analiza, nie wykonanie).
THEORY_VERBS = frozenset({
    "wyjasnij", "wytlumacz", "zdefiniuj", "opowiedz", "scharakteryzuj", "omow",
    "przeanalizuj", "analizuj", "porownaj", "uzasadnij", "ocen", "skomentuj",
})

# --- 3) wielowyrazowe otwarcia pytań / teorii ------------------------------------------------
QUESTION_PHRASE_RE = re.compile(
    r"^\s*(?:"
    r"powiedz\s+(?:mi\s+)?(?:co|jak|dlaczego|czemu|gdzie|kiedy)|"
    r"co\s+to(?:\s+jest|\s+znaczy)?|czym\s+(?:jest|sa|byly|byly)|"
    r"do\s+czego\s+(?:sluzy|służy)|na\s+co\s+(?:sluzy|służy)|"
    r"z\s+jakiego\s+powodu|z\s+jakiej\s+przyczyny|w\s+jakim\s+celu|"
    r"dokonaj\s+analiz|zrob\s+analiz|przeprowadz\s+analiz|"
    r"jaka\s+(?:jest\s+)?roznica|jaka\s+roznica|czym\s+sie\s+rozni|"
    r"jak\s+sie\s+(?:ma|masz|czujesz|nazywa))",
    re.I)

# Teoria „wtrącona" do komendy (np. „pokaż mi jak działa DNS") — komenda jednak jest pytaniem.
THEORY_INLINE_RE = re.compile(
    r"\bjak\s+(?:to\s+)?(?:zrobic|dziala|dzialaja|sie\s+robi|sie\s+uzywa|"
    r"zainstalowac|skonfigurowac|uruchomic|naprawic|ustawic|podlaczyc|działa)\b"
    r"|\bco\s+to\s+(?:jest|znaczy)\b|\bdlaczego\b|\bczemu\b|\broznica\b|\bporowna\w*\b",
    re.I)


def _first_word(low):
    match = re.match(r"\s*([a-z0-9]+)", low or "")
    return match.group(1) if match else ""


def _is_theory_start(low, first):
    if first in THEORY_VERBS:
        return True
    return bool(QUESTION_PHRASE_RE.match(low))


def _looks_execcommand(low, first):
    return first in EXEC_VERBS and not THEORY_INLINE_RE.search(low)


def _context_hint(low, history):
    """Konserwatywne dziedziczenie etykiety z kontekstu (przyszłość, etapami).

    Krótka wypowiedź bez własnego znacznika (brak czasownika wykonawczego i słowa pytającego)
    dziedziczy etykietę poprzedniej tury, jeśli była komendą. Dzięki temu „teraz to samo na
    dysku" po komendzie pozostaje komendą, a nie pytaniem do chmury.
    """
    if not history:
        return None
    last = None
    for item in reversed(list(history)):
        label = item.get("label") if isinstance(item, dict) else None
        text = item.get("text") if isinstance(item, dict) else item
        if label:
            last = label
            break
        if text:
            last = classify_intent(text)
            break
    if last not in ("command", "question", "chat"):
        return None
    tokens = re.findall(r"[a-z0-9]+", low or "")
    if len(tokens) > 8:
        return None
    return last


def classify_intent(text, history=None):
    """Zwraca 'command' | 'question' | 'chat' | 'unknown'.

    Kolejność jest istotna: najpierw rozstrzyga PIERWSZE słowo (czasownik wykonawczy vs słowo
    pytające), dopiero potem heurystyki treściowe i kontekst.
    """
    raw = (text or "").strip()
    if not raw:
        return "unknown"
    low = normalize_facts(raw)
    first = _first_word(low)

    # 1) jednoznaczne otwarcie teoretyczne/pytające (ma priorytet nad pojedynczym słowem)
    if _is_theory_start(low, first):
        return "question"

    # 2) czasownik wykonawczy na początku -> komenda (chyba że wtrącono teorię)
    if _looks_execcommand(low, first):
        return "command"

    # 3) słowo pytające na początku -> pytanie
    if first in QUESTION_WORDS:
        return "question"

    # 4) teoria / small-talk gdziekolwiek w treści
    if CLS_THEORY.search(low) or CLS_CHAT.search(low):
        return "question"

    # 5) uprzejme polecenie („czy możesz uruchomić...")
    if CLS_POLITE_CMD.search(low):
        return "command"

    # 6) pytajnik albo ogólny wzór pytania
    if raw.rstrip().endswith("?") or CLS_QUESTION_START.search(low):
        return "question"

    # 7) czasownik imperatywny gdziekolwiek (np. „a teraz zaktualizuj pakiety")
    if CLS_IMPERATIVE.search(low):
        return "command"

    # 8) kontekst poprzedniej tury (krótkie kontynuacje)
    hint = _context_hint(low, history)
    if hint:
        return hint

    return "unknown"


def is_executable_command(text):
    """True tylko dla realnych komend — wyznacznik bramki „nigdy do remote"."""
    return classify_intent(text) == "command"


__all__ = [
    "EXEC_VERBS", "QUESTION_WORDS", "THEORY_VERBS", "QUESTION_PHRASE_RE", "THEORY_INLINE_RE",
    "classify_intent", "is_executable_command",
]
