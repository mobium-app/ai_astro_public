"""Liczebniki i formy liczbowe (B5) — wydzielone z `audio/text.py`, zachowanie 1:1.

Zawiera: liczby główne (`pl_number`/`pl_plural`), liczebniki porządkowe, rzymskie,
formy przypadków liczebnika oraz powiązane wyrażenia regularne.
"""

import re

PL_ONES = ("zero", "jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem",
           "osiem", "dziewięć")
PL_TEENS = ("dziesięć", "jedenaście", "dwanaście", "trzynaście", "czternaście", "piętnaście",
            "szesnaście", "siedemnaście", "osiemnaście", "dziewiętnaście")
PL_TENS = ("", "", "dwadzieścia", "trzydzieści", "czterdzieści", "pięćdziesiąt",
           "sześćdziesiąt", "siedemdziesiąt", "osiemdziesiąt", "dziewięćdziesiąt")
PL_HUNDREDS = ("", "sto", "dwieście", "trzysta", "czterysta", "pięćset", "sześćset",
               "siedemset", "osiemset", "dziewięćset")
TTS_DEC_RE = re.compile(r"\b(\d+)[.,](\d+)\b")
# Separator tysięcy (spacja w „1 000") — sklejamy, żeby TTS przeczytał „tysiąc".
_THOUSANDS_RE = re.compile(r"(?<=\d)[ \u00a0](?=\d{3}(?!\d))")


def pl_plural(n, forms):
    if n == 1:
        return forms[0]
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return forms[1]
    return forms[2]


