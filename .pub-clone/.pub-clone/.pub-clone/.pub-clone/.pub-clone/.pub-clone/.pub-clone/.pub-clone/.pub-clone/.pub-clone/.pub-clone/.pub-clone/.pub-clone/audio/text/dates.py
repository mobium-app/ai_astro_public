"""Daty, godziny, miesiące (B5) — wydzielone z `audio/text.py`, 1:1."""

import re

PL_HOURS_F = {
    0: "zerowa", 1: "pierwsza", 2: "druga", 3: "trzecia", 4: "czwarta", 5: "piąta",
    6: "szósta", 7: "siódma", 8: "ósma", 9: "dziewiąta", 10: "dziesiąta",
    11: "jedenasta", 12: "dwunasta", 13: "trzynasta", 14: "czternasta", 15: "piętnasta",
    16: "szesnasta", 17: "siedemnasta", 18: "osiemnasta", 19: "dziewiętnasta",
    20: "dwudziesta", 21: "dwudziesta pierwsza", 22: "dwudziesta druga",
    23: "dwudziesta trzecia",
}
TTS_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
# „o 15:30" -> „o godzinie piętnastej trzydzieści" (miejscownik); „godzina 22:00" bez powtórzenia.
TTS_OCLOCK_RE = re.compile(r"\bo\s+(\d{1,2}):(\d{2})\b")
TTS_O_GODZ_RE = re.compile(r"\bo\s+godzinie\s+(\d{1,2}):(\d{2})\b", re.I)
TTS_GODZ_RE = re.compile(r"\b(?:godzina|godzinie)\s+(\d{1,2}):(\d{2})\b", re.I)
# Kod pocztowy „61-244" czytamy naturalnie jako liczbę („sześćdziesiąt jeden tysięcy dwieście...").
TTS_POSTAL_RE = re.compile(r"\b(\d{2})-(\d{3})\b")
_O_DOT_RE = re.compile(r"\bo\s+(\d{1,2})\.(\d{2})\b")
_GODZ_DOT_RE = re.compile(r"\b(?:godzina|godzinie)\s+(\d{1,2})\.(\d{2})\b", re.I)
# Po przyimku „w/we": miesiące i pory roku w miejscowniku („w styczeń" -> „w styczniu").
_MONTH_LOC = {
    "styczen": "styczniu", "luty": "lutym", "marzec": "marcu", "kwiecien": "kwietniu",
    "maj": "maju", "czerwiec": "czerwcu", "lipiec": "lipcu", "sierpien": "sierpniu",
    "wrzesien": "wrześniu", "pazdziernik": "październiku", "listopad": "listopadzie",
    "grudzien": "grudniu",
    "wiosna": "wiośnie", "lato": "lecie", "jesien": "jesieni", "zima": "zimie",
    # dni tygodnia po „w": biernik (środa/sobota/niedziela zmieniają formę)
    "sroda": "środę", "sobota": "sobotę", "niedziela": "niedzielę",
}
_W_LOC_RE = re.compile(r"\b([Ww]e?)\s+([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+)\b")
PL_MONTHS_GEN = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
                 "sierpnia", "września", "października", "listopada", "grudnia")
# Dni miesiąca w dopełniaczu („1 maja" -> „pierwszego maja").
PL_DAYS_ORD_GEN = (
    "", "pierwszego", "drugiego", "trzeciego", "czwartego", "piątego", "szóstego", "siódmego",
    "ósmego", "dziewiątego", "dziesiątego", "jedenastego", "dwunastego", "trzynastego",
    "czternastego", "piętnastego", "szesnastego", "siedemnastego", "osiemnastego",
    "dziewiętnastego", "dwudziestego", "dwudziestego pierwszego", "dwudziestego drugiego",
    "dwudziestego trzeciego", "dwudziestego czwartego", "dwudziestego piątego",
    "dwudziestego szóstego", "dwudziestego siódmego", "dwudziestego ósmego",
    "dwudziestego dziewiątego", "trzydziestego", "trzydziestego pierwszego",
)
PL_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+(stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|"
    r"października|listopada|grudnia)\b")
TTS_DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
TTS_DATE_EU = re.compile(r"\b(\d{1,2})[.\-](\d{1,2})[.\-](\d{4})\b")
