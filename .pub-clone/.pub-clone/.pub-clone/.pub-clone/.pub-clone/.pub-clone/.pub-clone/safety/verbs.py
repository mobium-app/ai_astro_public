"""Jedno źródło prawdy: słownictwo czasowników KOMEND (C7, 2026-09-26).

Wcześniej listy czasowników „co jest komendą" były rozsiane w 5 miejscach
(`safety/intent.EXEC_VERBS`, `safety/normalize.CLS_IMPERATIVE`/`CLS_POLITE_CMD`,
`core/fast_tools.MUTATE_RE`, `safety/plans.RUN_GOAL_RE`/`SETUP_GOAL_RE`) — łatwo było je
rozjechać. Teraz definicje żyją tutaj, a moduły budują z nich swoje wyrażenia (zachowanie 1:1).

Rozróżniamy celowo:
  * `EXEC_FIRST`     — tryb rozkazujący, rozstrzyga „pierwsze słowo" (SWITCH intencji),
  * `IMPERATIVE_ANY` — tryb rozkazujący gdziekolwiek w zdaniu,
  * `POLITE_INFINITIVE` — bezokoliczniki po zwrocie grzecznościowym („czy możesz …"),
  * `MUTATE`         — czasowniki zmieniające system (fast-path nie może ich przechwycić),
  * `RUN_GOAL` / `SETUP_GOAL` — cele planów (uruchomienie vs instalacja/konfiguracja).
"""

import re

# 1) Pierwsze słowo = komenda do wykonania (safety/intent.EXEC_VERBS).
EXEC_FIRST = frozenset({
    # ruch / system
    "uruchom", "odpal", "wykonaj", "zainstaluj", "odinstaluj", "zaktualizuj", "uaktualnij",
    "aktualizuj", "odswiez", "zrestartuj", "restartuj", "zresetuj", "resetuj", "zatrzymaj",
    "wlacz", "wylacz", "zamknij", "otworz", "zablokuj", "wyloguj", "aktywuj", "dezaktywuj",
    "polacz", "rozlacz", "skonfiguruj", "napraw", "wykryj", "monitoruj", "wyczysc",
    # pliki / dane / pokazywanie
    "pokaz", "wyswietl", "wypisz", "wylistuj", "pokazuj", "podaj", "raportuj", "sprawdz",
    "odczytaj", "przeczytaj", "znajdz", "wyszukaj", "przeszukaj", "kopiuj", "skopiuj",
    "przenies",
    "usun", "utworz", "zrob", "zmien", "ustaw", "dodaj", "dopisz", "zapisz", "pobierz",
    "sciagnij", "wyslij", "przeslij", "udostepnij", "wgraj", "sformatuj", "formatuj",
    "zainicjuj", "zaindeksuj", "zabezpiecz", "zarchiwizuj", "spakuj", "rozpakuj", "wypakuj",
    # liczenie / generowanie
    "oblicz", "policz", "przelicz", "podsumuj", "zsumuj", "wygeneruj", "opracuj", "sporzadz",
    "przygotuj", "stworz", "napisz", "nagraj", "odtworz", "zgeneruj",
    # dźwięk
    "zwieksz", "zmniejsz", "wycisz", "podglosn", "przycisz",
})

# 2) Tryb rozkazujący gdziekolwiek w zdaniu (safety/normalize.CLS_IMPERATIVE).
IMPERATIVE_ANY = frozenset({
    "zainstaluj", "odinstaluj", "uruchom", "odpal", "wykonaj", "otworz", "zamknij",
    "zrestartuj", "restartuj", "zatrzymaj", "wlacz", "wylacz", "pobierz", "sciagnij",
    "skopiuj", "przenies", "usun", "utworz", "zmien", "ustaw", "dodaj", "dopisz", "zapisz",
    "zaktualizuj", "uaktualnij", "aktualizuj", "odswiez", "wyslij", "przeslij", "udostepnij",
    "zablokuj", "wyloguj", "aktywuj", "dezaktywuj", "przeczytaj", "odczytaj", "sprawdz",
    "pokaz", "wyswietl", "polacz", "rozlacz", "skonfiguruj", "napraw", "wykryj", "monitoruj",
    "wyczysc", "policz", "oblicz", "przelicz", "zwieksz", "zmniejsz", "wycisz", "podglosn",
    "przycisz", "przygotuj", "wygeneruj", "opracuj", "sporzadz",
})