def pl_number(n):
    if n < 0:
        return "minus " + pl_number(-n)
    if n < 10:
        return PL_ONES[n]
    if n < 20:
        return PL_TEENS[n - 10]
    if n < 100:
        return PL_TENS[n // 10] + ((" " + PL_ONES[n % 10]) if n % 10 else "")
    if n < 1000:
        return PL_HUNDREDS[n // 100] + ((" " + pl_number(n % 100)) if n % 100 else "")
    if n < 1_000_000:
        tys, rem = divmod(n, 1000)
        out = pl_number(tys) + " " + pl_plural(tys, ("tysiąc", "tysiące", "tysięcy"))
        return out + ((" " + pl_number(rem)) if rem else "")
    mln, rem = divmod(n, 1_000_000)
    out = pl_number(mln) + " " + pl_plural(mln, ("milion", "miliony", "milionów"))
    return out + ((" " + pl_number(rem)) if rem else "")


def _num_words(n, feminine=False):
    s = pl_number(n)
    if feminine:
        if n == 1:
            return "jedna"
        if n % 10 == 2 and n % 100 != 12 and s.endswith("dwa"):
            return s[:-3] + "dwie"
    return s


# Liczebniki porządkowe (1–31) do „1. miejsce" / „15. rocznica".
_ORD_U_M = ("", "pierwszy", "drugi", "trzeci", "czwarty", "piąty", "szósty", "siódmy", "ósmy",
            "dziewiąty")
_ORD_TEENS_TUPLE = ("dziesiąty", "jedenasty", "dwunasty", "trzynasty", "czternasty", "piętnasty",
                    "szesnasty", "siedemnasty", "osiemnasty", "dziewiętnasty")


def _ord_m(n):
    if n < 10:
        return _ORD_U_M[n]
    if n < 20:
        return _ORD_TEENS_TUPLE[n - 10]
    tens = {20: "dwudziesty", 30: "trzydziesty"}.get((n // 10) * 10, "")
    unit = _ORD_U_M[n % 10]
    return f"{tens} {unit}".strip()


def _ord_f(words):
    out = []
    for w in words.split():
        if w == "drugi":
            out.append("druga")
        elif w == "trzeci":
            out.append("trzecia")
        elif w.endswith("y"):
            out.append(w[:-1] + "a")
        else:
            out.append(w)
    return " ".join(out)


def _ord_n(words):
    out = []
    for w in words.split():
        if w == "drugi":
            out.append("drugie")
        elif w == "trzeci":
            out.append("trzecie")
        elif w.endswith("y"):
            out.append(w[:-1] + "e")
        else:
            out.append(w)
    return " ".join(out)


_ORDINAL_M = tuple([""] + [_ord_m(i) for i in range(1, 32)])
_ORDINAL_F = tuple([""] + [_ord_f(_ord_m(i)) for i in range(1, 32)])
_ORDINAL_N = tuple([""] + [_ord_n(_ord_m(i)) for i in range(1, 32)])
# Nominatywne formy rzeczowników (żeby nie mylić przypadków).
_ORDINAL_NOUNS = {
    "miejsce": _ORDINAL_N, "pozycja": _ORDINAL_F, "klasa": _ORDINAL_F, "liga": _ORDINAL_F,
    "rocznica": _ORDINAL_F, "edycja": _ORDINAL_F, "lekcja": _ORDINAL_F, "wersja": _ORDINAL_F,
    "raz": _ORDINAL_M, "tom": _ORDINAL_M, "numer": _ORDINAL_M, "stopien": _ORDINAL_M,
    "stopień": _ORDINAL_M,
}
_ORDINAL_RE = re.compile(
    r"\b(\d{1,2})\.\s+([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+)\b")
NUM_INSTR = {2: "dwoma", 3: "trzema", 4: "czterema", 5: "pięcioma", 6: "sześcioma",
             7: "siedmioma", 8: "ośmioma", 9: "dziewięcioma", 10: "dziesięcioma"}
NUM_LOC = {2: "dwóch", 3: "trzech", 4: "czterech", 5: "pięciu", 6: "sześciu",
           7: "siedmiu", 8: "ośmiu", 9: "dziewięciu", 10: "dziesięciu"}
# Zakresy „od 5 do 10" -> „od pięciu do dziesięciu" (dopełniacz liczebnika).
_RANGE_RE = re.compile(r"\bod\s+(\d{1,2})\s+do\s+(\d{1,2})\b")
_GEN = {1: "jednego", 2: "dwóch", 3: "trzech", 4: "czterech", 5: "pięciu", 6: "sześciu",
        7: "siedmiu", 8: "ośmiu", 9: "dziewięciu", 10: "dziesięciu"}
_DO_RE = re.compile(r"\bdo\s+(\d{1,2})(?![\d.,])")
_CENTURY_RE = re.compile(r"\b(\d{1,2})\s+(wiek\w*)\b")
_CHILD_RE = re.compile(r"\b(\d{1,2})\s+(dzieci|dziecko)\b", re.I)
_COLLECT = {1: "jedno", 2: "dwoje", 3: "troje", 4: "czworo"}
# Wiek rzymski: „XXI wiek" -> „dwudziesty pierwszy wiek"; „w XX wieku" -> „w dwudziestym wieku".
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50}
_ROMAN_RE = re.compile(r"\b([IVXL]{1,6})\s+(wiek\w*)\b")

_ORD_UNITS_M = ("", "pierwszy", "drugi", "trzeci", "czwarty", "piąty", "szósty", "siódmy", "ósmy",
                "dziewiąty")
_ORD_TEENS_M = {11: "jedenasty", 12: "dwunasty", 13: "trzynasty", 14: "czternasty",
                15: "piętnasty", 16: "szesnasty", 17: "siedemnasty", 18: "osiemnasty",
                19: "dziewiętnasty"}


def ordinal_m(n):
    if n < 10:
        return _ORD_UNITS_M[n]
    if n == 10:
        return "dziesiąty"
    if 11 <= n <= 19:
        return _ORD_TEENS_M[n]
    tens = {20: "dwudziesty", 30: "trzydziesty"}.get((n // 10) * 10, "")
    unit = _ORD_UNITS_M[n % 10]
    return f"{tens} {unit}".strip()


def roman_to_int(s):
    total, prev = 0, 0
    for ch in reversed((s or "").upper()):
        v = _ROMAN_VALUES.get(ch, 0)
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def _loc_masculine(words):
    return " ".join(w[:-1] + "ym" if w.endswith("y") else (w[:-1] + "im" if w.endswith("i") else w)
                    for w in words.split())
