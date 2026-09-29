"""Współczucie i kryzys ASTRO (E7.7): rozpoznanie cierpienia + bezpieczne wsparcie.

Zasady (z planu, twarde):
- w kryzysie (myśli samobójcze, samookaleczenie) ASTRO **nie udaje terapeuty** — okazuje zrozumienie,
  jasno mówi, że jest programem, i kieruje do wsparcia człowieka (numery pomocowe, bliska osoba);
- w żałobie/chorobie/smutku **nie przechwytuje** zadania — dodaje wskazówki empatii do kontekstu,
  żeby model odpowiedział z zrozumieniem i konkretną pomocą, bez fałszywych zapewnień i oceniania.
Bez modelu i bez sieci.
"""

import re

from ..safety import normalize_facts

# Numery pomocowe (Polska) — podawane słownie modelowi TTS normalizuje liczby.
HELP_LINES = (
    "112 — numer alarmowy",
    "116 123 — kryzysowy telefon zaufania dla dorosłych",
    "116 111 — telefon zaufania dla dzieci i młodzieży",
    "800 70 2222 — centrum wsparcia, czynne całą dobę",
)

_CATEGORIES = ("crisis", "grief", "health", "distress")

_CRISIS_RE = re.compile(
    r"\b(chce umrzec|chce sie zabic|zabic sie|samoboj\w*|nie chce zyc|nie chce dalej zyc|"
    r"nie warto zyc|nie ma sensu zyc|skonczyc ze soba|skonczyc to wszystko|"
    r"zrobic sobie krzywde|skrzywdzic sie|odbierze sobie zycie|mam dosc zycia|"
    r"chce zniknac)\b")
_GRIEF_RE = re.compile(
    r"\b(zmar\w*|umar\w*|smierc|pogrzeb|zalob\w*|strac\w*|odszed\w*|tesknie|"
    r"brakuje mi)\b")
_HEALTH_RE = re.compile(
    r"\b(chor\w*|nowotwor\w*|diagnoz\w*|szpital|operacj\w*|rak\w*|cierpi\w*|bol\w*)\b")
_DISTRESS_RE = re.compile(
    r"\b(samotn\w*|smutn\w*|boje sie|boje\b|placze|placz\b|przygneb\w*|zalam\w*|"
    r"nie daje rady|stres\w*|przemecz\w*|wyczerpan\w*|jest mi zle|jestem sam\w*|"
    r"nie radze sobie|trudno mi)\b")

_GUIDANCE = {
    "crisis": ("Użytkownik może być w kryzysie. Zachowaj spokój, okaż zrozumienie bez oceniania, "
               "nie obiecuj, że wszystko będzie dobrze, i wyraźnie zachęć do kontaktu z człowiekiem "
               "lub numerem pomocowym."),
    "grief": ("Rozpoznano żałobę lub stratę. Nazwij delikatnie uczucie, nie pocieszaj na siłę, "
              "nie porównuj, nie mów „wiem, co czujesz”. Zaoferuj konkretną, spokojną pomoc "
              "(np. przypomnienie, załatwienie sprawy, obecność w rozmowie)."),
    "health": ("Rozpoznano chorobę lub cierpienie. Okaż zrozumienie, nie diagnozuj i nie strasz; "
               "możesz pomóc w praktycznych sprawach i zachęcić do kontaktu z lekarzem."),
    "distress": ("Rozpoznano smutek, samotność lub stres. Okaż empatię, nie umniejszaj, nie daj "
                 "fałszywych zapewnień; zaproponuj konkretną, małą pomoc."),
}

TRANSPARENCY = ("Jestem tylko programem — nie zastąpię człowieka ani terapeuty, ale zostaję "
                "z tobą w tej rozmowie.")


def detect(text):
    norm = normalize_facts(text or "")
    if not norm:
        return None
    if _CRISIS_RE.search(norm):
        return "crisis"
    if _GRIEF_RE.search(norm):
        return "grief"
    if _HEALTH_RE.search(norm):
        return "health"
    if _DISTRESS_RE.search(norm):
        return "distress"
    return None


def is_crisis(text):
    return detect(text) == "crisis"


def crisis_reply():
    lines = "; ".join(HELP_LINES)
    return ("Słyszę, że jest ci bardzo ciężko. To ważne, że o tym mówisz. " + TRANSPARENCY +
            " Proszę, zadzwoń po pomoc albo powiedz komuś bliskiemu — nie zostawaj z tym sama. "
            "Możesz zadzwonić: " + lines + ".")


def compassion_block(text):
    """Blok wsparcia dla modelu (poza kryzysem, który obsługujemy deterministycznie)."""
    cat = detect(text)
    if not cat or cat == "crisis":
        return ""
    return ("WSPARCIE: " + _GUIDANCE.get(cat, "") + " " + TRANSPARENCY).strip()


def handle(text, agent=None):
    """Tylko kryzys przechwytujemy deterministycznie; resztę zostawiamy modelowi (z blokiem WSPARCIE)."""
    if is_crisis(text):
        return crisis_reply(), "crisis"
    return None
