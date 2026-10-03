"""Filtry jakości nauki (zasada użytkownika, 2026-10-03).

Do bazy `learned` trafiają TYLKO:
  * **idealnie zrozumiane pytania** — kompletne, sensowne, nie tło/śmieci STT
    (`good_question`),
  * **idealnie dobre odpowiedzi** — merytoryczne, bez odmów, bez mieszania języków,
    nie będące głównie pytaniem (`good_answer`).
Dodatkowo pytania ULOTNE (pogoda teraz, godzina, stan/moduł — zmienne w czasie)
są wykluczane z nauki (`volatile_question`).

Moduł czysty (bez modelu/sieci); używany przez `core/agent._learn_premium`
i `scripts/distill_conversations.py`.
"""

import re
from collections import Counter

_Q_START = (
    "co", "czym", "czego", "czemu", "jak", "jaki", "jaka", "jakie", "jakim", "jaką",
    "dlaczego", "czy", "kto", "kogo", "komu", "gdzie", "kiedy", "ile", "który",
    "która", "które", "opowiedz", "wyjaśnij", "podaj", "wymień", "omów", "opisz",
)

# Artefakty STT / tło (samotne słowa-śmieci).
_JUNK_WORDS = {"yyy", "eee", "yyy...", "eee...", "yhm", "hmm", "mhm", "łłł", "ąąą"}

# Frazy odmowy/niepewności w odpowiedzi (nie nadaje się do bazy wiedzy).
_REFUSAL = (
    "nie wiem", "nie rozumiem", "nie mogę", "nie potrafię", "przepraszam", "przykro mi",
    "nie zrozumiałam", "nie mam dostępu", "nie jestem w stanie", "nie znam się",
    "nie udało mi się", "niestety", "jak mogę ci", "w czym mogę pomóc", "czym mogę",
    "nie jestem pewna", "spróbuj proszę", "spróbuj jeszcze raz",
    "przekroczyłam limit",
)

_EN_STOP = (" the ", " and ", " of ", " is ", " are ", " you ", " we ", " it ", " to ",
            " i ", " am ", " not ", " have ", " will ", " can ", " do ", " what ", " how ",
            " why ", " let ", " start ", " clean ", " sorry ", " please ", " my ", " your ")

# Pytania ULOTNE / o stan (nie wiedza trwała).
_VOLATILE = (
    "pogoda", "temperatura", "która godzina", "która jest", "jaki mamy dzień",
    "jaki dziś", "co słychać", "jak się masz", "jak mija", "jak leci",
    "jaki masz tryb", "jaki tryb", "gdzie jesteś", "co robisz", "co robiłaś",
    "stan systemu", "uptime", "status", "ile masz ram", "temperaturę",
)


def _tokens(text):
    return [t for t in re.split(r"[\s,.!?;:()„”\"'\-–—…]+", (text or "").strip()) if t]


def good_question(text):
    """True, gdy pytanie jest kompletne i zrozumiałe (nie tło/śmieć STT)."""
    t = (text or "").strip()
    if len(t) < 15 or len(t) > 400:
        return False
    toks = _tokens(t)
    if len(toks) < 4:
        return False
    low = " " + t.lower() + " "
    if any(f" {w} " in low for w in _JUNK_WORDS):
        return False
    # STT-loopy: to samo słowo (>2 znaki) powtórzone ponad 3 razy.
    counts = Counter(w.lower() for w in toks if len(w) > 2)
    if counts and counts.most_common(1)[0][1] > 3:
        return False
    if "?" in t:
        return True
    head = toks[0].lower()
    return head in _Q_START and len(toks) >= 5


def good_answer(text):
    """True, gdy odpowiedź jest merytoryczna i pełna (bez odmów/pytań/śmieci)."""
    t = (text or "").strip()
    if len(t) < 80 or len(t) > 4000:
        return False
    low = " " + t.lower() + " "
    if any(p in low for p in _REFUSAL):
        return False
    if sum(low.count(w) for w in _EN_STOP) >= 2:
        return False
    # W większości pytanie do użytkownika (np. „Jak mogę Ci pomóc?").
    if t.count("?") > max(1, t.count(".")):
        return False
    if t.count(".") == 0 and t.count("!") == 0 and t.count(",") == 0:
        return False
    return True


def volatile_question(text):
    """True dla pytań ulotnych (pogoda teraz, godzina, stan) — nie zapisywać do wiedzy."""
    low = " " + (text or "").lower() + " "
    return any(v in low for v in _VOLATILE)


def pair_ok(question, answer):
    """Pełna bramka pary (pytanie+odpowiedź) dla nauki i destylacji."""
    return (good_question(question) and good_answer(answer)
            and not volatile_question(question))
