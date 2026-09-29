"""Wywiad „poznaj mnie": deterministyczny, offline, jedno pytanie na turę.

Odporny na błędy STT: potwierdzenie/anuluj/pomiń dopasowywane są też „na przybliżenie"
(dyktowanie i przekręcone słowa), a pola krytyczne (imię, miasto, adres, kod pocztowy) mają
read-back z możliwością korekty. Bez modelu i bez sieci.
"""

import difflib
import re

from ..safety import normalize_facts
from . import profile as P

QUESTIONS = [
    ("preferred_name", "Jak mam się do Ciebie zwracać?", "Powiedz samo imię, na przykład Anna."),
    ("address_form", "Mówić do Ciebie na ty, czy w formie Pani albo Pan?",
     "Powiedz: na ty, Pani albo Pan."),
    ("city", "W jakim mieście mieszkasz?", "Podaj miasto, na przykład Warszawa."),
    ("address", "Chcesz podać ulicę i numer? Możesz to pominąć.",
     "Na przykład Kwiatowa pięć. To pole prywatne, zostaje tylko lokalnie."),
    ("postal_code", "Jaki masz kod pocztowy? Możesz pominąć.",
     "Pięć cyfr, na przykład: sześć jeden dwa cztery cztery."),
    ("profession", "Czym zajmujesz się zawodowo?", "Na przykład programista."),
    ("hobbies", "Co lubisz robić w wolnym czasie?", "Wymień po przecinku albo powiedz pomiń."),
    ("family", "Chcesz powiedzieć coś o rodzinie lub bliskich? Możesz pominąć.",
     "Na przykład żona Anna, syn Piotr."),
    ("style", "Jaki styl rozmowy lubisz? Możesz pominąć.", "Na przykład krótko i konkretnie."),
    ("notify_hours", "O jakich godzinach nie przeszkadzać? Możesz pominąć.",
     "Na przykład od dwudziestej drugiej do siódmej."),
]

# Pola, które po rozpoznaniu prosimy potwierdzić (najczęściej mylone przez STT).
VERIFY_FIELDS = ("preferred_name", "city", "address", "postal_code")

_CONFIRM_WORDS = ("potwierdzam", "potwierdz", "zapisz", "tak", "ok", "okej", "dobrze",
                  "zgoda", "poprawnie", "prawidlowo", "jest dobrze")
_CANCEL_WORDS = ("anuluj", "anul", "przerwij", "rezygnuje", "zrezygnuj", "stop")
_CANCEL_WORDS_STRICT = _CANCEL_WORDS + ("nie",)
_SKIP_WORDS = ("pomin", "pomijam", "pomiń", "nie wiem", "nie chce", "pasz", "nastepne",
               "dalej", "opusc", "opuść")
_FINISH_WORDS = ("wystarczy", "starczy", "koniec", "zakoncz", "zakończ", "to wszystko", "gotowe")
_REPLACE_WORDS = ("nadpisz", "od nowa", "caly profil", "cały profil", "od poczatku",
                  "od początku", "wypelnij od nowa")
_UPDATE_WORDS = ("zaktualizuj", "uzupelnij", "uzupełnij", "dopisz", "dopelnij", "dopełnij",
                 "brakujace", "brakujące")
_CORRECT_CMD_RE = re.compile(r"^\s*(?:popraw|zmie[nń]|zmien|edytuj|zmień)\s+(.+)$", re.I)
# Frazy-polecenia, których NIGDY nie wolno zapisać jako odpowiedź (np. imię „Poznaj mnie").
_COMMAND_LIKE_RE = re.compile(
    r"\b(?:poznaj\s+mnie|poznajmy\s+si[eę]|zbieraj\s+dane|zbierz\s+dane|"
    r"co\s+o\s+mnie\s+wiesz|zapomnij\s+(?:o\s+)?mnie|kim\s+jestem|"
    r"jak[ai]\s+glosnos\w*|jaki\s+poziom\s+dzwieku|jaki\s+dzwiek|"
    r"wylacz\s+(?:system|komputer|maline|urzadzenie)|zamknij\s+system|"
    r"(?:re|ze)start\w*\s+systemu|reset\s+systemu|przerwij|zatrzymaj)\b")
