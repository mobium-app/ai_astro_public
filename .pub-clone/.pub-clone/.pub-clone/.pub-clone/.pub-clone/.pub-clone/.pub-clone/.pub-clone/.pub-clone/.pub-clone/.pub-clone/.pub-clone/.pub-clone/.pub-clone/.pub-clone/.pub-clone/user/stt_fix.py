"""Korekcja typowych błędów STT w polskich nazwach (E8.4).

STT (Vosk/Whisper) przekręca miasta i imiona („Poznani", „Michau", „Krakuff"). Zamiast zgadywać
globalnie (co psuje komendy), korygujemy **wartości pól profilu** względem kuratorowanego słownika
miast i imion, dopasowaniem przybliżonym (difflib) po formie bez znaków diakrytycznych.
Bez modelu i bez sieci.
"""

import difflib

from ..safety import normalize_facts

CITIES = (
    "Warszawa", "Kraków", "Łódź", "Wrocław", "Poznań", "Gdańsk", "Szczecin", "Bydgoszcz",
    "Lublin", "Białystok", "Katowice", "Gdynia", "Częstochowa", "Radom", "Toruń", "Sosnowiec",
    "Rzeszów", "Kielce", "Gliwice", "Olsztyn", "Zabrze", "Bielsko-Biała", "Bytom",
    "Zielona Góra", "Rybnik", "Ruda Śląska", "Opole", "Tychy", "Gorzów Wielkopolski",
    "Elbląg", "Płock", "Dąbrowa Górnicza", "Wałbrzych", "Włocławek", "Tarnów", "Chorzów",
    "Koszalin", "Kalisz", "Legnica", "Grudziądz", "Słupsk", "Jaworzno", "Jastrzębie-Zdrój",
    "Nowy Sącz", "Jelenia Góra", "Siedlce", "Mysłowice", "Konin", "Piła", "Piotrków Trybunalski",
    "Inowrocław", "Lubin", "Ostrów Wielkopolski", "Suwałki", "Gniezno", "Chełm", "Zamość",
    "Łomża", "Ełk", "Tczew", "Mielec", "Krosno", "Świdnica", "Pruszków", "Starogard Gdański",
    "Sopot", "Zakopane", "Zgierz", "Rumia", "Wejherowo", "Malbork", "Oświęcim", "Sanok",
)

NAMES_F = (
    "Anna", "Maria", "Katarzyna", "Małgorzata", "Agnieszka", "Barbara", "Krystyna", "Magdalena",
    "Ewa", "Joanna", "Zofia", "Teresa", "Danuta", "Halina", "Irena", "Jadwiga", "Aleksandra",
    "Beata", "Marta", "Monika", "Natalia", "Karolina", "Julia", "Zuzanna", "Wiktoria", "Amelia",
    "Oliwia", "Emilia", "Hanna", "Alicja", "Gabriela", "Laura", "Maja", "Pola", "Antonina",
    "Wanda", "Iwona", "Renata", "Dorota", "Elżbieta", "Izabela", "Lucyna", "Urszula",
)
NAMES_M = (
    "Jan", "Piotr", "Krzysztof", "Andrzej", "Tomasz", "Paweł", "Marcin", "Michał", "Marek",
    "Grzegorz", "Jerzy", "Stanisław", "Adam", "Łukasz", "Rafał", "Wojciech", "Mateusz", "Szymon",
    "Jakub", "Kacper", "Filip", "Bartosz", "Antoni", "Franciszek", "Aleksander", "Wiktor",
    "Ignacy", "Leon", "Alan", "Oskar", "Dawid", "Miłosz", "Damian", "Sebastian", "Robert",
    "Mariusz", "Dariusz", "Jacek", "Zbigniew", "Wiesław", "Ryszard", "Henryk", "Kazimierz",
    "Kamil", "Patryk", "Dominik", "Adrian", "Norbert", "Przemysław",
)

# Krótkie słowa pomijamy (zbyt łatwo o fałszywe trafienie).
_MIN_LEN = 4
_CITY_THRESHOLD = 0.82
_NAME_THRESHOLD = 0.80

