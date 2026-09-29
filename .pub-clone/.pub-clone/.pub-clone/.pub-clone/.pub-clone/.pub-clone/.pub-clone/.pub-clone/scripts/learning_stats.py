#!/usr/bin/env python3
"""Nauka w runtime (A) — ile ASTRO wie i potrafi z sesji na sesję (bez treningu wag).

Pokazuje liczniki: udane trajektorie narzędziowe (baza wzorców few-shot), epizody
rozmów, wpisy `learned`, lekcje oraz statystyki planów (CBR).

Użycie:
    python3 astro/scripts/learning_stats.py
    python3 astro/scripts/learning_stats.py --examples "sprawdź temperaturę procesora"
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.memory import Memory  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Liczniki nauki w runtime (ASTRO)")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--examples", default="", help="pokaż trajektorie podobne do zapytania")
    args = ap.parse_args()

    mem = Memory(args.db)
    stats = mem.learning_stats()
    print("== ASTRO: nauka w runtime ==")
    print(f"  trajektorie narzędziowe (kind=agent): {stats['agent_trajectories']}")
    print(f"  epizody rozmów (kind=episode):        {stats['episodes']}")
    print(f"  learned (baza wiedzy):                {stats['learned']}")
    print(f"  lekcje:                               {stats['lessons']}")
    print(f"  unknowns (do douczenia):              {stats['unknowns']}")
    p = stats["plans"]
    print(f"  plany (CBR): total={p['total']} ok={p['ok']} fail={p['fail']}")

    if args.examples:
        hits = mem.similar_trajectories(args.examples, k=3)
        print(f"\n  podobne udane trajektorie dla: {args.examples!r}")
        if not hits:
            print("    (brak - agent nie ma jeszcze wzorca dla tego zadania)")
        for h in hits:
            names = ", ".join(s.get("name", "?") for s in h["steps"])
            print(f"    [{h['score']}] {h['goal']} -> {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
