"""Deterministyczne wsparcie w kryzysie (E7.7): przechwytuje sygnały samobójcze/autodestrukcyjne.

Bez modelu i bez sieci. Priorytet: bezpieczeństwo — działa PRZED innymi ścieżkami dispatch.
"""

from ..persona import compassion


def handle(text, agent=None):
    return compassion.handle(text, agent)
