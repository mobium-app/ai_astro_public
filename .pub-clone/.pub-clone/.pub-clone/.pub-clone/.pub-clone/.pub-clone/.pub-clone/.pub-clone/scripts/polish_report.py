#!/usr/bin/env python3
"""Skrobie logi ASTRO i raportuje realne usterki polszczyzny (do rozbudowy wzorców E9).

Użycie:
    python3 astro/scripts/polish_report.py             # odpowiedzi modelu (voice/logi)
    python3 astro/scripts/polish_report.py --topics    # tematy użytkownika (usage.jsonl)
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.persona import polish  # noqa: E402

VOICE_RE = re.compile(r"\[voice\] odpowiedź: '(.*)'\s*$")


def collect(topics=False):
    texts = []
    usage = config.LOGS_DIR / "usage.jsonl"
    if usage.exists():
        for line in open(usage, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("topic") or ""
            if topics and len(t) >= 5:
                texts.append(t)
    if not topics:
        log = config.LOGS_DIR / "astro.log"
        if log.exists():
            for line in open(log, encoding="utf-8", errors="replace"):
                m = VOICE_RE.search(line)
                if m:
                    texts.append(m.group(1))
    return texts


def main():
    ap = argparse.ArgumentParser(description="Raport usterek polszczyzny z logów")
    ap.add_argument("--topics", action="store_true",
                    help="analizuj tematy użytkownika (usage.jsonl), nie odpowiedzi modelu")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    texts = collect(args.topics)
    counts = Counter()
    samples = {}
    for t in texts:
        for iss in polish.quality_issues(t):
            key = iss.split(":")[0]
            counts[key] += 1
            samples.setdefault(key, t[:110])
    print(f"próbek: {len(texts)}")
    for key, n in counts.most_common(args.top):
        print(f"{n:6}  {key}: {samples.get(key, '')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
