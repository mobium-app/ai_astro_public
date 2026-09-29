#!/usr/bin/env python3
"""Diagnostyka wsparcia zdalnego ASTRO: status kont, salda/limity, kolejność (bez logowania kluczy).

Użycie:
    python3 astro/scripts/remote_probe.py            # DeepSeek -> ... -> OpenCode (+PC)
    python3 astro/scripts/remote_probe.py --no-pc
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import remote_support  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Probe dostawców zdalnych ASTRO")
    ap.add_argument("--no-pc", action="store_true")
    args = ap.parse_args()

    chain = remote_support.provider_chain(include_pc=not args.no_pc)
    order = list(dict.fromkeys(p.label for p in chain)) or ["(brak kluczy)"]
    print("Łańcuch: " + " -> ".join(order))
    print("(1) ASTRO sam (lokalny agent) -> " + " -> ".join(order))
    print()
    print(f"{'konto':14s} {'model':30s} {'czat':9s} {'czas':>6s}  limit/saldo  ·  rate-limit")
    print("-" * 118)
    seen = set()
    for p in chain:
        if p.account in seen:
            continue
        seen.add(p.account)
        rl = {}
        if p.label == "pc" and not remote_support._pc_online(p.url):
            status, latency = "offline", 0.0
        else:
            import time
            start = time.time()
            budget = 1200 if p.label in ("gemini", "opencode") else (
                800 if p.label == "groq" else 64)
            try:
                data, headers = remote_support._post_full(p, {
                    "model": p.model,
                    "messages": [{"role": "user",
                                  "content": "Odpowiedz jednym zdaniem po polsku: "
                                             "dlaczego niebo jest niebieskie?"}],
                    "max_tokens": budget, "stream": False})
                msg = ((data.get("choices") or [{}])[0].get("message") or {})
                status = "OK" if (msg.get("content") or "").strip() else "PUSTE"
                low = {k.lower(): v for k, v in headers.items()}
                rl = {k: low[k] for k in remote_support._RATE_KEYS if k in low}
            except Exception as e:
                status = "BŁĄD " + str(e)[:32]
            latency = round(time.time() - start, 2)
        info = remote_support.account_info(p) or "-"
        compact = " ".join(f"{k.replace('x-ratelimit-', '')}={v}" for k, v in rl.items())
        print(f"{p.account:14s} {p.model:30s} {status:9s} {latency:5.2f}s  {info:22s}  {compact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
