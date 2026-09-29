"""Leksykon wymowy (M2.2/M2.4): akronimy i nazwy własne -> zapis fonetyczny dla TTS.

Wydzielone z `audio/text.py` (monolit), żeby rozszerzać słownik bez dotykania logiki liczb/dat.
Plik danych: `config.TTS_LEXICON` albo wbudowany `audio/lexicon_pl.json`.
`upper` = akronimy dopasowywane dokładnie (CPU/IP), `words` = nazwy bez rozróżniania wielkości.
"""

import json
import os
import re

from .. import config


def lexicon_path():
    return getattr(config, "TTS_LEXICON", "") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "lexicon_pl.json")


def load_lexicon(path=None):
    """Zwraca (upper, words) jako krotki (regex, zamiana). Brak/błąd pliku = puste."""
    try:
        with open(path or lexicon_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return (), ()
    upper = tuple((re.compile(r"\b" + re.escape(k) + r"\b"), v)
                  for k, v in (data.get("upper") or {}).items())
    words = tuple((re.compile(r"\b" + re.escape(k) + r"\b", re.I), v)
                  for k, v in (data.get("words") or {}).items())
    return upper, words


_UPPER, _WORDS = load_lexicon()


def apply_lexicon(text, upper=None, words=None):
    """Zamienia akronimy/nazwy na zapis fonetyczny (dokładne akronimy, potem nazwy)."""
    if not text:
        return text
    for rx, repl in (upper if upper is not None else _UPPER):
        text = rx.sub(repl, text)
    for rx, repl in (words if words is not None else _WORDS):
        text = rx.sub(repl, text)
    return text


__all__ = ["apply_lexicon", "load_lexicon", "lexicon_path"]