# Aliasy pól (po normalizacji, bez znaków diakrytycznych) -> klucz profilu.
_FIELD_ALIASES = {
    "imie": "preferred_name", "imienia": "preferred_name", "nazwa": "preferred_name",
    "forma": "address_form", "zwrot": "address_form",
    "miasto": "city", "miejscowosc": "city",
    "adres": "address", "ulica": "address",
    "kod pocztowy": "postal_code", "pocztowy": "postal_code", "kod": "postal_code",
    "zawod": "profession", "hobby": "hobbies", "zainteresowania": "hobbies",
    "rodzina": "family", "styl": "style", "godziny": "notify_hours",
}


def _field_from(text):
    norm = normalize_facts(text or "")
    best = ""
    for alias in _FIELD_ALIASES:
        if alias in norm and len(alias) > len(best):
            best = alias
    return _FIELD_ALIASES.get(best, "")


def _fuzzy_match(text, words, threshold=0.7):
    """True, gdy wypowiedź zawiera któreś słowo (dokładnie lub wystarczająco podobnie)."""
    toks = normalize_facts(text or "").split()
    if not toks:
        return False
    joined = " ".join(toks)
    for w in words:
        wn = normalize_facts(w)
        if not wn:
            continue
        if " " in wn:
            if wn in joined:
                return True
            continue
        for t in toks:
            if t == wn:
                return True
            if len(t) >= 4 and len(wn) >= 4 and difflib.SequenceMatcher(None, t, wn).ratio() >= threshold:
                return True
    return False


def is_confirm(text):
    return _fuzzy_match(text, _CONFIRM_WORDS, threshold=0.58)


def is_cancel(text, strict=False):
    return _fuzzy_match(text, _CANCEL_WORDS_STRICT if strict else _CANCEL_WORDS, threshold=0.6)


