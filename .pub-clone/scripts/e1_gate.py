#!/usr/bin/env python3
"""Bramka E1: zadanie 'temperatura CPU + wolne miejsce' wykonane narzędziami na CPU.

Bez PC, bez głosu. Domyślnie ścieżka deterministyczna (fast-tools -> system_info).
Z flagą --llm uruchamia dodatkowo pełną pętlę agenta na lokalnej Ollamie (CPU).
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import backends as B  # noqa: E402
from astro import config, core, memory  # noqa: E402

TASK = "sprawdź temperaturę procesora i wolne miejsce na dysku"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true",
                        help="uruchom też pełną pętlę agenta na lokalnej Ollamie (CPU)")
    args = parser.parse_args()

    config.ensure_dirs()
    mem = memory.default_memory()
    if mem.learned_count() == 0:
        stats = memory.import_curated(mem)
        print(f"[gate] import kuratorowanej wiedzy: {stats}")
    agent = core.create_agent(memory=mem)

    backends = sorted(B.DEFAULT.backends)
    print(f"[gate] backendy runtime: {backends} (PC/remote tylko opt-in)")
    if not set(backends) <= {"cpu", "cpu_fast", "npu"}:
        print("[gate] FAIL: PC/remote aktywny domyślnie")
        return 1

    out = core.dispatch(TASK, agent)
    print(f"[gate] trasa: {out.route}")
    print(f"[gate] odpowiedź: {out.reply}")
    ok = out.route == "fast" and "°C" in out.reply and "GB" in out.reply and "wolne" in out.reply

    if args.llm:
        print("[gate] pełna pętla agenta na CPU (może potrwać)...")
        result = agent.run(TASK)
        print(f"[gate] agent: route={result.route} used_tools={result.used_tools} "
              f"steps={result.steps} calls={[c['name'] for c in result.tool_calls]}")
        print(f"[gate] agent odpowiedź: {result.reply}")
        ok = ok and result.used_tools

    print("[gate] " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
