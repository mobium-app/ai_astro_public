"""Jednostki, rzeczowniki, waluty i ułamki (B5) — wydzielone z `audio/text.py`, 1:1."""

import re

from ...safety import normalize_facts

# Zgodność liczebnika z rzeczownikiem (mianownik lp / mianownik lm / dopełniacz lm).
COUNT_NOUNS = {
    "plik": ("plik", "pliki", "plików"),
    "błąd": ("błąd", "błędy", "błędów"),
    "minuta": ("minuta", "minuty", "minut"),
    "godzina": ("godzina", "godziny", "godzin"),
    "sekunda": ("sekunda", "sekundy", "sekund"),
    "dzień": ("dzień", "dni", "dni"),
    "rok": ("rok", "lata", "lat"),
    "miesiąc": ("miesiąc", "miesiące", "miesięcy"),
    "tydzień": ("tydzień", "tygodnie", "tygodni"),
    "osoba": ("osoba", "osoby", "osób"),
    "pozycja": ("pozycja", "pozycje", "pozycji"),
    "znak": ("znak", "znaki", "znaków"),
    "linia": ("linia", "linie", "linii"),
    "wpis": ("wpis", "wpisy", "wpisów"),
    "dokument": ("dokument", "dokumenty", "dokumentów"),
    "folder": ("folder", "foldery", "folderów"),
    "katalog": ("katalog", "katalogi", "katalogów"),
    "stopień": ("stopień", "stopnie", "stopni"),
    "punkt": ("punkt", "punkty", "punktów"),
    "bajt": ("bajt", "bajty", "bajtów"),
    "kilobajt": ("kilobajt", "kilobajty", "kilobajtów"),
    "megabajt": ("megabajt", "megabajty", "megabajtów"),
    "gigabajt": ("gigabajt", "gigabajty", "gigabajtów"),
    "terabajt": ("terabajt", "terabajty", "terabajtów"),
    "procent": ("procent", "procenty", "procent"),
}
# Waluty: (lp, lm, dopełniacz lm) oraz warianty zapisu/symbolu.
CURRENCY = {
    "zł": ("złoty", "złote", "złotych"), "pln": ("złoty", "złote", "złotych"),
    "eur": ("euro", "euro", "euro"), "€": ("euro", "euro", "euro"),
    "usd": ("dolar", "dolary", "dolarów"), "$": ("dolar", "dolary", "dolarów"),
    "gbp": ("funt", "funty", "funtów"),
    "chf": ("frank", "franki", "franków"), "czk": ("korona", "korony", "koron"),
    "dolar": ("dolar", "dolary", "dolarów"), "funt": ("funt", "funty", "funtów"),
    "euro": ("euro", "euro", "euro"),
}
_FORM_TO_KEY = {}
for _key, _forms in COUNT_NOUNS.items():
    for _f in _forms:
        _FORM_TO_KEY[normalize_facts(_f)] = _key
# Jednostki czasu — liczby w tych frazach czytamy słownie („za 5 minut" -> „za pięć minut").
TEMPORAL_KEYS = {"minuta", "godzina", "sekunda", "dzień", "rok", "tydzień", "miesiąc"}
_FEMININE_KEYS = {"minuta", "godzina", "sekunda"}
# Narzędnik i miejscownik liczby mnogiej (rozpoznajemy po końcówce -ami / -ach).
CASE_FORMS = {
    "plik": ("plikami", "plikach"), "błąd": ("błędami", "błędach"),
    "minuta": ("minutami", "minutach"), "godzina": ("godzinami", "godzinach"),
    "sekunda": ("sekundami", "sekundach"), "dzień": ("dniami", "dniach"),
    "rok": ("latami", "latach"), "miesiąc": ("miesiącami", "miesiącach"),
    "tydzień": ("tygodniami", "tygodniach"), "osoba": ("osobami", "osobach"),
    "pozycja": ("pozycjami", "pozycjach"), "znak": ("znakami", "znakach"),
    "linia": ("liniami", "liniach"), "wpis": ("wpisami", "wpisach"),
    "dokument": ("dokumentami", "dokumentach"), "folder": ("folderami", "folderach"),
    "katalog": ("katalogami", "katalogach"), "stopień": ("stopniami", "stopniach"),
    "punkt": ("punktami", "punktach"), "bajt": ("bajtami", "bajtach"),
    "kilobajt": ("kilobajtami", "kilobajtach"), "megabajt": ("megabajtami", "megabajtach"),
    "gigabajt": ("gigabajtami", "gigabajtach"), "terabajt": ("terabajtami", "terabajtach"),
    "procent": ("procentami", "procentach"),
}
_CASE_FORM_TO_KEY = {}
for _key, _pair in CASE_FORMS.items():
    for _f in _pair:
        _CASE_FORM_TO_KEY[normalize_facts(_f)] = _key
