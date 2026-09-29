"""Deterministyczne komendy humoru ASTRO (E7.6): „opowiedz żart" z twardymi regułami.

Bez modelu i bez sieci. Jawna prośba działa też przy poważnym temperamencie, ale NIGDY
w kontekście wrażliwym. Spontaniczny humor (przez expression policy) ma cooldown.
"""

from ..persona import humor
from ..persona.expression import is_sensitive


def _memory(agent):
    return getattr(agent, "memory", None) or getattr(
        getattr(agent, "ctx", None), "memory", None)


def handle(text, agent=None):
    if not humor.is_joke_request(text):
        return None
    memory = _memory(agent)
    if is_sensitive(text):
        return ("Widzę, że to nie najlepszy moment na żarty. Jestem obok, "
                "jeśli chcesz o czymś porozmawiać.", "humor")
    store = getattr(memory, "humor", None) if memory is not None else None
    avoid = store.recent_ids() if store is not None else None
    joke = humor.pick(avoid=avoid)
    if store is not None:
        store.mark(joke["id"])
    return (joke["text"], "humor")
