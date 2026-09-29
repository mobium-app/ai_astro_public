#!/usr/bin/env python3
"""Uzupełnia istniejący dataset ASTRO o rekordy kuratorowane (czat + łańcuchy).

Nie przebudowuje datasetu z `memory.db` (to robi `build_dataset.py`) — tylko:
  1) synchronizuje prompt systemowy we wszystkich rekordach z aktualnym `SYSTEM_PROMPT`,
  2) dopisuje rekordy z `scripts/curated_data.py` (dedup), wyłącznie do zbioru treningowego.

Użycie:
    python3 astro/scripts/augment_dataset.py            # datasets/astro_{train,val}.jsonl
    python3 astro/scripts/augment_dataset.py --stats
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro.core.context import SYSTEM_PROMPT  # noqa: E402
from astro.scripts import curated_data  # noqa: E402


def load(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def key(rec):
    msgs = rec.get("messages") or []
    user = next((m.get("content") for m in msgs if m.get("role") == "user"), "")
    ans = next((m.get("content") for m in reversed(msgs) if m.get("role") == "assistant"), "")
    return (str(user).strip(), str(ans).strip()[:120])


def sync_prompt(records):
    for rec in records:
        for msg in rec.get("messages") or []:
            if msg.get("role") == "system":
                msg["content"] = SYSTEM_PROMPT
                break
    return records


def main():
    ap = argparse.ArgumentParser(description="Augmentacja datasetu ASTRO")
    ap.add_argument("--out", default=str(os.path.join(ROOT, "datasets")))
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    train_p = os.path.join(args.out, "astro_train.jsonl")
    val_p = os.path.join(args.out, "astro_val.jsonl")
    train = sync_prompt(load(train_p))
    val = sync_prompt(load(val_p)) if os.path.exists(val_p) else []
    seen = {key(r) for r in train} | {key(r) for r in val}

    curated = curated_data.records()
    added = 0
    for rec in curated:
        if key(rec) in seen:
            continue
        seen.add(key(rec))
        train.append(rec)
        added += 1

    print(f"[augment] train {len(train)} (+{added} kuratorowanych), val {len(val)}")
    if args.stats:
        return 0
    with open(train_p, "w", encoding="utf-8") as fh:
        for r in train:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(val_p, "w", encoding="utf-8") as fh:
        for r in val:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = os.path.join(args.out, "manifest.json")
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as fh:
            data = json.load(fh)
        data.update({"train": len(train), "val": len(val), "curated_added": added})
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    print(f"[augment] zapisano: {train_p} ({len(train)}), {val_p} ({len(val)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
