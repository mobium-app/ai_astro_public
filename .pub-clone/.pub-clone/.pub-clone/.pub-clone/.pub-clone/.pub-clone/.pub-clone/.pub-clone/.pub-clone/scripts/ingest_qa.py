#!/usr/bin/env python3
"""Ingest bazy Q&A do `learned` ASTRO + pomiar pokrycia offline.

Obsługuje dwa schematy:
  * nowy:  {"tematy": [{"tematyka_glowna", "nazwa", "qa": [{"pytanie","odpowiedz"}]}]}
  * stary: {"categories": [{"name", "topics": [{"name","subtopics":[...]}]}]}  (best-effort)

Rekord -> `learned`: topic=<kategoria> / <podkategoria>, title=pytanie, text=odpowiedź,
source=<--source> (domyślnie `qa_baza`), verified=False. Bramka jakości (`_good_learned`)
odrzuca szum; dedup globalny po pytaniu; wektory embeddingowe zapisywane przy insercie.

Użycie:
    python3 astro/scripts/ingest_qa.py --dry-run --stats
    python3 astro/scripts/ingest_qa.py                 # wgraj do runtime/memory.db
    python3 astro/scripts/ingest_qa.py --measure       # pokrycie 1020 pytań offline
    python3 astro/scripts/ingest_qa.py --backfill      # wektory dla istniejących `learned`
"""

import argparse
import collections
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.memory import Memory, offline_facts_answer  # noqa: E402
from astro.memory.embed import OllamaEmbedder  # noqa: E402
from astro.memory.store import _good_learned  # noqa: E402

DEFAULT_FILE = "/etc/astro-secrets/qa_baza_wiedzy.json"


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ł", "l")
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def load_records(path):
    """JSON -> lista (kategoria, podkategoria, pytanie, odpowiedź)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for t in data.get("tematy") or []:
        cat = t.get("tematyka_glowna") or t.get("kategoria") or ""
        sub = t.get("nazwa") or ""
        for qa in t.get("qa") or []:
            q = (qa.get("pytanie") or "").strip()
            a = (qa.get("odpowiedz") or qa.get("odpowiedź") or "").strip()
            if q and a:
                out.append((cat, sub, q, a))
    for c in data.get("categories") or []:  # schemat stary (best-effort)
        cat = c.get("name") or ""
        for t in c.get("topics") or []:
            sub = t.get("name") or ""
            for qa in (t.get("qa") or t.get("subtopics") or []):
                if isinstance(qa, str):
                    continue
                q = (qa.get("pytanie") or qa.get("question") or "").strip()
                a = (qa.get("odpowiedz") or qa.get("answer") or "").strip()
                if q and a:
                    out.append((cat, sub, q, a))
    return out


def make_memory(db):
    embedder = OllamaEmbedder(config.LLM_URL, config.EMBED_MODEL) if config.EMBED_MODEL else None
    return Memory(db, embedder=embedder)


def stats(records):
    cats = collections.Counter(cat for cat, _, _, _ in records)
    print(f"Rekordów Q&A: {len(records)} | kategorie: {len(cats)}")
    for cat, n in cats.most_common():
        print(f"  {n:5d}  {cat}")


def measure(mem, records, source):
    facts = learned = missing = 0
    for cat, sub, q, a in records:
        if offline_facts_answer(q):
            facts += 1
            continue
        if mem.best_learned(q):
            learned += 1
        else:
            missing += 1
    total = len(records) or 1
    print(f"\n== POKRYCIE OFFLINE (bez remote/modelu) ==")
    print(f"  facts.txt:        {facts:5d} ({facts * 100 // total}%)")
    print(f"  learned (retrieval): {learned:5d} ({learned * 100 // total}%)")
    print(f"  brak odpowiedzi:  {missing:5d} ({missing * 100 // total}%)")
    print(f"  razem:            {len(records)}")
    print(f"  wektory learned:  {mem.learned_vector_count()}")


def main():
    ap = argparse.ArgumentParser(description="Ingest bazy Q&A do learned ASTRO")
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--source", default="qa_baza")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stats", action="store_true", help="tylko statystyki pliku")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--backfill", action="store_true", help="wektory dla istniejących learned")
    ap.add_argument("--replace-source", action="store_true", help="usuń istniejące wpisy --source")
    ap.add_argument("--batch", type=int, default=100)
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print(f"[qa] brak pliku: {args.file}", file=sys.stderr)
        return 2
    records = load_records(args.file)
    if args.limit:
        records = records[:args.limit]
    stats(records)

    if args.stats:
        return 0
    if args.dry_run:
        seen = set()
        dup = rejected = ok = 0
        for _, _, q, a in records:
            key = norm(q)
            if key in seen:
                dup += 1
                continue
            seen.add(key)
            if _good_learned(q, a):
                ok += 1
            else:
                rejected += 1
        print(f"\n[dry-run] do wgrania: {ok} | duplikaty: {dup} | odrzucone (gate): {rejected}")
        return 0

    mem = make_memory(args.db)

    if args.backfill:
        n = mem.backfill_learned_vectors()
        print(f"[qa] backfill wektorów: +{n} (razem {mem.learned_vector_count()})")
        return 0

    if args.replace_source:
        cur = mem.con.execute("DELETE FROM learned WHERE source=?", (args.source,))
        mem.con.commit()
        print(f"[qa] usunięto {cur.rowcount} wpisów source={args.source}")

    seen = set()
    added = dup = rejected = 0
    for i, (cat, sub, q, a) in enumerate(records, 1):
        key = norm(q)
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        topic = f"{cat} / {sub}".strip(" /")
        rid = mem.add_learned(topic, q, a, source=args.source, verified=False, confidence=0.7)
        if rid:
            added += 1
        else:
            rejected += 1
        if args.batch and i % args.batch == 0:
            print(f"  ... {i}/{len(records)} (dodane={added}, dup={dup}, gate={rejected})",
                  flush=True)
    print(f"[qa] dodane={added} duplikaty={dup} odrzucone={rejected} | "
          f"wektory={mem.learned_vector_count()} | learned={mem.learned_count()}")

    if args.measure:
        measure(mem, records, args.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