class ProfileIntake:
    def __init__(self, existing=None):
        self.existing = dict(existing or {})
        self.answers = {}
        self.order = []
        self.index = 0
        self.phase = "mode" if self.existing else "questions"
        self.verify_key = None
        self.verify_value = None
        self.single = False
        self.cancelled = False
        self.confirmed = False

    @property
    def active(self):
        return not (self.cancelled or self.confirmed)

    def _pending_keys(self):
        return [k for k, _q, _h in QUESTIONS if not self.existing.get(k)]

    def _build_order(self, mode):
        if mode == "update":
            keys = self._pending_keys()
            self.answers = {k: v for k, v in self.existing.items() if v}
        else:
            keys = [k for k, _q, _h in QUESTIONS]
            self.answers = {}
        return keys

    def _question(self):
        if self.index >= len(self.order):
            return None
        key = self.order[self.index]
        q, hint = next(((q, h) for k, q, h in QUESTIONS if k == key), ("", ""))
        if self.single:
            return f"Podaj nową wartość. {q} {hint}"
        # Krótkie, spontaniczne pytanie — bez monotonnego „Pytanie N z M" (2026-09-27).
        return f"{q} {hint}".strip()

    def _summary(self):
        return ("Podsumowanie profilu:\n"
                + "\n".join(P.summary_lines(self.answers, masked=False))
                + "\nPowiedz potwierdzam, aby zapisać, albo anuluj, aby zrezygnować.")

    def _advance(self):
        self.verify_key = self.verify_value = None
        self.index += 1
        if self.single or self.index >= len(self.order):
            self.single = False
            self.phase = "confirm"
            return self._summary()
        return self._question()

    def start(self):
        if not self.order:
            self.order = self._build_order("replace")
        if self.phase == "mode":
            return ("Znam już Twój profil. Powiedz nadpisz, aby uzupełnić od nowa, "
                    "zaktualizuj, aby dopisać brakujące dane, albo anuluj.")
        if not self.order:
            self.phase = "confirm"
            return self._summary()
        return self._question()

    def repeat(self):
        """Bieżące pytanie albo podsumowanie — do powtórzenia (np. powtórka „poznaj mnie")."""
        if self.phase == "confirm":
            return self._summary()
        if self.phase == "mode":
            return ("Znam już Twój profil. Powiedz nadpisz, aby uzupełnić od nowa, "
                    "zaktualizuj, aby dopisać brakujące dane, albo anuluj.")
        return self._question() or self._summary()

    def feed(self, text):
        raw = (text or "").strip()
        norm = normalize_facts(raw)

        if self.phase == "mode":
            if is_cancel(norm, strict=True):
                self.cancelled = True
                return "Anulowałam, nic nie zmieniłam."
            if _fuzzy_match(norm, _UPDATE_WORDS, 0.7):
                mode = "update"
            elif _fuzzy_match(norm, _REPLACE_WORDS, 0.7):
                mode = "replace"
            else:
                return ("Powiedz nadpisz, zaktualizuj albo anuluj. "
                        "Nadpisz zastępuje profil, zaktualizuj dopisuje brakujące dane.")
            self.order = self._build_order(mode)
            self.index = 0
            self.phase = "questions"
            if not self.order:
                self.phase = "confirm"
                return "Profil jest już kompletny. " + self._summary()
            return self._question()

        if self.phase == "confirm":
            m = _CORRECT_CMD_RE.match(raw)
            if m:
                field = _field_from(m.group(1))
                if field:
                    self.single = True
                    self.order = [field]
                    self.index = 0
                    self.phase = "questions"
                    return self._question()
                return ("Które pole poprawić? Powiedz na przykład: popraw imię, popraw miasto, "
                        "popraw adres, popraw kod pocztowy, popraw zawód.")
            if is_cancel(norm, strict=True):
                self.cancelled = True
                return "Anulowałam, nic nie zapisałam."
            if is_confirm(norm):
                self.confirmed = True
                return "Zapisałam Twój profil. Dziękuję."
            return ("Nie rozpoznałam potwierdzenia. Powiedz potwierdzam, aby zapisać, "
                    "albo anuluj, aby zrezygnować, albo popraw któreś pole.")

        # Faza pytań: najpierw read-back pola krytycznego.
        if self.verify_key:
            if is_cancel(norm, strict=True):
                self.cancelled = True
                return "Anulowałam, nic nie zapisałam."
            if is_confirm(norm):
                if self.verify_value:
                    self.answers[self.verify_key] = self.verify_value
                return self._advance()
            if _fuzzy_match(norm, _SKIP_WORDS, 0.7):
                return self._advance()
            if _fuzzy_match(norm, _FINISH_WORDS, 0.7):
                if self.verify_value:
                    self.answers[self.verify_key] = self.verify_value
                self.phase = "confirm"
                return self._summary()
            key = self.verify_key
            ok, value, err = self._parse(key, raw)
            if ok:
                if value:
                    self.answers[key] = value
                return self._advance()
            return f"Nie rozpoznałam poprawki. {err}"

        if is_cancel(norm):
            self.cancelled = True
            return "Anulowałam, nic nie zapisałam."
        if _fuzzy_match(norm, _FINISH_WORDS, 0.7):
            self.phase = "confirm"
            return self._summary()

        key = self.order[self.index]
        ok, value, err = self._parse(key, raw)
        if not ok:
            return f"Nie rozpoznałam. {err} Możesz też powiedzieć pomiń."
        if not value:
            return self._advance()
        if key in VERIFY_FIELDS:
            self.verify_key, self.verify_value = key, value
            return (f"Usłyszałam: {value}. Czy dobrze? Powiedz „tak”, "
                    f"albo podaj poprawną wartość.")
        self.answers[key] = value
        return self._advance()

    def _parse(self, key, raw):
        if _fuzzy_match(normalize_facts(raw), _SKIP_WORDS, 0.7) and len(raw) < 40:
            return True, "", ""
        if key == "preferred_name" and _COMMAND_LIKE_RE.search(normalize_facts(raw)):
            return False, "", "To brzmi jak polecenie, nie jak imię. Podaj samo imię."
        m = re.match(r"^(?:nie|popraw|zmien|zmie[nń]|wlasciwie|właściwie)[, ]+(.+)$",
                     raw.strip(), re.I)
        value_raw = m.group(1) if m else raw
        ok, value, err = P.validate(key, value_raw)
        if ok and key == "preferred_name":
            self.answers.setdefault("gender_form", P.infer_gender(value))
        if ok and key == "gender_form" and value == "n":
            self.answers["address_form"] = self.answers.get("address_form") or "ty"
        return ok, value, err