# 3) Bezokoliczniki po zwrocie grzecznościowym (safety/normalize.CLS_POLITE_CMD).
POLITE_INFINITIVE = frozenset({
    "zainstalowac", "uruchomic", "otworzyc", "pobrac", "wyslac", "skopiowac", "usunac",
    "zmienic", "ustawic", "dodac", "zaktualizowac", "sprawdzic", "pokazac", "wyswietlic",
    "zrestartowac", "wlaczyc", "wylaczyc", "przeczytac", "zapisac", "podlaczyc",
    "skonfigurowac", "naprawic", "wykryc", "wyczyscic",
})

# 4) Czasowniki ZMIENIAJĄCE system (core/fast_tools.MUTATE_RE) — sufiksu `\w*` dokłada regex.
MUTATE = frozenset({
    "zainstaluj", "odinstaluj", "zaktualizuj", "uaktualnij", "aktualizuj", "odswiez", "upgrade",
    "skonfiguruj", "napraw", "uruchom", "odpal", "wlacz", "wylacz", "zrestartuj", "restartuj",
    "restart", "reset", "resetuj", "zresetuj", "zatrzymaj", "utworz", "usun", "zmien", "ustaw",
    "dodaj", "dopisz", "zapisz", "pobierz", "sciagnij", "wyslij", "kopiuj", "skopiuj",
    "przenies", "formatuj", "sformatuj", "wyczysc", "zainicjuj", "zabezpiecz",
})

# 5) Cele planów (safety/plans.RUN_GOAL_RE / SETUP_GOAL_RE) — sufiksu `\w*` dokłada regex.
RUN_GOAL = ("uruchom", "uruchomic", "odpal", "otworz", "otworzyc", "wlacz", "wystartuj", "start")
SETUP_GOAL = ("zainstaluj", "odinstaluj", "skonfiguruj", "napraw", "zaktualizuj", "aktualizuj",
              "uaktualnij", "podlacz", "wykryj", "sterownik")

_POLITE_LEAD = (r"(?:czy\s+)?(?:mozesz|moglbys|moglabys|chcialbym|chcialabym|prosze|poprosze)")


def _alt(words):
    """Alternacja z escapowaniem; dłuższe frazy przed krótszymi (bezpieczniej przy `\\w*`)."""
    return "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))


def imperative_re():
    return re.compile(r"\b(?:" + _alt(IMPERATIVE_ANY) + r")\b", re.I)


def polite_cmd_re():
    return re.compile(r"\b" + _POLITE_LEAD + r"\b[^.!?]{0,40}?\b(?:"
                      + _alt(POLITE_INFINITIVE) + r")\b", re.I)


def mutate_re():
    # `aktualizacj\w*` osobno (jak w oryginale), reszta + `\w*`.
    return re.compile(r"\b(?:" + _alt(MUTATE) + r"|aktualizacj\w*)\w*")


def run_goal_re():
    return re.compile(r"\b(?:" + _alt(RUN_GOAL) + r")\w*\b", re.I)


def setup_goal_re():
    return re.compile(r"\b(?:" + _alt(SETUP_GOAL) + r")\w*\b", re.I)


__all__ = ["EXEC_FIRST", "IMPERATIVE_ANY", "POLITE_INFINITIVE", "MUTATE", "RUN_GOAL",
           "SETUP_GOAL", "imperative_re", "polite_cmd_re", "mutate_re", "run_goal_re",
           "setup_goal_re"]
