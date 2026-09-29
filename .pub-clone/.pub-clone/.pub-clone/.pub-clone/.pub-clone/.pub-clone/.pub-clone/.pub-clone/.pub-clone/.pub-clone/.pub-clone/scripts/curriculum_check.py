#!/usr/bin/env python3
"""Weryfikacja pokrycia curriculum w bazie wiedzy ASTRO.

Obsługuje oba schematy curriculum:
  * `{"categories":[{"name","topics":[{"name","subtopics":[...]}]}]}`
  * `{"tematy":[{"tematyka_glowna","nazwa","qa":[{"pytanie","odpowiedz"}]}]}` (nowy, np. qa_baza)

Dla każdego tematu sprawdza, czy w ASTRO `learned` istnieje wpis ze słowami kluczowymi tematu.
Raportuje pokrycie per kategoria + brakujące tematy.

Użycie:
    python3 astro/scripts/curriculum_check.py --curriculum /etc/astro-secrets/qa_baza_wiedzy.json
    python3 astro/scripts/curriculum_check.py --min-hits 2
"""

import argparse
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
from astro.memory import Memory  # noqa: E402

DEFAULT_CURRICULUM = "/etc/astro-secrets/qa_baza_wiedzy.json"
STOP = {"i", "w", "na", "do", "z", "ze", "dla", "oraz", "the", "and", "of", "jej", "ich",
        "nowoczesny", "nowoczesne", "sektor", "nauki", "systemy", "technika", "jaka", "jaki",
        "jest", "jakie", "jak", "czy", "kiedy", "gdzie", "co", "to", "sie", "oraz", "przez",
        "jego", "jej", "przy", "tym", "tego", "mi", "sie", "tak", "nie", "oraz"}


def norm(text):
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c)).replace("ł", "l")


def keywords(topic):
    words = [w for w in re.findall(r"\w{4,}", norm(topic)) if w not in STOP]
    return words


def load_curriculum(data):
    """Normalizuje różne schematy do listy kategorii {'name','topics':[{'name','subtopics'}]}."""
    if data.get("categories"):
        return data["categories"]
    cats = {}
    for t in data.get("tematy") or []:
        cat = t.get("tematyka_glowna") or t.get("kategoria") or "?"
        sub = t.get("nazwa") or ""
        questions = [qa.get("pytanie", "") for qa in (t.get("qa") or [])
                     if isinstance(qa, dict) and qa.get("pytanie")]
        cats.setdefault(cat, []).append({"name": sub, "subtopics": questions})
    return [{"name": cat, "topics": topics} for cat, topics in cats.items()]


def main():
    ap = argparse.ArgumentParser(description="Pokrycie curriculum w wiedzy ASTRO")
    ap.add_argument("--curriculum", default=DEFAULT_CURRICULUM)
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--min-hits", type=int, default=1)
    ap.add_argument("--list-missing", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.curriculum):
        print(f"[curr] brak curriculum: {args.curriculum}", file=sys.stderr)
        return 2
    with open(args.curriculum, encoding="utf-8") as fh:
        data = json.load(fh)

    mem = Memory(args.db)
    rows = mem.con.execute("SELECT title, text FROM learned").fetchall()
    blob = norm(" ".join((r["title"] or "") + " " + (r["text"] or "") for r in rows))

    total_topics = covered = 0
    print(f"Curriculum: {args.curriculum}")
    print(f"Wiedza ASTRO: {len(rows)} wpisów `learned`\n")
    missing = []
    for cat in load_curriculum(data):
        topics = cat.get("topics", [])
        c_cov = 0
        for t in topics:
            total_topics += 1
            kws = keywords(t.get("name", ""))
            subs = t.get("subtopics") or []
            hits = sum(1 for k in kws if k in blob)
            sub_hits = sum(1 for s in subs
                           if any(k in blob for k in keywords(
                               s if isinstance(s, str) else (s.get("name") or ""))))
            ok = hits >= args.min_hits or (subs and sub_hits >= args.min_hits)
            c_cov += bool(ok)
            covered += bool(ok)
            if not ok:
                missing.append(f"{cat.get('name')} / {t.get('name')}")
        pct = c_cov / len(topics) * 100 if topics else 0
        print(f"  {cat.get('name', cat.get('id'))}: {c_cov}/{len(topics)} ({pct:.0f}%)")
    pct = covered / total_topics * 100 if total_topics else 0
    print(f"\nRAZEM: {covered}/{total_topics} tematów ({pct:.0f}%)")
    if missing:
        print(f"Brakujące tematy ({len(missing)}):")
        for m in missing[: (len(missing) if args.list_missing else 20)]:
            print(f"  - {m}")
        if not args.list_missing and len(missing) > 20:
            print(f"  ... (+{len(missing) - 20}, użyj --list-missing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
