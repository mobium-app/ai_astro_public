#!/usr/bin/env python3
"""Raport zużycia tokenów zewnętrznych AI ASTRO (remote + premium).

Źródło: `runtime/logs/remote_usage.jsonl` (pola: ts, provider, account, model, prompt,
completion, total, kind, free, est_usd) — zapisywane przez `remote_support._log_usage`.

Użycie:
  python3 scripts/remote_usage.py [--all] [--today] [--days N] [--premium]
                                  [--summary] [--color|--no-color]
    --all       cała historia (domyślnie: wszystkie wpisy — zgodność wstecz)
    --today     tylko dzisiejsze wpisy
    --days N    ostatnie N dni (z dzisiejszym)
    --premium   TYLKO modele OpenCode Go: per model (free/płatne), rodzaje zadań (kind), koszt
    --summary   jedna linia (do wypowiedzenia głosem)
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

KIND_LABELS = {
    "chat": "rozmowy", "vision": "obrazy (vision)", "tools": "narzędzia", "plan": "planowanie",
    "distill": "destylacja", "probe": "sondy", "knowledge": "nauka",
}


def color(txt, code, on):
    return f"\033[{code}m{txt}\033[0m" if on else txt


def fmt(n):
    return f"{int(round(n)):,}".replace(",", " ")


def _cutoff(days=None):
    if not days or days <= 0:
        return None
    start = datetime.datetime.now() - datetime.timedelta(days=days - 1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


def read_entries(days=None, provider=None):
    """Zwraca listę wpisów (dict) — z filtrem dni (ostatnie N) i providera."""
    cutoff = _cutoff(days)
    out = []
    if not os.path.exists(USAGE):
        return out
    with open(USAGE, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if cutoff is not None:
                try:
                    if float(r.get("ts") or 0) < cutoff:
                        continue
                except Exception:
                    continue
            if provider and (r.get("provider") or "") != provider:
                continue
            out.append(r)
    return out


def agg_by_provider(entries):
    stats = {}
    for r in entries:
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


def agg_by_model(entries):
    models = {}
    for r in entries:
        m = r.get("model") or "?"
        st = models.setdefault(m, {"calls": 0, "prompt": 0.0, "completion": 0.0, "total": 0.0,
                                   "usd": 0.0, "free": bool(r.get("free")), "kinds": {}})
        st["calls"] += 1
        st["prompt"] += r.get("prompt") or 0
        st["completion"] += r.get("completion") or 0
        st["total"] += r.get("total") or 0
        free, usd = _free_and_usd(r)
        st["free"] = free if st["calls"] == 1 else (st["free"] and free)
        st["usd"] += usd
        k = r.get("kind") or ""
        if k:
            st["kinds"][k] = st["kinds"].get(k, 0) + 1
    return models


def _free_and_usd(r):
    """(free, usd) z wpisu; dla starych wpisów bez pól — wylicz z modelu (cennik ASTRO)."""
    free = r.get("free")
    usd = r.get("est_usd")
    if free is not None and usd is not None:
        return bool(free), float(usd or 0.0)
    try:
        sys.path.insert(0, os.path.dirname(REPO))
        from astro import remote_support as _rs  # noqa: E402
        model = r.get("model") or ""
        if free is None:
            free = _rs.is_free_model(model)
        if usd is None:
            usd = _rs.estimate_usd(model, int(r.get("prompt") or 0),
                                   int(r.get("completion") or 0))
    except Exception:
        free = bool(free) if free is not None else False
        usd = float(usd or 0.0)
    return bool(free), float(usd or 0.0)


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


def _calls_word(n):
    if n == 1:
        return "wywołanie"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "wywołania"
    return "wywołań"


def premium_summary(models, scope):
    """Jedna linia dla głosu — tylko modele OC Go."""
    if not models:
        return f"{scope} premium: brak wywołań."
    calls = sum(s["calls"] for s in models.values())
    usd = sum(s["usd"] for s in models.values())
    free = all(s["free"] for s in models.values())
    parts = []
    for m, st in sorted(models.items(), key=lambda kv: -kv[1]["calls"]):
        name = m.replace("-free", "").replace("-preview", "").replace("-", " ").strip().title()
        extra = ""
        vision = st["kinds"].get("vision", 0)
        if vision:
            extra = f", w tym {vision} obraz."
        parts.append(f"{name} {st['calls']} {_calls_word(st['calls'])} "
                     f"i {fmt(st['total'])} tokenów{extra}")
    koszt = ("Koszt: zero — modele darmowe." if free
             else f"Szacowany koszt: {usd:.4f} dolara.")
    return (f"{scope} premium użył {calls} {_calls_word(calls)}: " + "; ".join(parts)
            + ". " + koszt)


def premium_tree(models, scope, c):
    print(color("ZUŻYCIE PREMIUM (OpenCode Go)", "1;36", c) + "   "
          + color(f"[{scope}]", "0;90", c))
    if not models:
        print("└─ brak wywołań premium w tym okresie")
        return
    items = sorted(models.items(), key=lambda kv: -kv[1]["calls"])
    for i, (m, st) in enumerate(items):
        last = i == len(items) - 1
        arm = "└─" if last else "├─"
        tag = color("free", "1;32", c) if st["free"] else color("płatny", "1;33", c)
        print(f"{arm} {color(m, '1', c)}  [{tag}]")
        bar = "   " if last else "│  "
        print(f"{bar}├─ wywołania: {st['calls']}  ·  tokeny: ~{fmt(st['total'])} "
              f"(prompt ~{fmt(st['prompt'])} · odp. ~{fmt(st['completion'])})")
        if st["kinds"]:
            kind = " · ".join(f"{KIND_LABELS.get(k, k)} {v}"
                              for k, v in sorted(st["kinds"].items(), key=lambda kv: -kv[1]))
            print(f"{bar}├─ rodzaje: {kind}")
        cost = "0 $ (darmowy)" if st["free"] else f"{st['usd']:.4f} $"
        print(f"{bar}└─ koszt: {cost}")
    gt = sum(s["total"] for s in models.values())
    gc = sum(s["calls"] for s in models.values())
    gu = sum(s["usd"] for s in models.values())
    print("│")
    print(f"└─ {color('RAZEM', '1;32', c)}: {gc} wywołań · ~{fmt(gt)} tokenów · "
          f"koszt {gu:.4f} $")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="cała historia (domyślne)")
    ap.add_argument("--today", action="store_true", help="tylko dzisiejsze wpisy")
    ap.add_argument("--days", type=int, default=None, help="ostatnie N dni")
    ap.add_argument("--premium", action="store_true", help="tylko modele OpenCode Go")
    ap.add_argument("--summary", action="store_true", help="jedna linia (do wypowiedzenia)")
    ap.add_argument("--color", action=argparse.BooleanOptionalAction,
                    default=sys.stdout.isatty())
    args = ap.parse_args()
    c = args.color

    days = args.days
    if args.today and not days:
        days = 1
    scope = "cała historia"
    if days == 1:
        scope = "dziś"
    elif days:
        scope = f"ostatnie {days} dni"

    if args.premium:
        models = agg_by_model(read_entries(days=days, provider="opencode"))
        if args.summary:
            print(premium_summary(models, "Dziś" if days == 1 else
                                  ("W całej historii" if not days else f"Przez {days} dni")))
            return
        premium_tree(models, scope, c)
        return

    stats = agg_by_provider(read_entries(days=days))
    if args.summary:
        print(summary(stats, "Dziś" if days == 1 else "W całej historii" if not days else
                      f"Przez {days} dni"))
        return

    entries = read_entries(days=days)
    stats = agg_by_provider(entries)

    print(color("ZUŻYCIE TOKENÓW — ZEWNĘTRZNE AI (remote)", "1;36", c)
          + "   " + color(f"[{scope}]", "0;90", c))
    print("│")
    provs = ordered(stats)
    if not provs:
        print("└─ brak danych w rejestrze (uruchomiony od pierwszego wywołania remote)")
        return
    gt = gp = gc2 = gcalls = 0
    gusd = 0.0
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
        gc2 += st["completion"]
        gt += st["total"]
        gcalls += st["calls"]
    gusd = sum(float(r.get("est_usd") or 0.0) for r in entries)
    print("│")
    print(f"└─ {color('RAZEM', '1;32', c)}: ~{fmt(gt)} tokenów "
          f"(prompt ~{fmt(gp)} · odpowiedź ~{fmt(gc2)})")
    if gusd > 0:
        print(f"    szacowany koszt: {gusd:.4f} $ (modele płatne)")
    print(f"    wywołania: {gcalls}   ·   rejestr: {os.path.relpath(USAGE, REPO)}")


if __name__ == "__main__":
    main()
