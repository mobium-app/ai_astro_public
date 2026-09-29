"""Profil użytkownika ASTRO: schemat, normalizacja, forma adresatywna, maskowanie PII.

Bez zależności od modelu i od bazy — czysta logika domenowa. Trwały zapis: `user/store.py`,
wywiad „poznaj mnie": `user/intake.py`, użycie w kontekście: `core/context.py`.
"""

import difflib
import re

from ..safety import normalize_facts
from . import stt_fix

# Definicja pól: typ + wrażliwość. Źródło prawdy dla walidacji, maskowania i podpowiedzi.
FIELDS = {
    "preferred_name": {"type": "str", "label": "imię"},
    "full_name": {"type": "str", "label": "imię i nazwisko"},
    "gender_form": {"type": "enum", "choices": ("f", "m", "n"), "label": "rodzaj"},
    "address_form": {"type": "enum", "choices": ("ty", "pani", "pan"), "label": "forma"},
    "city": {"type": "str", "label": "miasto"},
    "address": {"type": "str", "label": "adres", "sensitivity": "private"},
    "postal_code": {"type": "str", "label": "kod pocztowy", "sensitivity": "private"},
    "country": {"type": "str", "label": "kraj"},
    "profession": {"type": "str", "label": "zawód"},
    "employer": {"type": "str", "label": "pracodawca"},
    "work_hours": {"type": "str", "label": "godziny pracy"},
    "hobbies": {"type": "list", "label": "hobby"},
    "topics": {"type": "list", "label": "tematy"},
    "family": {"type": "list", "label": "rodzina"},
    "style": {"type": "str", "label": "styl rozmowy"},
    "units": {"type": "str", "label": "jednostki"},
    "notify_hours": {"type": "str", "label": "godziny bez przeszkadzania"},
}
PRIVATE_FIELDS = {k for k, v in FIELDS.items() if v.get("sensitivity") == "private"}
MASK = "[prywatne]"

# Płeć: domyślnie NIGDY nie zgadujemy bez potwierdzenia. Poniżej tylko sugestia do wywiadu.
_MALE_WITH_A = {"kuba", "barnaba", "bonawentura", "jarema", "sasza", "nikita"}
# Wołacz (tylko pewne, częste formy); brak wpisu = zostajemy przy mianowniku (bezpiecznie).
_VOCATIVE = {
    "piotr": "piotrze", "paweł": "pawle", "jan": "janie", "adam": "adamie",
    "marek": "marku", "kuba": "kubo", "jakub": "jakubie", "tomasz": "tomaszu",
    "michał": "michale", "krzysztof": "krzysztofie", "grzegorz": "grzegorzu",
    "marcin": "marcinie", "łukasz": "łukaszu", "rafał": "rafale", "mateusz": "mateuszu",
    "szymon": "szymonie", "filip": "filipie", "bartosz": "bartoszu", "andrzej": "andrzeju",
    "wojciech": "wojciechu", "kacper": "kacprze", "antoni": "antoni", "franciszek": "franciszku",
}
_FORM_MAP = {
    "na ty": "ty", "ty": "ty", "po imieniu": "ty", "neutralnie": "ty", "neutralna": "ty",
    "pani": "pani", "kobieta": "pani", "pan": "pan", "mezczyzna": "pan",
}
_GENDER_MAP = {
    "kobieta": "f", "dziewczyna": "f", "zenska": "f", "żeńska": "f", "female": "f", "f": "f",
    "mezczyzna": "m", "mężczyzna": "m", "chłopak": "m", "meska": "m", "męska": "m",
    "male": "m", "m": "m",
    "neutralnie": "n", "neutralna": "n", "wolę nie mowic": "n", "wolę nie mówić": "n", "n": "n",
}
_NAME_PREFIX_RE = re.compile(
    r"^(?:mam na imi[eę]|nazywam si[eę]|jestem|zwijaj mi si[eę]|m[oó]wi mi si[eę]|imi[eę])\s+")
