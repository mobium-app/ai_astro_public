#!/usr/bin/env python3
"""E6 — budowa zbioru treningowego ASTRO z trajektorii (`memory.db`) + opcjonalnie legacy.

Format rekordu (zgodny z `apply_chat_template(messages, tools=...)` i Ollamą):
    {"messages": [...], "tools": [<schematy OpenAI>]}
gdzie wiadomości `assistant` niosą `tool_calls`, a `tool` niesie wynik. To uczy
model DOKŁADNIE tego, czego brakowało w poprzednich iteracjach: mapowania
pytanie -> nazwa narzędzia + argumenty -> wynik -> finalna odpowiedź.

Użycie:
    python3 astro/scripts/build_dataset.py                 # ASTRO memory.db -> datasets/
    python3 astro/scripts/build_dataset.py --legacy        # + czat z datasetu Ateny
    python3 astro/scripts/build_dataset.py --stats         # tylko statystyki
"""

import argparse
import glob
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.core.context import SYSTEM_PROMPT  # noqa: E402
from astro.memory import Memory, default_memory  # noqa: E402
from astro.safety import normalize_facts  # noqa: E402
from astro.tools import registry  # noqa: E402
from astro.scripts import curated_data, train_book  # noqa: E402

BAD_FRAGMENTS = ("nie udało", "nie potrafię", "błąd", "[tool", "przepraszam", "nie wiem")


def _bad(text):
    t = (text or "").strip()
    if len(t) < 12:
        return True
    low = t.lower()
    return any(b in low for b in BAD_FRAGMENTS)


def _tool_calls(steps, base=0):
    out = []
    for i, s in enumerate(steps):
        call = {"id": f"call_{base + i}", "type": "function",
                "function": {"name": s.get("name", ""),
                             "arguments": json.dumps(s.get("args") or {}, ensure_ascii=False)}}
        out.append(call)
    return out


def record_from_trajectory(row):
    """Trajektoria -> rekord treningowy albo None (gdy się nie nadaje)."""
    goal = (row.get("goal") or "").strip()
    answer = (row.get("answer") or "").strip()
    if not goal or _bad(answer):
        return None
    try:
        steps = json.loads(row.get("steps_json") or "[]")
    except Exception:
        steps = []
    steps = [s for s in steps if isinstance(s, dict) and s.get("name")]
    if not steps:
        return {"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": goal},
                             {"role": "assistant", "content": answer}],
                "tools": []}
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": goal}]
    for i, s in enumerate(steps):
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": _tool_calls([s], base=i)})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "name": s.get("name", ""),
                     "content": str(s.get("result") or "")[:1500]})
    msgs.append({"role": "assistant", "content": answer})
    # Schematy narzędzi jak w RUNTIME (`registry.select` = max(MAX_TOOLS, core)), a nie pełne 32 —
    # model trenował się na dystrybucji promptu, której nigdy nie widzi na inferencji.
    # Dokładamy narzędzia faktycznie użyte w trajektorii, by `tool_calls` zawsze miały schemat.
    schemas = registry.select(goal)
    have = {s["function"]["name"] for s in schemas}
    all_schemas = {s["function"]["name"]: s for s in registry.schemas()}
    for s in steps:
        nm = s.get("name", "")
        if nm and nm not in have and nm in all_schemas:
            schemas.append(all_schemas[nm])
            have.add(nm)
    return {"messages": msgs, "tools": schemas}


def from_memory(db_path, limit=0):
    mem = Memory(db_path)
    rows = mem.con.execute(
        "SELECT kind, goal, steps_json, result, answer, source, ok FROM trajectories "
        "ORDER BY id").fetchall()
    out = []
    by_kind = {}
    for r in rows:
        rec = record_from_trajectory(dict(r))
        if rec is None:
            continue
        rec["_source"] = r["source"] or r["kind"]
        out.append(rec)
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    if limit:
        out = out[-limit:]
    return out, by_kind


def from_legacy(path, tool_names):
    """Tylko czysto-tekstowe tury z datasetu Ateny (bez niezgodnych schematów narzędzi)."""
    out = []
    for f in glob.glob(path):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                msgs = d.get("messages") or []
                if not msgs or any(m.get("tool_calls") for m in msgs):
                    continue
                answer = next((m.get("content") for m in reversed(msgs)
                               if m.get("role") == "assistant"), "")
                if _bad(answer):
                    continue
                out.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                         {"role": "user", "content": msgs[-1].get("content", "")},
                                         {"role": "assistant", "content": answer}],
                            "tools": [], "_source": "legacy"})
    return out


