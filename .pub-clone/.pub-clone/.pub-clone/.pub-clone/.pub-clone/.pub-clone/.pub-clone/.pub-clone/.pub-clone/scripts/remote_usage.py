#!/usr/bin/env python3
"""Drzewko zużycia tokenów zewnętrznych AI ASTRO (remote).

Źródło: `runtime/logs/remote_usage.jsonl` (pola: ts, provider, account, model, prompt,
completion, total) — zapisywane przez `remote_support._log_usage` przy każdej odpowiedzi
dostawcy zdalnego.

Użycie:
  python3 scripts/remote_usage.py [--all] [--today] [--summary] [--color|--no-color]
    --all      cała historia (domyślnie: tylko dzisiejsze wpisy)
    --summary  jedna linia (do wypowiedzenia głosem)
"""

import argparse
import datetime
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.environ.get("ASTRO_RUNTIME", os.path.join(os.path.expanduser("~"), "astro", "runtime"))
USAGE = os.path.join(RUNTIME, "logs", "remote_usage.jsonl")

LABELS = {
    "deepseek": "DeepSeek", "grok": "Grok", "gemini": "Gemini", "groq": "Groq",
    "openrouter": "OpenRouter", "huggingface": "Hugging Face", "pc": "PC (Bielik)",
    "opencode": "OpenCode",
}
ORDER = ["deepseek", "grok", "gemini", "groq", "openrouter", "huggingface", "pc", "opencode"]


def color(txt, code, on):
    return f"\033[{code}m{txt}\033[0m" if on else txt


def fmt(n):
    return f"{int(round(n)):,}".replace(",", " ")


def read_usage(day=None):
    """Zwraca {provider: {calls, prompt, completion, total, accounts: Counter}}."""
    stats = {}
    if not os.path.exists(USAGE):
        return stats
    with open(USAGE, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            ts = r.get("ts") or 0
            if day:
                try:
                    when = datetime.datetime.fromtimestamp(float(ts)).date().isoformat()
                except Exception:
                    when = ""
                if when != day:
                    continue
            prov = r.get("provider") or "inne"
            st = stats.setdefault(prov, {"calls": 0, "prompt": 0.0, "completion": 0.0,
                                         "total": 0.0, "model": r.get("model") or "",
                                         "accounts": {}})
            st["calls"] += 1
            st["prompt"] += r.get("prompt") or 0
            st["completion"] += r.get("completion") or 0
            st["total"] += r.get("total") or 0
            if not st["model"] and r.get("model"):
                st["model"] = r["model"]
            acc = r.get("account") or prov
            st["accounts"][acc] = st["accounts"].get(acc, 0) + 1
    return stats


def ordered(stats):
    return [p for p in ORDER if p in stats] + [p for p in stats if p not in ORDER]


def summary(stats, scope):
    total = sum(s["total"] for s in stats.values())
    calls = sum(s["calls"] for s in stats.values())
    parts = [f"{LABELS.get(p, p)} {s['calls']}" for p, s in
             ((p, stats[p]) for p in ordered(stats)) if s["calls"]]
    used = ", ".join(parts) if parts else "żadne"
    return (f"{scope} ASTRO użyła zewnętrznych źródeł AI: {calls} wywołań ({used}), "
            f"około {fmt(total)} tokenów.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="cała historia (nie tylko dziś)")
    ap.add_argument("--today", action="store_true", help="tylko dzisiejsze wpisy")
    ap.add_argument("--summary", action="store_true", help="jedna linia (do wypowiedzenia)")
    ap.add_argument("--color", action=argparse.BooleanOptionalAction,
                    default=sys.stdout.isatty())
    args = ap.parse_args()
    c = args.color

    today = None
    if args.today and not args.all:
        today = datetime.date.today().isoformat()
    stats = read_usage(today)
    scope = "dziś" if today else "cała historia"

    if args.summary:
        print(summary(stats, "Dziś" if today else "W całej historii"))
        return

    print(color("ZUŻYCIE TOKENÓW — ZEWNĘTRZNE AI (remote)", "1;36", c)
          + "   " + color(f"[{scope}]", "0;90", c))
    print("│")

    gt = gp = gc = gcalls = 0
    provs = ordered(stats)
    if not provs:
        print("└─ brak danych w rejestrze (uruchomiony od pierwszego wywołania remote)")
        return

    for i, prov in enumerate(provs):
        st = stats[prov]
        last = i == len(provs) - 1
        arm = "└─" if last else "├─"
        head = color(LABELS.get(prov, prov), "1", c) + (f"  ({st['model']})" if st["model"] else "")
        print(f"{arm} {head}")
        bar = "   " if last else "│  "
        print(f"{bar}├─ wywołania: {st['calls']}")
        print(f"{bar}├─ tokeny: prompt ~{fmt(st['prompt'])}"
              f"  ·  odpowiedź ~{fmt(st['completion'])}  ·  razem ~{fmt(st['total'])}")
        if len(st["accounts"]) > 1:
            acc = " · ".join(f"{k} ×{v}" for k, v in sorted(st["accounts"].items()))
            print(f"{bar}└─ konta: {acc}")
        else:
            only = next(iter(st["accounts"]), prov)
            print(f"{bar}└─ konto: {only}")
        gp += st["prompt"]
        gc += st["completion"]
        gt += st["total"]
        gcalls += st["calls"]

    print("│")
    print(f"└─ {color('RAZEM', '1;32', c)}: ~{fmt(gt)} tokenów "
          f"(prompt ~{fmt(gp)} · odpowiedź ~{fmt(gc)})")
    print(f"    wywołania: {gcalls}   ·   rejestr: {os.path.relpath(USAGE, REPO)}")


if __name__ == "__main__":
    main()
