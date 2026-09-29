"""Dopasowanie zniekształconego rozpoznania mowy do ZNANEJ komendy must-have.

Cel: gdy STT (Whisper-Base / Vosk) przekręci znaną komendę („pokaż zafoby w dalne" ->
„pokaż zasoby zdalne"), naprawiamy ją deterministycznie, jeszcze przed routerem. Działa bez
modelu i bez sieci; lista komend pochodzi z wersji wbudowanej w repo (`config.MUSTHAVE_FILE`).

Metoda: normalizacja fonetyczna PL + podobieństwo ciągów (difflib) i nakładanie tokenów.
Zwraca kanoniczną frazę + wynik (0..1); stosuj tylko powyżej progu, żeby nie łapać pytań.
"""

import os
import re
import unicodedata
from difflib import SequenceMatcher

from .. import config

_PLACEHOLDER_RE = re.compile(r"\[[^\]]*\]?")
_PAREN_RE = re.compile(r"\([^)]*\)?")
_WORD_RE = re.compile(r"[a-z0-9]+")
# Nowa forma listy must-have (2026-09-29): aliasy po „/", opis po strzałce „---->".
# Separator opisu: 3+ myślniki + „>"; tolerujemy też strzałkę unicode (→) i warianty.
_ARROW_RE = re.compile(r"\s*[-–—]{2,}\s*>\s*|\s*→\s*")

_PHON_SUBS = (("ą", "on"), ("ę", "en"), ("ł", "l"), ("ó", "o"), ("ż", "z"), ("ź", "z"),
              ("ś", "s"), ("ć", "c"), ("ń", "n"), ("rz", "z"), ("sz", "s"), ("cz", "c"),
              ("dz", "z"), ("ch", "h"))