_CASE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+(?:ami|ach))\b")
_HALF_RE = re.compile(r"\b0[.,]5\b")
_QUARTER_RE = re.compile(r"\b0[.,]25\b")
_HALF_UNIT_RE = re.compile(r"\b(pół|ćwierć)\s*(kg|km|m|l|g)\b")
_UNIT_GEN = {"kg": "kilograma", "km": "kilometra", "m": "metra", "l": "litra", "g": "grama"}
# Jednostki miary zapisane skrótem czytamy słownie („5 km" -> „pięć kilometrów").
_UNIT_WORDS = {
    "km": ("kilometr", "kilometry", "kilometrów"),
    "m": ("metr", "metry", "metrów"),
    "cm": ("centymetr", "centymetry", "centymetrów"),
    "mm": ("milimetr", "milimetry", "milimetrów"),
    "kg": ("kilogram", "kilogramy", "kilogramów"),
    "g": ("gram", "gramy", "gramów"),
    "l": ("litr", "litry", "litrów"),
    "ha": ("hektar", "hektary", "hektarów"),
    "t": ("tona", "tony", "ton"),
    "W": ("wat", "waty", "watów"),
    "kW": ("kilowat", "kilowaty", "kilowatów"),
    "MW": ("megawat", "megawaty", "megawatów"),
    "V": ("wolt", "wolty", "woltów"),
    "A": ("amper", "ampery", "amperów"),
    "Hz": ("herc", "herce", "herców"),
    "kHz": ("kiloherc", "kiloherce", "kiloherców"),
    "m²": ("metr kwadratowy", "metry kwadratowe", "metrów kwadratowych"),
    "m³": ("metr sześcienny", "metry sześcienne", "metrów sześciennych"),
    "km²": ("kilometr kwadratowy", "kilometry kwadratowe", "kilometrów kwadratowych"),
    "kWh": ("kilowatogodzina", "kilowatogodziny", "kilowatogodzin"),
    "MWh": ("megawatogodzina", "megawatogodziny", "megawatogodzin"),
    "Wh": ("watogodzina", "watogodziny", "watogodzin"),
    "PB": ("petabajt", "petabajty", "petabajtów"),
    "bit": ("bit", "bity", "bitów"),
}
# Jednostki „na sekundę"/„na godzinę" — (formy, sufiks, żeńska?).
_PER_SEC = {
    "m/s": (("metr", "metry", "metrów"), "na sekundę", False),
    "km/h": (("kilometr", "kilometry", "kilometrów"), "na godzinę", False),
    "MB/s": (("megabajt", "megabajty", "megabajtów"), "na sekundę", False),
    "GB/s": (("gigabajt", "gigabajty", "gigabajtów"), "na sekundę", False),
    "KB/s": (("kilobajt", "kilobajty", "kilobajtów"), "na sekundę", False),
    "Mbps": (("megabit", "megabity", "megabitów"), "na sekundę", False),
    "Gbps": (("gigabit", "gigabity", "gigabitów"), "na sekundę", False),
    "mph": (("mila", "mile", "mil"), "na godzinę", True),
}
_UNIT_WORD_RE = re.compile(
    r"\b(\d+)\s*(m/s|km/h|MB/s|GB/s|KB/s|Mbps|Gbps|mph|km²|km2|m²|m2|m³|m3|kWh|MWh|Wh|"
    r"kW|MW|kHz|PB|km|kg|cm|mm|ha|Hz|W|V|A|t|m|g|l|bit)\b")
_UNIT_ALIAS = {"km2": "km²", "m2": "m²", "m3": "m³", "kw": "kW", "mw": "MW",
               "khz": "kHz", "hz": "Hz", "v": "V", "w": "W", "a": "A",
               "kwh": "kWh", "mwh": "MWh", "wh": "Wh", "pb": "PB", "mbps": "Mbps", "gbps": "Gbps"}
_FEMININE_UNITS = {"t"}


def _unit_key(unit):
    if unit in _UNIT_WORDS:
        return unit
    return _UNIT_ALIAS.get(unit.lower(), unit)
_CURRENCY_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(zł|PLN|EUR|USD|GBP|CHF|CZK|€|\$)\b", re.I)
# Kwoty z dwiema cyframi po przecinku czytamy słownie („4,50 zł" -> „cztery złote pięćdziesiąt groszy").
_CURRENCY_DEC_RE = re.compile(r"\b(\d+)[.,](\d{2})\s*(zł|PLN|EUR|USD|GBP|CHF|CZK|€|\$)\b", re.I)
_CENT_FORMS = {"zł": ("grosz", "grosze", "groszy"), "pln": ("grosz", "grosze", "groszy"),
               "usd": ("cent", "centy", "centów"), "$": ("cent", "centy", "centów"),
               "eur": ("cent", "centy", "centów"), "€": ("cent", "centy", "centów")}
# Ułamki zwykłe (zapis „1/2") — czytane po polsku.
FRACTIONS = {
    "1/2": "pół", "1/4": "ćwierć", "3/4": "trzy czwarte", "1/3": "jedna trzecia",
    "2/3": "dwie trzecie", "1/5": "jedna piąta", "2/5": "dwie piąte", "3/5": "trzy piąte",
    "4/5": "cztery piąte", "1/8": "jedna ósma", "3/8": "trzy ósme", "5/8": "pięć ósmych",
    "7/8": "siedem ósmych",
}
_FRACTION_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
TTS_UNIT_RE = re.compile(r"\b(\d+)(?:[.,](\d+))?\s*(GB|MB|KB|TB|GHz|MHz|°C)\b", re.I)
TTS_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
TTS_UNIT_FORMS = {
    "GB": ("gigabajt", "gigabajty", "gigabajtów", "gigabajta"),
    "MB": ("megabajt", "megabajty", "megabajtów", "megabajta"),
    "KB": ("kilobajt", "kilobajty", "kilobajtów", "kilobajta"),
    "TB": ("terabajt", "terabajty", "terabajtów", "terabajta"),
    "GHZ": ("gigaherc", "gigaherce", "gigaherców", "gigaherca"),
    "MHZ": ("megaherc", "megaherce", "megaherców", "megaherca"),
    "°C": ("stopień Celsjusza", "stopnie Celsjusza", "stopni Celsjusza", "stopnia Celsjusza"),
}