# Odmiana nazw miast: dopełniacz („do/ dla X") i miejscownik („w X").
CITY_FORMS = {
    "warszawa": ("Warszawy", "Warszawie"), "krakow": ("Krakowa", "Krakowie"),
    "lodz": ("Łodzi", "Łodzi"), "wroclaw": ("Wrocławia", "Wrocławiu"),
    "poznan": ("Poznania", "Poznaniu"), "gdansk": ("Gdańska", "Gdańsku"),
    "szczecin": ("Szczecina", "Szczecinie"), "bydgoszcz": ("Bydgoszczy", "Bydgoszczy"),
    "lublin": ("Lublina", "Lublinie"), "bialystok": ("Białegostoku", "Białymstoku"),
    "katowice": ("Katowic", "Katowicach"), "gdynia": ("Gdyni", "Gdyni"),
    "czestochowa": ("Częstochowy", "Częstochowie"), "radom": ("Radomia", "Radomiu"),
    "torun": ("Torunia", "Toruniu"), "sosnowiec": ("Sosnowca", "Sosnowcu"),
    "rzeszow": ("Rzeszowa", "Rzeszowie"), "kielce": ("Kielc", "Kielcach"),
    "gliwice": ("Gliwic", "Gliwicach"), "olsztyn": ("Olsztyna", "Olsztynie"),
    "zabrze": ("Zabrza", "Zabrzu"), "bytom": ("Bytomia", "Bytomiu"),
    "opole": ("Opola", "Opolu"), "tychy": ("Tychów", "Tychach"),
    "elblag": ("Elbląga", "Elblągu"), "plock": ("Płocka", "Płocku"),
    "tarnow": ("Tarnowa", "Tarnowie"), "koszalin": ("Koszalina", "Koszalinie"),
    "kalisz": ("Kalisza", "Kaliszu"), "legnica": ("Legnicy", "Legnicy"),
    "grudziadz": ("Grudziądza", "Grudziądzu"), "slupsk": ("Słupska", "Słupsku"),
    "nowy sacz": ("Nowego Sącza", "Nowym Sączu"),
    "jelenia gora": ("Jeleniej Góry", "Jeleniej Górze"),
    "siedlce": ("Siedlec", "Siedlcach"), "konin": ("Konina", "Koninie"),
    "pila": ("Piły", "Pile"), "suwalki": ("Suwałk", "Suwałkach"),
    "gniezno": ("Gniezna", "Gnieźnie"), "zamosc": ("Zamościa", "Zamościu"),
    "lomza": ("Łomży", "Łomży"), "tczew": ("Tczewa", "Tczewie"),
    "sopot": ("Sopotu", "Sopocie"), "zakopane": ("Zakopanego", "Zakopanem"),
    "oswiecim": ("Oświęcimia", "Oświęcimiu"), "sanok": ("Sanoka", "Sanoku"),
}


def _city_form(text, index):
    key = normalize_facts(text or "")
    forms = CITY_FORMS.get(key)
    return forms[index] if forms else text


def genitive_city(text):
    """Dopełniacz nazwy miasta („Poznania"); nieznane zostawia bez zmian."""
    return _city_form(text, 0)


def locative_city(text):
    """Miejscownik nazwy miasta („Poznaniu"); nieznane zostawia bez zmian."""
    return _city_form(text, 1)


def _best(text, vocabulary, threshold):
    low = normalize_facts(text)
    if not low:
        return ""
    best, best_ratio = "", 0.0
    for cand in vocabulary:
        ratio = difflib.SequenceMatcher(None, low, normalize_facts(cand)).ratio()
        if ratio > best_ratio:
            best, best_ratio = cand, ratio
    return best if best_ratio >= threshold else ""


def correct_city(text):
    """Dopasowuje nazwę miasta (też wielowyrazową) do słownika; zostawia oryginał gdy brak pewności."""
    raw = (text or "").strip()
    if len(normalize_facts(raw)) < _MIN_LEN:
        return raw
    hit = _best(raw, CITIES, _CITY_THRESHOLD)
    return hit or raw


def correct_name(text):
    """Dopasowuje pojedyncze imię do słownika; przy dwóch+ słowach zostawia bez zmian."""
    raw = (text or "").strip()
    if " " in raw or len(normalize_facts(raw)) < _MIN_LEN:
        return raw
    hit = _best(raw, NAMES_F + NAMES_M, _NAME_THRESHOLD)
    return hit or raw


def correct_text(text):
    """Lekka korekta całej wypowiedzi: każde słowo bliskie imieniu zamieniane na kanoniczne."""
    out = []
    for token in (text or "").split():
        fixed = correct_name(token)
        out.append(fixed if fixed != token else token)
    return " ".join(out)
