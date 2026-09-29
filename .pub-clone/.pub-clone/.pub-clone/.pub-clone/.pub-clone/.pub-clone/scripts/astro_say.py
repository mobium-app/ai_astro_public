#!/usr/bin/env python3
"""Wypowiada tekst głosem ASTRO (słodki robocik). Test: python3 astro/scripts/astro_say.py "Cześć"."""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro.audio import TTS  # noqa: E402
from astro.audio import express  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="+")
    parser.add_argument("--engine", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--mood", default="", help="preset nastroju (np. radosna, zmartwiona)")
    parser.add_argument("--current-mood", action="store_true",
                        help="użyj aktualnego nastroju z pamięci")
    parser.add_argument("--voice", default="", help="model Piper (nadpisuje głos nastroju)")
    args = parser.parse_args()
    tts = TTS(engine=args.engine)
    plan = None
    if args.mood:
        plan = express.plan(args.mood)
    elif args.current_mood:
        from astro.memory import default_memory
        plan = express.plan_for_affect(default_memory())
    fx = plan["fx"] if plan else None
    model = args.voice or (plan["model"] if plan else None)
    text = " ".join(args.text)  # normalizacja (speakable/feminize) jest w TTS.synthesize
    if not tts.available():
        print(f"[say] TTS niedostępny (engine={tts.engine}, piper={tts.piper}, model={tts.model})")
        return 1
    wav = tts.speak(text, out_wav=args.out, fx=fx, model=model)
    mood = f" mood={plan['mood']}" if plan else ""
    print(f"[say] {'OK' if wav else 'FAIL'}{mood}: {text!r} -> {wav}")
    return 0 if wav else 1


if __name__ == "__main__":
    sys.exit(main())
