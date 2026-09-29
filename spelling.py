"""Literowanie hasła mową -> hasło (obsługa ASTRO bez ekranu).

Przykład: „małe a, duże B, slash, hashtag, małpa, wykrzyknik, end, gwiazdka, dolar, procent”
-> „aB/#@!&*$%”. Obsługiwane nazwy liter, cyfr i symboli (w tym „end”/„and” = &).
"""

import re

LETTER_NAMES = {
    "a": "a", "be": "b", "ce": "c", "de": "d", "e": "e", "ef": "f", "gie": "g",
    "ha": "h", "i": "i", "jot": "j", "ka": "k", "el": "l", "em": "m", "en": "n",
    "o": "o", "pe": "p", "er": "r", "es": "s", "te": "t", "u": "u", "wu": "w",
    "y": "y", "igrek": "y", "zet": "z", "ku": "q", "iks": "x",
    "b": "b", "c": "c", "d": "d", "f": "f", "g": "g", "h": "h", "j": "j", "k": "k",
    "l": "l", "m": "m", "n": "n", "p": "p", "q": "q", "r": "r", "s": "s", "t": "t",
    "v": "v", "w": "w", "x": "x", "z": "z",
}
DIGIT_NAMES = {
    "zero": "0", "jeden": "1", "dwa": "2", "trzy": "3", "cztery": "4", "pięć": "5",
    "piec": "5", "sześć": "6", "szesc": "6", "siedem": "7", "osiem": "8",
    "dziewięć": "9", "dziewiec": "9",
}
SYMBOL_NAMES = {
    "hasztag": "#", "hashtag": "#", "hash": "#", "kratka": "#",
    "małpa": "@", "malpa": "@", "at": "@",
    "wykrzyknik": "!", "slash": "/", "ukosnik": "/", "ukośnik": "/",
    "gwiazdka": "*", "gwiazdkę": "*", "dolar": "$", "procent": "%",
    "end": "&", "and": "&", "ampersand": "&",
    "kropka": ".", "dot": ".", "przecinek": ",", "myslnik": "-", "minus": "-",
    "podkreslnik": "_", "podkreślnik": "_", "plus": "+", "rowna": "=", "równa": "=",
    "pytajnik": "?", "dwukropek": ":", "srednik": ";", "średnik": ";", "nawias": "(",
}
_LOWER = {"małe", "male", "mała", "mala", "mały", "maly"}
_UPPER = {"duże", "duze", "duża", "duza", "duży", "duzy"}

_TOKEN_RE = re.compile(r"[a-z0-9ąćęłńóśźż]+|[#@!$%^&*()+=.,:;?/\\'\"~`|{}<>_\-\[\]]")


def parse_spelled_secret(text):
    """Zamienia mowę literowaną na hasło. Zwraca '' dla pustego wejścia."""
    words = _TOKEN_RE.findall((text or "").lower())
    out = []
    i = 0
    while i < len(words):
        w = words[i]
        upper = False
        if w in _LOWER:
            i += 1
            if i >= len(words):
                break
            w = words[i]
        elif w in _UPPER:
            upper = True
            i += 1
            if i >= len(words):
                break
            w = words[i]
        if w in SYMBOL_NAMES:
            out.append(SYMBOL_NAMES[w])
        elif w in LETTER_NAMES:
            ch = LETTER_NAMES[w]
            out.append(ch.upper() if upper else ch)
        elif w in DIGIT_NAMES:
            out.append(DIGIT_NAMES[w])
        elif len(w) == 1 and w.isalnum():
            out.append(w.upper() if upper else w)
        elif w in ("cyfra", "litera"):
            i += 1
            if i < len(words):
                w2 = words[i]
                if w2 in DIGIT_NAMES:
                    out.append(DIGIT_NAMES[w2])
                elif w2 in LETTER_NAMES:
                    ch = LETTER_NAMES[w2]
                    out.append(ch.upper() if upper else ch)
                elif len(w2) == 1:
                    out.append(w2.upper() if upper else w2)
        i += 1
    return "".join(out)


def looks_spelled(text):
    """Czy wypowiedź wygląda na literowanie (zawiera nazwy symboli/liter)?"""
    words = set(_TOKEN_RE.findall((text or "").lower()))
    return bool(words & (set(SYMBOL_NAMES) | _LOWER | _UPPER | set(LETTER_NAMES)))
