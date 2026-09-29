"""Polityka wyrażania ASTRO (E7.4): temperament + nastrój + kontekst -> styl i parametry LLM.

Zamienia cechy (persona) i stan afektywny (PAD) na konkretne wskazówki dla modelu oraz na
`max_tokens`/`temperature`. W kontekście wrażliwym (smutek, zdrowie, kryzys) wyłącza humor
i zwiększa empatię. Bez modelu i bez sieci.
"""

import re

from ..safety import normalize_facts
from .persona import defaults, normalize
from .store import PersonaStore

# Kontekst wrażliwy: wtedy bez żartów, więcej empatii, niższa temperatura.
SENSITIVE_RE = re.compile(
    r"\b(smierc|śmierć|zmarl|zmarł|umar\w*|zalob\w*|żałob\w*|pogrzeb|chor\w*|nowotwor\w*|"
    r"nowotwór|diagnoz\w*|szpital|depresj\w*|samoboj\w*|nie chce zyc|nie chcę żyć|umrzec|umrzeć|"
    r"rozwod\w*|zwolnion\w*|zwolnili|stracil\w*|stracił\w*|kryzys|placze|płaczę|boje sie|boję się|"
    r"samotn\w*|tesknie|tęsknię|smutn\w*|cierpi\w*)\b")


def is_sensitive(text):
    return bool(SENSITIVE_RE.search(normalize_facts(text or "")))


def _level(value):
    return "low" if value < 0.34 else ("high" if value >= 0.67 else "mid")


def style_block(persona=None, affect=None, text="", humor_ok=None):
    """Wskazówki stylu dla systemowego kontekstu (spójne z temperamentem i nastrojem)."""
    p = normalize(persona)
    sensitive = is_sensitive(text)
    directives = []
    verb = _level(p["verbosity"])
    if verb == "low":
        directives.append("Odpowiadaj zwięźle (1-3 zdania).")
    elif verb == "high":
        directives.append("Możesz odpowiedzieć szerzej (do 6 zdań).")
    formal = _level(p["formality"])
    if formal == "high":
        directives.append("Utrzymuj formalny, uprzejmy ton.")
    elif formal == "low":
        directives.append("Mów swobodnie, po przyjacielsku.")
    if _level(p["warmth"]) == "high":
        directives.append("Bądź ciepła i wspierająca.")
    elif _level(p["warmth"]) == "low":
        directives.append("Trzymaj się rzeczowo, bez czułości.")
    if sensitive:
        directives.append("Kontekst wrażliwy: zero żartów, okaż zrozumienie i spokój.")
    elif _level(p["humor"]) == "low":
        directives.append("Unikaj żartów.")
    else:
        allow = True if humor_ok is None else bool(humor_ok)
        if allow:
            directives.append("Możesz wpleść lekki humor, gdy naprawdę pasuje; "
                              "nie powtarzaj tego samego żartu.")
    if _level(p["caution"]) == "high":
        directives.append("Sygnalizuj ryzyko i pytaj o zgodę przy zmianach.")
    if affect is not None:
        _label, guidance = affect.describe()
        directives.append(guidance.capitalize() + ".")
    if not directives:
        return ""
    return "EKSPRESJA: " + " ".join(directives)


def llm_params(persona=None, affect=None, text=""):
    """Parametry generacji wynikające z temperamentu/nastroju (bezpieczne zakresy)."""
    p = normalize(persona)
    max_tokens = int(round(300 + 500 * p["verbosity"]))
    temperature = 0.2 + 0.4 * p["energy"]
    if _level(p["humor"]) == "high":
        temperature += 0.05
    if affect is not None:
        _label, _g = affect.describe()
        temperature += 0.05 * affect.effective()[1]
    if is_sensitive(text):
        temperature = min(temperature, 0.3)
    temperature = max(0.1, min(0.85, temperature))
    return {"max_tokens": max(200, min(900, max_tokens)), "temperature": round(temperature, 2)}


def for_run(text, memory=None):
    """Parametry dla pojedynczego uruchomienia agenta (persona + nastrój z pamięci)."""
    try:
        p = PersonaStore().load()
    except Exception:
        p = defaults()
    aff = None
    store = getattr(memory, "affect", None) if memory is not None else None
    if store is not None:
        try:
            aff = store.load()
        except Exception:
            aff = None
    return llm_params(p, aff, text)