_LIST_SPLIT_RE = re.compile(r"\s*(?:,|;|\bi\b|\boraz\b)\s*")
_POSTAL_RE = re.compile(r"^\d{2}-\d{3}$")
# Cyfry słownie (dyktowanie kodu pocztowego: „zero zero dziewięć pięć zero").
_DIGIT_WORDS = {
    "zero": "0", "jeden": "1", "jedna": "1", "dwa": "2", "dwie": "2", "trzy": "3",
    "cztery": "4", "pięć": "5", "piec": "5", "sześć": "6", "szesc": "6", "siedem": "7",
    "osiem": "8", "dziewięć": "9", "dziewiec": "9",
}


def _address_form(raw):
    """Forma adresatywna odporna na STT: „na te"/„naty" → „ty", „Panie" → „pan", „Pani" → „pani"."""
    n = normalize_facts(raw)
    if n in _FORM_MAP:
        return _FORM_MAP[n]
    toks = n.split()
    for t in toks:
        if t == "pani" or (t.startswith("pani") and not t.startswith("panie")):
            return "pani"
    for t in toks:
        if t in ("pan", "panie", "pana", "panu", "panem"):
            return "pan"
    if "po imieniu" in n or "neutraln" in n:
        return "ty"
    for t in toks:
        if t in ("ty", "te", "tu", "cie", "tobie", "ta"):
            return "ty"
        if 2 <= len(t) <= 4 and difflib.SequenceMatcher(None, t, "ty").ratio() >= 0.6:
            return "ty"
    return raw


def parse_postal(text):
    """Wyłuskuje dokładnie 5 cyfr (cyfry arabskie lub słownie) -> „NN-NNN" albo "".

    Akceptuje separatory („6-1-244", „61 244", „61.244") i dyktowanie
    („zero zero dziewięć pięć zero"). Odrzuca niejednoznaczne (mniej/więcej niż 5 cyfr).
    """
    s = (text or "").lower()
    for word, digit in _DIGIT_WORDS.items():
        s = re.sub(rf"(?<!\w){word}(?!\w)", digit, s)
    digits = re.sub(r"\D", "", s)
    if len(digits) == 5:
        return f"{digits[:2]}-{digits[2:]}"
    return ""


def infer_gender(name):
    """Sugestia rodzaju z imienia (do potwierdzenia, nigdy nie zapisywana bez zgody)."""
    raw = (name or "").strip().lower()
    if not raw:
        return ""
    first = raw.split()[0]
    if first in _MALE_WITH_A:
        return "m"
    if first.endswith("a"):
        return "f"
    return "m"


def extract_name(text):
    """Wyłuskuje imię z naturalnej wypowiedzi („mam na imię Anna")."""
    s = (text or "").strip().strip(" .,!")
    s = _NAME_PREFIX_RE.sub("", s, count=1).strip(" .,!")
    return s


def parse_list(text):
    parts = [p.strip(" .,!") for p in _LIST_SPLIT_RE.split(text or "")]
    out, seen = [], set()
    for p in parts:
        low = normalize_facts(p)
        if len(p) < 2 or low in seen:
            continue
        seen.add(low)
        out.append(p)
    return out


def vocative(name):
    """Wołacz, gdy pewny; w razie wątpliwości zwraca mianownik (bez ryzykownej odmiany)."""
    raw = (name or "").strip()
    if not raw:
        return raw
    low = raw.lower()
    if low in _VOCATIVE:
        v = _VOCATIVE[low]
        return v[0].upper() + v[1:] if raw[:1].isupper() else v
    if low.endswith("a") and low not in _MALE_WITH_A:
        return raw[:-1] + "o"
    if low.endswith(("k", "g", "h", "sz", "cz", "rz", "ż", "ź", "c")):
        return raw + "u"
    return raw


def salutation(profile):
    """Jak zwracać się do użytkownika: „Pani Anno" / „Panie Marku" / „Anno"."""
    name = (profile or {}).get("preferred_name") or ""
    if not name:
        return ""
    form = (profile or {}).get("address_form") or "ty"
    voc = vocative(name)
    if form == "pani":
        return f"Pani {voc}"
    if form == "pan":
        return f"Panie {voc}"
    return voc


def gender_of(profile):
    g = (profile or {}).get("gender_form") or "n"
    return g if g in ("f", "m", "n") else "n"


