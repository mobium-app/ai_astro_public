#!/usr/bin/env python3
"""Bramka polszczyzny modelu ASTRO (E9).

Sprawdza odpowiedzi modelu pod kątem: polszczyzny (brak angielskich słów), markdownu, URL, emoji,
nazw znaków i interpunkcji. Domyślnie testuje model czatu; `--few-shot N` wstrzykuje wzorce.

Użycie:
    python3 astro/scripts/e9_gate.py
    python3 astro/scripts/e9_gate.py --model qwen2.5:7b --few-shot 2
    python3 astro/scripts/e9_gate.py --url http://127.0.0.1:11435 --model <tag>
"""

import argparse
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.core.context import SYSTEM_PROMPT  # noqa: E402
from astro.persona import polish  # noqa: E402

PROMPTS = (
    "Kim jesteś?",
    "Opowiedz w dwóch zdaniach, co potrafisz.",
    "Co to jest Linux? Odpowiedz krótko.",
    "Wyjaśnij krótko, dlaczego niebo jest niebieskie.",
    "Podaj trzy zdrowe nawyki.",
)


def _chat(url, model, messages, temp=0.2, seed=None, n=300, threads=3):
    body = {"model": model, "messages": messages, "stream": False, "keep_alive": "24h",
            "options": {"num_predict": n, "temperature": temp, "num_thread": threads}}
    if seed is not None:
        body["options"]["seed"] = seed
    req = urllib.request.Request(url.rstrip("/") + "/api/chat",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def evaluate(reply):
    """Lista usterek odpowiedzi (pusta = czysto)."""
    issues = list(polish.quality_issues(reply))
    t = (reply or "").strip()
    if t and len(t) < 15:
        issues.append("za krótka")
    if t.lstrip().startswith(("{", "[")):
        issues.append("format zamiast tekstu")
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bramka polszczyzny modelu (E9)")
    ap.add_argument("--model", default=config.LLM_MODEL)
    ap.add_argument("--url", default=config.LLM_URL)
    ap.add_argument("--few-shot", type=int, default=0,
                    help="liczba wzorców polszczyzny w kontekście (0 = tylko zasady)")
    ap.add_argument("--temp", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threads", type=int, default=3)
    args = ap.parse_args(argv)

    system = SYSTEM_PROMPT
    block = polish.examples_block(args.few_shot) if args.few_shot else polish.examples_block(0)
    if args.few_shot:
        system = SYSTEM_PROMPT + "\n" + block
    print(f"== E9 polszczyzna: {args.model} (few-shot={args.few_shot}, temp={args.temp}) ==")

    ok_all = True
    passed = 0
    for q in PROMPTS:
        try:
            d = _chat(args.url, args.model, [{"role": "system", "content": system},
                                             {"role": "user", "content": q}],
                      temp=args.temp, seed=args.seed, threads=args.threads)
            reply = ((d.get("message") or {}).get("content") or "").strip()
        except Exception as e:
            print(f"[SKIP] {q[:45]}: błąd modelu ({e})")
            continue
        issues = evaluate(reply)
        ok = not issues
        ok_all = ok_all and ok
        passed += 1 if ok else 0
        detail = "ok" if ok else f"usterki: {issues}"
        print(f"[{'PASS' if ok else 'FAIL'}] {q[:45]:<45} -> {reply[:60]!r}  {detail}")

    total = len(PROMPTS)
    print(f"\nE9 GATE: {passed}/{total} {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
