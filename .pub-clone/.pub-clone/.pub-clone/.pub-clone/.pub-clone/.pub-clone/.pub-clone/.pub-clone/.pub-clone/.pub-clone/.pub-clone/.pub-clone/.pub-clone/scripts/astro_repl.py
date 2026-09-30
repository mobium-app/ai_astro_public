#!/usr/bin/env python3
"""Tryb tekstowy ASTRO (bez mikrofonu) — do diagnozy logiki komend.

Wpisujesz to samo, co powiedziałbyś głosem, i widzisz trasę + odpowiedź. Pozwala oddzielić
problem ze SŁUCHEM (STT) od problemu z LOGIKĄ/trasowaniem. Ctrl-D kończy.

Użycie:
    python3 astro/scripts/astro_repl.py
    python3 astro/scripts/astro_repl.py "oblicz dwa dodać dwa"
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.backends import modes  # noqa: E402
from astro.core import create_agent, dispatch  # noqa: E402


def _enable_stream(agent):
    """C4 (opt-in `ASTRO_STREAM=1`): sink tokenów czatu na stdout. Zwraca stan (mutowalny)."""
    state = {"used": False}
    if not getattr(config, "STREAM", False):
        return state

    def sink(piece):
        state["used"] = True
        sys.stdout.write(piece)
        sys.stdout.flush()

    agent.ctx.stream_sink = sink
    return state


def main():
    args = sys.argv[1:]
    if args:
        text = " ".join(args)
        res = dispatch(text, create_agent())
        print(f"[{res.route}] {res.reply}")
        return 0
    agent = create_agent()
    stream = _enable_stream(agent)
    print(f"ASTRO REPL (tekst, bez mikrofonu). {modes.status_line()}. Ctrl-D = wyjście.")
    print("Tryby: „tryb offline” / „tryb komputer” / „tryb premium”; „tryb” = status.")
    while True:
        try:
            line = input(f"ty[{modes.get_mode()}]> ").strip()
        except EOFError:
            print()
            break
        if not line:
            continue
        if line in ("q", "quit", "exit", "wyjdz", "wyjdź"):
            break
        if line.lower() in ("tryb", "mode", "status"):
            print(f"[tryb] {modes.status_line()}")
            continue
        try:
            res = dispatch(line, agent)
            if stream["used"]:
                sys.stdout.write("\n")
                stream["used"] = False
                print(f"[{res.route}] (streamowane)")
            else:
                print(f"[{res.route}] {res.reply}")
        except Exception as exc:
            print(f"[błąd] {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
