#!/usr/bin/env python3
"""Ranking użycia ASTRO (runtime) - kolejność curriculum i treningu.

Od najczęstszych tras/narzędzi/tematów do najrzadszych. Dane: `runtime/logs/usage.jsonl`
zapisywane w tle przez `core/dispatch.py`.

Użycie:
    python3 astro/scripts/usage_report.py [--top 25]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro.core.usage import USAGE_FILE, usage_summary  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Ranking użycia ASTRO")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    s = usage_summary(args.top)
    print(f"Plik: {USAGE_FILE}")
    print(f"Tur: {s['total']}\n")
    print("TRASY (route):")
    for name, n in s["routes"]:
        print(f"  {n:>5}  {name}")
    print("\nNARZĘDZIA:")
    for name, n in s["tools"]:
        print(f"  {n:>5}  {name}")
    print("\nNAJCZĘSTSZE TEMATY:")
    for topic, n in s["topics"]:
        print(f"  {n:>5}  {topic[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
