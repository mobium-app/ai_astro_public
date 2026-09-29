#!/usr/bin/env python3
"""Zapowiedź startowa ASTRO (D2): mówi kontekstowe powitanie po starcie usługi.

Domyślnie WYŁĄCZONE (brak hałasu przy każdym restarcie). Włącz: `ASTRO_ANNOUNCE_BOOT=1`
(albo `--force`). Respektuje tryb cichy i ciszę nocną przez `core/initiative`.

Użycie:
    python3 astro/scripts/astro_announce.py [--force]
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.audio.tts import TTS  # noqa: E402
from astro.core.initiative import Initiative  # noqa: E402


def announce(force=False, init=None, tts=None):
    """Mówi powitanie startowe. Zwraca tekst albo "" (wyłączone/cichy tryb/brak TTS)."""
    if not force and not getattr(config, "ANNOUNCE_BOOT", False):
        return ""
    init = init if init is not None else Initiative()
    text = init.greeting()
    if not text:
        return ""  # cisza nocna / tryb cichy / cooldown — szanujemy
    tts = tts if tts is not None else TTS()
    try:
        tts.speak(text)
    except Exception:
        pass
    return text


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in argv
    text = announce(force=force)
    print(f"[announce] {text!r}" if text else "[announce] pominięto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
