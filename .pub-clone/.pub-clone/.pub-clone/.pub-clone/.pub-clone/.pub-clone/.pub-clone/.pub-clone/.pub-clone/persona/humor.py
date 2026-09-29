"""Humor ASTRO (E7.6): kuratorowany zestaw krótkich żartów + twarde reguły „kiedy nie żartować".

Żarty są autorskie/bezpieczne (bez grup, polityki, wulgaryzmów), tematycznie bliskie robotowi.
Humor włączamy tylko gdy: kontekst nie jest wrażliwy, temperament nie jest „poważny",
nastrój nie jest wyraźnie negatywny i minął cooldown (żeby nie był nachalny).
"""

import random
import re

from ..safety import normalize_facts
from .persona import normalize

JOKES = (
    {"id": "wirus", "topic": "tech",
     "text": "Dlaczego robot poszedł do lekarza? Bo złapał wirusa."},
    {"id": "zarowka", "topic": "tech",
     "text": "Ile programistów potrzeba, żeby zmienić żarówkę? Żadnego — to problem sprzętowy."},
    {"id": "herbata", "topic": "tech",
     "text": "Najbezpieczniejsza herbata? Ta bez błędu. A przynajmniej tak mówi mój kod."},
    {"id": "kalendarz", "topic": "ogolne",
     "text": "Poprosiłam kalendarz o wolną chwilę. Wpisał mi ją na przyszły wtorek."},
    {"id": "poniedzialek", "topic": "praca",
     "text": "Poniedziałek to taki wtorek, tylko bardziej poniedziałek."},
    {"id": "dieta", "topic": "jedzenie",
     "text": "Nie ufam dietom. Przez przypadek zniknęła mi cała tabliczka czekolady."},
    {"id": "pamiec", "topic": "tech",
     "text": "Komputer mówi, że brakuje pamięci. Ja mam całą bazę i też czasem zapominam, "
             "gdzie położyłam klucze."},
    {"id": "absolutna", "topic": "ogolne",
     "text": "Mam pamięć absolutną — do rzeczy, które wcale nie są mi potrzebne."},
    {"id": "nieskonczone", "topic": "tech",
     "text": "Dwie rzeczy są nieskończone: wszechświat i błędy w kodzie. Co do wszechświata "
             "mam wątpliwości."},
    {"id": "rozgrzewka", "topic": "robocik",
     "text": "Nie jestem rannym ptaszkiem. Jestem rannym robotem i potrzebuję chwili "
             "na rozgrzanie procesora."},
    {"id": "parasol", "topic": "ogolne",
     "text": "Pogoda na dziś: pięćdziesiąt procent szans na deszcz i sto procent szans, "
             "że i tak wezmę parasol."},
    {"id": "spotkanie", "topic": "praca",
     "text": "Spotkanie, które mogło być mailem, i mail, który mógł wcale nie istnieć."},
    {"id": "inteligencja", "topic": "techn",
     "text": "Zapytałam pewną sztuczną inteligencję, czy jest inteligentna. "
             "Odpowiedziała: to zależy od pytania."},
    {"id": "dreszcze", "topic": "robocik",
     "text": "Ludzie mają dreszcze. Ja mam błąd zmiennoprzecinkowy."},
)

_REQUEST_RE = re.compile(
    r"\bopowiedz\s+(?:mi\s+)?(?:jak\w*\s+)?(?:zart|dowcip|kawal)\b|"
    r"\bpowiedz\s+(?:mi\s+)?(?:cos\s+smiesznego|zart|dowcip|kawal)\b|"
    r"\brozsmiesz mnie\b|"
    r"\b(?:masz|znasz)\s+(?:jak\w*\s+)?(?:zart|dowcip|kawal)\b")


def is_joke_request(text):
    return bool(_REQUEST_RE.search(normalize_facts(text or "")))


def _level(value):
    return "low" if value < 0.34 else ("high" if value >= 0.67 else "mid")


def can_joke(persona=None, affect=None, text="", store=None, now=None):
    """Czy ASTRO może spontanicznie zażartować (bez jawnej prośby użytkownika)."""
    from .expression import is_sensitive
    if is_sensitive(text):
        return False
    p = normalize(persona)
    if _level(p["humor"]) == "low":
        return False
    if affect is not None:
        try:
            if affect.effective()[0] < -0.3:
                return False
        except Exception:
            pass
    if store is not None:
        try:
            if not store.allow(now):
                return False
        except Exception:
            pass
    return True


def pick(salt=0, avoid=None, rng=None):
    """Wybiera żart, pomijając ostatnio użyte (`avoid`). Deterministycznie przy danym `rng`."""
    avoid = set(avoid or ())
    pool = [j for j in JOKES if j["id"] not in avoid] or list(JOKES)
    chooser = rng or random
    return chooser.choice(pool)


def by_id(joke_id):
    return next((j for j in JOKES if j["id"] == joke_id), None)