def dedup(records):
    seen, out = set(), []
    for r in records:
        key = (r["messages"][1].get("content", "").strip(),
               r["messages"][-1].get("content", "").strip()[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _goal(rec):
    msgs = rec.get("messages") or []
    return msgs[1].get("content", "") if len(msgs) > 1 else ""


def _semantic_key(rec):
    """Tekst do porównania podobieństwa: cel + początek odpowiedzi/kroku."""
    msgs = rec.get("messages") or []
    goal = _goal(rec)
    answer = msgs[-1].get("content", "") if msgs else ""
    return (goal + "\n" + (answer or "")[:200]).strip()


def main():
    ap = argparse.ArgumentParser(description="Budowa datasetu ASTRO (E6)")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--out", default=str(config.REPO / "datasets"))
    ap.add_argument("--legacy", action="store_true", help="dołącz czat z datasetu Ateny")
    ap.add_argument("--no-curated", action="store_true",
                    help="bez kuratorowanych rekordów czatu/łańcuchów")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--semantic-threshold", type=float, default=0.93,
                    help="próg dedup semantycznego przed treningiem (0 = tylko leksykalny)")
    ap.add_argument("--no-semantic-dedup", action="store_true",
                    help="wyłącz dedup semantyczny (reguła 2026-09-27: domyślnie WŁĄCZONY)")
    ap.add_argument("--avoid-out", default="",
                    help="plik listy „nie powtarzaj” z odrzuconych duplikatów "
                         "(domyślnie runtime/dups_avoid.txt)")
    ap.add_argument("--stats", action="store_true", help="tylko statystyki, nie zapisuj")
    args = ap.parse_args()

    records, by_kind = from_memory(args.db, limit=args.limit)
    if args.legacy:
        legacy = from_legacy(os.path.join(config.REPO, "datasets", "legacy_agent_episodes.jsonl"),
                             registry.names())
        if legacy:
            records.extend(legacy)
    curated = []
    if not args.no_curated:
        curated = curated_data.records()
        by_kind["curated"] = len(curated)
    # ROTACJA DUPLIKATÓW (reguła 2026-09-27): dedup SEMANTYCZNY przed treningiem/kwantyzacją;
    # odrzucone duplikaty trafiają na listę „nie powtarzaj" dla generatora świeżych danych.
    if not args.no_semantic_dedup and args.semantic_threshold > 0 and len(records) > 1:
        avoid_path = args.avoid_out or str(config.REPO / "runtime" / "dups_avoid.txt")
        keys = [_semantic_key(r) for r in records]
        try:
            embedder = default_memory().embedder
        except Exception:
            embedder = None
        keep, drop, _dups = train_book.semantic_dedup(
            keys, args.semantic_threshold, embedder, label="dedup semantyczny")
        if drop:
            train_book.write_avoid(avoid_path, [_goal(records[i]) for i in drop])
            print(f"[data] dedup semantyczny: odsiane {len(drop)} (lista „nie powtarzaj”: "
                  f"{avoid_path})")
        records = [records[i] for i in keep]
    records = dedup(records + curated)

    tools_records = [r for r in records if r.get("tools")]
    chat_records = [r for r in records if not r.get("tools")]
    print(f"[data] rekordy: {len(records)} (z narzędziami: {len(tools_records)}, "
          f"czat: {len(chat_records)}); wg kind: {by_kind}")
    for r in records:
        if not r.get("tools"):
            continue
        n = sum(1 for m in r["messages"] if m.get("tool_calls"))
        if n >= 2:
            print(f"[data]   łańcuch ({n} kroków): {r['messages'][1]['content'][:60]}")
    if args.stats:
        return 0

    # Podział GRUPAMI po znormalizowanym celu: warianty tego samego pytania (ta sama odpowiedź
    # inaczej sformułowana) nie mogą trafić jednocześnie do train i val (wyciek — m.in. 9 par).
    groups = {}
    for r in records:
        msgs = r.get("messages") or []
        goal = msgs[1].get("content", "") if len(msgs) > 1 else ""
        groups.setdefault(normalize_facts(goal), []).append(r)
    keys = list(groups)
    random.Random(args.seed).shuffle(keys)
    n_val = max(1, int(len(keys) * args.val_frac)) if len(keys) > 1 else 0
    val_keys = set(keys[:n_val])
    train, val = [], []
    for k, rs in groups.items():
        (val if k in val_keys else train).extend(rs)
    # Kuratorowane (czat/łańcuchy) ZAWSZE do treningu — nie walidujemy na własnych wzorcach.
    train += [r for r in val if r.get("_source") == "curated"]
    val = [r for r in val if r.get("_source") != "curated"]
    os.makedirs(args.out, exist_ok=True)
    for name, data in (("astro_train.jsonl", train), ("astro_val.jsonl", val)):
        path = os.path.join(args.out, name)
        with open(path, "w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[data] {path}: {len(data)}")
    manifest = {"db": args.db, "records": len(records), "train": len(train), "val": len(val),
                "tools_records": len(tools_records), "chat_records": len(chat_records),
                "by_kind": by_kind, "legacy": bool(args.legacy),
                "tool_count": len(registry.names())}
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(f"[data] manifest: {os.path.join(args.out, 'manifest.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