def _strip_diacritics(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def normalize(s):
    s = _strip_diacritics((s or "").lower()).replace("ł", "l")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Lekka rekonstrukcja diakrytyków PL (KOMENDA „popraw komendy" — 2026-09-29). Whisper/Vosk
# często gubią znaki diakrytyczne („podaj godzine", „wylacz"), a lista must-have ma poprawne
# formy — sprowadzamy obie strony do wspólnej postaci, żeby dopasowanie i „pewność" nie cierpiały.
_DIACRITIC_RESTORE = (
    ("wylacz", "wyłącz"), ("wlacz", "włącz"), ("wyswietl", "wyświetl"),
    ("pokaz", "pokaż"), ("scisz", "ścisz"), ("podglosn", "podgłośn"),
    ("podglosc", "podgłoś"), ("zglosn", "zgłośn"), ("zglos", "zgłoś"),
    ("glos", "głos"), ("dzwiek", "dźwięk"), ("zwieksz", "zwiększ"),
    ("zmniejsz", "zmniejsz"), ("godzine", "godzinę"), ("daty", "daty"),
    ("wylacz", "wyłącz"), ("wlacz", "włącz"), ("zrodla", "źródła"),
    ("aktualizuj", "aktualizuj"), ("obroc", "obróć"), ("wysrodkuj", "wyśrodkuj"),
    ("sprawdz", "sprawdź"), ("przywroc", "przywróć"), ("usun", "usuń"),
    ("wyczysc", "wyczyść"), ("wykasuj", "wykasuj"), ("zapamietaj", "zapamiętaj"),
    ("zapomnij", "zapomnij"), ("podlacz", "podłącz"), ("rozlacz", "rozłącz"),
)


def restore_diacritics(s):
    """Przywraca podstawowe diakrytyki PL w tekście (best-effort, słowo po słowie)."""
    out = []
    for word in (s or "").split():
        low = _strip_diacritics(word.lower()).replace("ł", "l")
        for plain, proper in _DIACRITIC_RESTORE:
            if low == plain:
                # zachowaj oryginalne otoczenie znaków (interpunkcja) poza rdzeniem słowa
                out.append(word.replace(word.strip(",.!?;:"), proper))
                break
        else:
            out.append(word)
    return " ".join(out)


# Aliasy fonetyczne/STT: słowa, które Whisper/Vosk mylą z kanonem (akcent, brak ogonków).
# Sprowadzamy je do formy kanonicznej PRZED dopasowaniem — inaczej „remote" i „zdalne" są dla
# difflib odległe, choć znaczą to samo. Użytkownik i tak używa obu wariantów w must-have.
_ALIASES = {
    "remote": "zdalne", "remont": "zdalne", "zdarne": "zdalne", "zdanem": "zdalne",
    "zdaln": "zdalne", "zdałem": "zdalne", "sobie": "zdalne",
    "remot": "zdalne", "remout": "zdalne", "remotem": "zdalne",
    "zdrowie": "zdalne", "zdania": "zdalne", "zdajne": "zdalne",
}

# Prefiks czasownikowy „za-" (zainstaluj/instaluj, zaaktualizuj/aktualizuj) to ten sam zamiar —
# Whisper raz dodaje „za", raz nie. Sprowadzamy do formy bez prefiksu dla rdzeni wykonawczych.
_ZA_VERBS = ("instaluj", "aktualizuj", "laduj", "laduj", "pobierz")


def canonicalize(s):
    """Sprowadza aliasy STT i warianty prefiksu „za-" do form kanonicznych (słowo po słowie)."""
    words = []
    for word in (s or "").split():
        core = word.strip(",.!?;:")
        low = _strip_diacritics(core.lower()).replace("ł", "l")
        rep = _ALIASES.get(low)
        if rep is None and low.startswith("za") and len(low) > 2:
            base = low[2:]
            if base in _ZA_VERBS:
                rep = base
        words.append(word.replace(core, rep) if rep else word)
    return " ".join(words)



def phonetic(s):
    s = (s or "").lower()
    for a, b in _PHON_SUBS:
        s = s.replace(a, b)
    return normalize(s)


def _tokens(s):
    return set(_WORD_RE.findall(normalize(s)))


def similarity(a, b):
    """0..1: max z podobieństwa znakowego (zwykłego i fonetycznego) oraz nakładania tokenów."""
    a = canonicalize(a)
    b = canonicalize(b)
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    char = SequenceMatcher(None, na, nb).ratio()
    phon = SequenceMatcher(None, phonetic(a), phonetic(b)).ratio()
    ta, tb = _tokens(a), _tokens(b)
    tok = len(ta & tb) / max(1, len(ta | tb))
    return max(char, phon, tok)


def _commands(path=None):
    path = path or getattr(config, "MUSTHAVE_FILE", "")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for line in lines:
        s = line.strip()
        if not s.startswith("#"):
            continue
        hashes = len(s) - len(s.lstrip("#"))
        body = s.lstrip("#").strip()
        if hashes == 1 or not body:
            continue
        if hashes == 2 and " " not in body and "/" not in body and body.isupper():
            continue
        body = _PLACEHOLDER_RE.sub("", _PAREN_RE.sub("", body))
        # Opis oddzielony strzałką („---->", „→") — bierzemy część przed strzałką.
        body = _ARROW_RE.split(body)[0]
        # Stara forma „ - " (opis myślnikiem) — dla zgodności wstecznej.
        body = re.sub(r"\s+-\s+", " - ", body).split(" - ")[0]
        for part in re.split(r"\s*/\s*", body):
            part = re.sub(r"\s+", " ", part).strip(" .-–—")
            if len(part) >= 4:
                out.append(part)
    return list(dict.fromkeys(out))


_CACHE = {"path": None, "mtime": None, "cmds": []}


def commands(path=None):
    """Lista znanych komend must-have z inwalidacją cache po zmianie pliku.

    Wcześniej cache był kluczowany SAMĄ ścieżką — edycja `/etc/astro-secrets/komendy_must-have`
    nie działała bez restartu usługi. Teraz klucz zawiera mtime pliku (M: cache invalidation)."""
    path = path or getattr(config, "MUSTHAVE_FILE", "")
    try:
        mtime = os.path.getmtime(path) if path else None
    except OSError:
        mtime = None
    if _CACHE["path"] != path or _CACHE["mtime"] != mtime:
        _CACHE["cmds"] = _commands(path)
        _CACHE["path"] = path
        _CACHE["mtime"] = mtime
    return _CACHE["cmds"]


def best(text, threshold=0.80, path=None):
    """(kanoniczna fraza, wynik) dla najlepszego dopasowania albo (None, wynik)."""
    if not (text or "").strip():
        return None, 0.0
    cmds = _commands(path) if path else commands()
    best_cmd, best_score = None, 0.0
    for cmd in cmds:
        sc = similarity(text, cmd)
        if sc > best_score:
            best_cmd, best_score = cmd, sc
    if best_score >= threshold:
        return best_cmd, best_score
    return None, best_score
