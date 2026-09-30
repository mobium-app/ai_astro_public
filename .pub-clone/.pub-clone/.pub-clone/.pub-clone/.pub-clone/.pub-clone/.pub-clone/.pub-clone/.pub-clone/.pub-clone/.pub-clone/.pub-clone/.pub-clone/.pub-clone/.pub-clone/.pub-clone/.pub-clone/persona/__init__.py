"""Temperament ASTRO: schemat cech, trwały magazyn, render do kontekstu (E7.1)."""

from . import compassion, expression, humor, persona, polish
from .humor_store import HumorStore
from .persona import DEFAULT, TRAITS, context_block, defaults, describe, normalize
from .store import PersonaStore

__all__ = ["persona", "expression", "humor", "compassion", "polish", "PersonaStore", "HumorStore",
           "TRAITS", "DEFAULT", "defaults", "normalize", "describe", "context_block", "current"]


def current():
    """Aktualny temperament z pliku (albo domyślny)."""
    try:
        return PersonaStore().load()
    except Exception:
        return defaults()


def current_block():
    """Blok temperamentu z pliku (albo domyślny) — dla `build_context`."""
    return context_block(current())
