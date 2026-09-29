"""Polszczyzna modelu (E9): wzorce few-shot + detekcja usterek w odpowiedziach.

Warstwa mowy (`audio/text.py`) czyści wymowę; tutaj pilnujemy **treści** odpowiedzi modelu:
poprawna polszczyzna, rodzaj żeński, interpunkcja, bez angielskich słów, markdownu, URL-i, emoji
i bez odczytywania nazw znaków. Bez modelu i bez sieci (sam checker + wzorce).
"""

import re

from .. import config

# Wzorce (pytanie -> wzorowa odpowiedź po polsku). Krótkie, konkretne, poprawny rodzaj żeński.
POLISH_EXAMPLES = (
    ("Ile jest plików w katalogu?",
     "W katalogu roboczym mam pięć plików, w tym dwa ukryte."),
    ("Jaka jest temperatura procesora?",
     "Temperatura procesora wynosi 47 stopni Celsjusza i jest w normie."),
    ("Opowiedz w dwóch zdaniach, co potrafisz.",
     "Sprawdzam pliki, uruchamiam polecenia i odpowiadam po polsku. Robię to krótko, "
     "konkretnie i z poprawną interpunkcją."),
    ("Kim jesteś?",
     "Jestem Astro, lokalnym agentem działającym na Raspberry Pi."),
)
POLISH_RULES = (
    "Pisz po polsku: pełne zdania z interpunkcją, pierwsza osoba rodzaju żeńskiego. "
    "Nie używaj angielskich słów ani rodzajników, markdownu, adresów URL, emoji ani nazw znaków "
    "(np. „kratka”, „małpa”). Liczebniki i jednostki zapisuj słownie."
)

# Jednoznacznie angielskie słowa (pomijamy dwuznaczne: i, a, to, on, no, do, my, we…).
_ENGLISH = ("the", "and", "of", "is", "are", "was", "were", "with", "this", "that", "your",
            "you", "for", "have", "has", "from", "about", "sorry", "please", "hello", "thanks")
_SIGN_NAMES = ("kratka", "małpa", "ukośnik", "daszek", "tylda", "pionowa kreska")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2705\u274C\u2B50]")
_MARKDOWN_RE = re.compile(r"(\*\*|__|`|^\s*#{1,6}\s|^\s*[-*]\s|\]\()", re.M)
_URL_RE = re.compile(r"https?://|www\.", re.I)


def examples_block(n=None):
    """Blok few-shot polszczyzny do systemowego kontekstu (n wzorców; 0 = brak)."""
    n = config.POLISH_FEWSHOT if n is None else int(n)
    if n <= 0:
        return ""
    lines = ["POLSZCZYZNA — pisz tak:", POLISH_RULES]
    for q, a in POLISH_EXAMPLES[:n]:
        lines.append(f'- pytanie: „{q}" → odpowiedź: „{a}"')
    return "\n".join(lines)


_ENGLISH_PHRASES = ("open source", "machine learning", "deep learning", "artificial intelligence",
                    "as well as", "by the way", "of course", "in fact")
_REPEAT_RE = re.compile(r"\b(\w{3,})\s+\1\b", re.I)


def english_words(text):
    low = (text or "").lower()
    return sorted({w for w in _ENGLISH if re.search(rf"\b{re.escape(w)}\b", low)})


def english_phrases(text):
    low = (text or "").lower()
    return [p for p in _ENGLISH_PHRASES if p in low]


def looks_english(text):
    """Heurystyka: odpowiedź wygląda na angielską (do jednorazowej regeneracji po polsku).

    Dwa+ jednoznacznie angielskie słowa albo jedno przy krótkiej wypowiedzi. Świadomie prosto —
    fałszywy alarm kosztuje najwyżej jedno dodatkowe wygenerowanie, a ratuje odpowiedź mówioną."""
    words = (text or "").split()
    if not words:
        return False
    eng = english_words(text)
    if len(eng) >= 2:
        return True
    return bool(eng) and len(words) <= 8


def repeated_words(text):
    return [m.group(1) for m in _REPEAT_RE.finditer(text or "")]


def starts_upper(text):
    for ch in (text or "").strip():
        if ch.isalpha():
            return ch.isupper()
    return True


def emoji_present(text):
    return bool(_EMOJI_RE.search(text or ""))


def markdown_present(text):
    return bool(_MARKDOWN_RE.search(text or ""))


def url_present(text):
    return bool(_URL_RE.search(text or ""))


def sign_names(text):
    low = (text or "").lower()
    return [w for w in _SIGN_NAMES if w in low]


def ends_properly(text):
    stripped = (text or "").strip().rstrip("”\"'’)]}")
    return bool(stripped) and stripped[-1] in ".!?…"


def quality_issues(text):
    """Lista usterek polszczyzny w odpowiedzi ([] = czysto)."""
    t = (text or "").strip()
    issues = []
    if not t:
        return ["pusta odpowiedź"]
    eng = english_words(t)
    if eng:
        issues.append(f"angielskie słowa: {', '.join(eng)}")
    phr = english_phrases(t)
    if phr:
        issues.append(f"angielskie frazy: {', '.join(phr)}")
    rep = repeated_words(t)
    if rep:
        issues.append(f"powtórzenia: {', '.join(rep)}")
    if not starts_upper(t):
        issues.append("brak wielkiej litery na początku")
    if markdown_present(t):
        issues.append("markdown")
    if url_present(t):
        issues.append("adres URL")
    if emoji_present(t):
        issues.append("emoji")
    signs = sign_names(t)
    if signs:
        issues.append(f"nazwy znaków: {', '.join(signs)}")
    if not ends_properly(t):
        issues.append("brak interpunkcji końcowej")
    return issues
