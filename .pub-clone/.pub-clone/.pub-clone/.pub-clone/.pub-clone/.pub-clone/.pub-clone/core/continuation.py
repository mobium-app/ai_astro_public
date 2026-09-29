"""P3 — deterministyczne rozwiązywanie kontynuacji/anafor przed routerem.

Krótkie wypowiedzi bez własnego tematu („a jak bardzo?", „i co dalej?", „a dlaczego?")
nie niosą treści same w sobie — sens bierze się z poprzedniej tury. Ten moduł scala taką
wypowiedź z ostatnim pytaniem użytkownika w jedno samodzielne pytanie, ZANIM trafi ono do
routera/klasyfikatora. Deterministycznie, bez modelu i bez chmury.

Efekt: silniejszy kontekst dla czatu ORAZ lepsza klasyfikacja intencji (mniej WPADÓW
krótkich kontynuacji w trasę `fast`/RAG). Wypowiedź, która ma własny temat (czasownik/rzeczownik
treściowy), NIE jest ruszana.
"""

import re

from ..safety import normalize_facts

# Zaimki/dopełnienia, które w krótkiej kontynuacji zastępują temat poprzedniej tury.
_ANAPHORA = frozenset({"to", "tego", "temu", "tym", "ta", "ten", "ona", "on", "ono", "je",
                       "niego", "niej", "nich", "jego", "jej", "ci", "ciebie", "cie", "tobie",
                       "mnie", "mi", "nas", "was", "pracy", "rozmowy", "temacie", "temat"})
# Okoliczniki/zaimek „jak” — łączą się z przymierzem stopnia („jak bardzo/długo/często”).
_MANNER = frozenset({"jak", "tak", "bardziej", "mniej", "bardzo", "dlugo", "czesto", "szybko",
                     "dobrze", "zle"})

_PRZECINEK_RE = re.compile(r"\s*,\s*")


def _clean(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def _preceded_by_comma(lead, text):
    match = re.search(r"^\s*" + re.escape(lead) + r"\s*,", text or "", re.I)
    return bool(match)


def rewrite_continuation(text, prev_user, lead_words):
    """Scala krótką kontynuację z poprzednim pytaniem użytkownika.

    `text` — bieżąca wypowiedź; `prev_user` — poprzednia wypowiedź użytkownika (z sesji);
    `lead_words` — zbiór spójników rozpoczynających kontynuację (np. a/i/ale/wiec/to).
    Zwraca scalone pytanie (str) albo None, gdy wypowiedź nie jest kontynuacją.
    """
    cur = _clean(text)
    prev = _clean(prev_user)
    if not cur or not prev:
        return None
    low = normalize_facts(cur)
    tokens = re.findall(r"[a-z0-9]+", low)
    if not tokens or tokens[0] not in lead_words:
        return None

    # Zdanie złożone/rozbudowane („a jak bardzo lubisz zieloną herbatę?”) ma własny temat — nie ruszamy.
    # Wyjątek: dłuższe, czysto zaimkowe/okolicznikowe kontynuacje („a jak bardzo ci się to podoba”).
    content = [t for t in tokens[1:] if t not in _ANAPHORA and t not in _MANNER]
    has_content = bool(content)
    if has_content and len(tokens) > 4:
        return None
    starts_manner = len(tokens) > 1 and tokens[1] == "jak"
    if not has_content and not starts_manner and len(tokens) > 9:
        return None

    lead = tokens[0]
    rest = re.sub(r"^\s*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż0-9]+\s*,?\s*", "", cur).strip()
    rest = _PRZECINEK_RE.sub(" ", rest).strip()
    rest = re.sub(r"\s*[.!?]+\s*$", "", rest).strip()

    # „to” jako samodzielne wskazanie („a to?”, „a to dlaczego?”) — zaimkowe lub puste.
    if lead == "to" and (not rest or rest.lower() in _ANAPHORA):
        rest = "to"

    if not rest:
        # Pusta kontynuacja po spójniku („a?”, „i?”) — nic sensownego do scalenia.
        return None

    # „a to?” = „a co z tym?” — zamiast „to to jest …” scal do „co z <prev>”.
    if rest == "to" and prev.lower().startswith("to "):
        return f"co z {_clean(prev[3:]).rstrip('?.!')}"

    merged = _clean(f"{rest} {prev}")
    return merged if merged and merged != cur else None


__all__ = ["rewrite_continuation"]
