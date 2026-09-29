"""Deterministyczne komendy temperamentu ASTRO (E7.1): podgląd i zmiana cech.

Bez modelu i bez sieci. Wpięte w `dispatch` przed agentem; działa też głosowo.
"""

import re

from ..persona import PersonaStore
from ..persona import persona as P
from ..safety import normalize_facts

QUERY_RE = re.compile(
    r"\bjaki masz temperament\b|\bjaka masz osobowosc\b|\bjaki masz charakter\b|"
    r"\btwoj temperament\b|\btwoja osobowosc\b|\btwoj charakter\b|"
    r"\bpokaz (?:twoj |swoj )?(?:temperament|osobowosc|charakter)\b")
_RESET_RE = re.compile(r"\bprzywroc (?:domyslna |domyslny )?(?:osobowosc|temperament)\b|"
                       r"\breset osobowosci\b")
# (regex, cecha, delta) — kolejność ma znaczenie dla fraz złożonych.
_CHANGES = (
    (re.compile(r"\bbadz powazniejsza\b|\bbadz powazna\b|\bmow powaznie\b"), "formality", 0.15),
    (re.compile(r"\bbadz powazniejsza\b|\bbadz powazna\b|\bmow powaznie\b"), "humor", -0.15),
    (re.compile(r"\brozluznij sie\b|\bna luzie\b|\bbadz swobodna\b"), "formality", -0.15),
    (re.compile(r"\bbadz weselsza\b|\bbadz wesola\b|\bwiecej humoru\b|\bbadz zartobliwa\b"),
     "humor", 0.2),
    (re.compile(r"\bbadz weselsza\b|\bbadz wesola\b"), "energy", 0.1),
    (re.compile(r"\bbadz spokojniejsza\b|\bbadz spokojna\b|\bzwolnij\b"), "energy", -0.2),
    (re.compile(r"\bbadz energiczna\b|\bwiecej energii\b"), "energy", 0.2),
    (re.compile(r"\bmow krocej\b|\bmow krotko\b|\bzwiezle\b"), "verbosity", -0.2),
    (re.compile(r"\bmow wiecej\b|\bmow szczegolowo\b|\bwiecej szczegolow\b"), "verbosity", 0.2),
    (re.compile(r"\bbadz ostrozniejsza\b|\bbadz ostrozna\b"), "caution", 0.2),
    (re.compile(r"\bbadz smielsza\b|\bbadz odwazna\b"), "caution", -0.2),
    (re.compile(r"\bbadz cieplejsza\b|\bbadz milsza\b|\bbadz mila\b"), "warmth", 0.15),
    (re.compile(r"\bbadz rzeczowa\b|\bbadz chlodna\b"), "warmth", -0.15),
)


def _summary(traits):
    return ("Mój temperament:\n" + "\n".join(P.describe(traits))).strip()


def handle(text, agent=None):
    """Zwraca (reply, route) albo None."""
    norm = normalize_facts(text or "")
    if not norm:
        return None
    store = PersonaStore()
    if _RESET_RE.search(norm):
        return _summary(store.reset()) + " Przywróciłam domyślny temperament.", "persona"
    if QUERY_RE.search(norm):
        return _summary(store.load()), "persona"
    changed = False
    traits = store.load()
    for rx, trait, delta in _CHANGES:
        if rx.search(norm):
            traits = P.adjust(traits, trait, delta)
            changed = True
    if changed:
        store.save(traits)
        return "Dobrze. " + _summary(traits), "persona"
    return None