def normalize_value(key, raw):
    """Normalizuje surową wartość pola (bez walidacji zakresu)."""
    spec = FIELDS.get(key) or {}
    kind = spec.get("type", "str")
    if kind == "list":
        return parse_list(raw)
    s = str(raw if raw is not None else "").strip().strip(" .,!")
    if key == "postal_code":
        return parse_postal(s) or s
    if key == "gender_form":
        return _GENDER_MAP.get(normalize_facts(s), s)
    if key == "address_form":
        return _address_form(s)
    if key == "city":
        titled = " ".join(w[:1].upper() + w[1:] for w in s.split())
        return stt_fix.correct_city(titled)
    if key == "preferred_name":
        return stt_fix.correct_name(extract_name(s))
    return s


def validate(key, value):
    """Zwraca (ok, wartość_znormalizowana, komunikat). Komunikaty są pełnymi zdaniami po polsku."""
    spec = FIELDS.get(key)
    if not spec:
        return False, value, "Nie znam tego pola."
    if key == "postal_code":
        postal = parse_postal(value)
        if not postal:
            return False, normalize_value(key, value), (
                "Nie rozpoznałam kodu. Podaj pięć cyfr, na przykład: sześć jeden dwa cztery cztery.")
        return True, postal, ""
    v = normalize_value(key, value)
    if spec.get("type") == "list":
        if not v:
            return False, [], "Nie rozpoznałam żadnej pozycji. Wymień po przecinku albo powiedz pomiń."
        return True, v, ""
    if spec.get("type") == "enum":
        if v not in spec.get("choices", ()):
            if key == "address_form":
                return False, v, "Powiedz: na ty, Pani albo Pan."
            if key == "gender_form":
                return False, v, "Powiedz: kobieta, mężczyzna albo neutralnie."
            return False, v, "Nie rozpoznałam odpowiedzi."
        return True, v, ""
    if not v:
        return False, v, "Nie dosłyszałam wartości. Powtórz proszę."
    if len(v) > 120:
        return False, v, "To za długa odpowiedź. Skróć ją proszę."
    return True, v, ""


def is_private(key):
    return key in PRIVATE_FIELDS


def private_values(profile):
    vals = []
    for k in PRIVATE_FIELDS:
        v = (profile or {}).get(k)
        if isinstance(v, str) and len(v) >= 3:
            vals.append(v)
    return vals


def redact(text, values):
    """Zastępuje prywatne wartości w tekście (mirror/logi) znacznikiem."""
    out = text or ""
    for v in sorted(set(values or ()), key=len, reverse=True):
        if v and len(v) >= 3:
            out = out.replace(v, MASK)
    return out


def summary_lines(profile, masked=False):
    """Czytelne podsumowanie profilu (do wywiadu i komendy „co o mnie wiesz")."""
    out = []
    for key, spec in FIELDS.items():
        v = (profile or {}).get(key)
        if not v:
            continue
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        if masked and is_private(key):
            v = MASK
        out.append(f"{spec.get('label', key)}: {v}")
    return out


def context_block(profile):
    """Fragment systemowego kontekstu. Pola prywatne (adres) NIE trafiają do modelu."""
    if not profile:
        return ""
    lines = []
    name = profile.get("preferred_name")
    sal = salutation(profile)
    if name:
        form = profile.get("address_form") or "ty"
        lines.append(f"Imię użytkownika: {name} (forma: {form}).")
    if sal:
        lines.append(f"Zwracaj się do użytkownika: {sal}.")
    if profile.get("city"):
        lines.append(f"Mieszka w: {profile['city']}.")
    if profile.get("profession"):
        lines.append(f"Zawód: {profile['profession']}.")
    if profile.get("hobbies"):
        lines.append("Hobby: " + ", ".join(profile["hobbies"]) + ".")
    if profile.get("style"):
        lines.append(f"Preferowany styl rozmowy: {profile['style']}.")
    if not lines:
        return ""
    return "PROFIL UŻYTKOWNIKA:\n" + "\n".join(lines)


def home_location(profile):
    """Lokalizacja domyślna dla zapytań zewnętrznych: miasto (adres tylko za osobną zgodą)."""
    return (profile or {}).get("city") or ""
