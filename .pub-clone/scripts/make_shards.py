#!/usr/bin/env python3
"""Odśwież shardy treningowe z aktualnego datasetu (narzędzia + czat + łańcuchy).

`--chain-weight N` oversampluje w zbiorze TRENINGOWYM rekordy wielo-krokowe
(≥2 wywołań narzędzi w jednej trajektorii), żeby poprawić łańcuchy.
`--chat-weight N` oversampluje rekordy CZATU (bez narzędzi) — bez nich model trenowany
tylko na narzędziach regresuje w rozmowie (artefakty `<tool_call>`/`</think>` w czacie).
Walidacja zostaje reprezentatywna (bez ważenia).
"""
import argparse
import json
import os
import random

A = "/home/user/astro"
src = os.path.join(A, "datasets")
out = os.path.join(A, "runtime", "shards")
os.makedirs(out, exist_ok=True)


def load(p):
    try:
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except OSError:
        return []


def calls(r):
    return sum(len(m.get("tool_calls") or []) for m in (r.get("messages") or [])
               if m.get("role") == "assistant")


def is_chat(r):
    return not r.get("tools")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain-weight", type=int, default=1,
                    help="ile razy powtórzyć rekordy ≥2 wywołań w treningu (1 = bez zmian)")
    ap.add_argument("--chat-weight", type=int, default=1,
                    help="ile razy powtórzyć rekordy czatu (bez narzędzi) w treningu")
    ap.add_argument("--only-chat", action="store_true",
                    help="tylko rekordy CZATU (bez narzędzi) — adapter czatu/polszczyzny")
    args = ap.parse_args()

    tr = load(os.path.join(src, "astro_train.jsonl"))
    va = load(os.path.join(src, "astro_val.jsonl"))
    if getattr(args, "only_chat", False):     # adapter CZATU: tylko rekordy bez narzędzi
        tr = [r for r in tr if is_chat(r)]
        va = [r for r in va if is_chat(r)]
    elif args.chat_weight <= 0:               # 0 = całkowicie pomiń rekordy czatu (tool-only)
        tr = [r for r in tr if not is_chat(r)]
        va = [r for r in va if not is_chat(r)]
    tr_w = []
    for r in tr:
        w = 1
        if args.chain_weight > 1 and calls(r) >= 2:
            w = max(w, args.chain_weight)
        if args.chat_weight > 1 and is_chat(r):
            w = max(w, args.chat_weight)
        tr_w.extend([r] * w)
    random.Random(42).shuffle(tr_w)
    names = ["pcmax", "pc2", "kali"]
    for tag, rows in (("train", tr_w), ("val", va)):
        b = {n: [] for n in names}
        for i, r in enumerate(rows):
            b[names[i % 3]].append(r)
        for n in names:
            with open(os.path.join(out, f"astro_{tag}_{n}.jsonl"), "w", encoding="utf-8") as fh:
                for r in b[n]:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        # Pełny zbiór (unia shardów) — trening jakościowy na jednej maszynie (Kali).
        # Powód: trening tylko na 1/3 danych (per-maszyna) dawał słabe adaptery (E6 FAIL).
        with open(os.path.join(out, f"astro_{tag}_full.jsonl"), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tools = [r for r in tr if not is_chat(r)]
    chat = [r for r in tr if is_chat(r)]
    chains = sum(1 for r in tr if calls(r) >= 2)
    print(f"shardy: train {len(tr)}->{len(tr_w)} (tools={len(tools)}, chat={len(chat)}"
          f" x{args.chat_weight}, łańcuchy={chains} x{args.chain_weight}), val={len(va)}; "
          f"pełny: astro_*_full.jsonl")


if __name__ == "__main__":
    main()
