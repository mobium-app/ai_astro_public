#!/usr/bin/env python3
"""Kontrola jakości bazy wiedzy `learned`: odsiewa szum z wpisów zdalnych/nauczyciela.

Wpisy spoza źródeł kuratorowanych (`remote_knowledge:*`, `web`, `atena`, `legacy`) bywają
zanieczyszczone i psują retrieval offline:

  * **META** — model-nauczyciel zwrócił instrukcje „jak zadawać pytania" zamiast odpowiedzi,
  * **TRUNC** — pytanie ucięte w połowie (brak „?" i kończy się fragmentem frazy),
  * **REFUSAL** — odpowiedź to odmowa/„podaj pełne pytanie" zamiast wiedzy.

Domyślnie tryb `--dry-run` (tylko raport). `--apply` usuwa wpisy z `learned` wraz z wektorami.
Źródła kuratorowane (`facts`, `first_aid`) oraz wpisy `verified=1` nie są ruszane.

Użycie:
    python3 astro/scripts/knowledge_prune.py --dry-run
    python3 astro/scripts/knowledge_prune.py --apply
    python3 astro/scripts/knowledge_prune.py --dry-run --sources remote_knowledge:%
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.memory import Memory  # noqa: E402
from astro.memory.store import _good_learned  # noqa: E402

CURATED = ("facts", "first_aid")

META_RE = re.compile(
    r"^(każde (z )?pytani|pytania (powinny|nie powinny|mogą|dotyczą|muszą|są|zostały)|"
    r"odpowiedzi( na pytania)? powinny|bądź |dodaj |dopasuj|dostosuj|dostarczaj|"
    r"odpowiadaj|odpowiedz |postaraj|pamiętaj|celem jest|lista pytań|"
    r"możesz zadawać|opracuj|sformułuj|wygeneruj|stwórz |przygotuj|zadbaj|zachowaj|"
    r"unikaj|rozważ|upewnij|staraj)", re.I)
META_ANY = re.compile(
    r"(pytanie powinno|pytania powinny|odpowiedzi powinny|"
    r"asystent(owi|a)?\b.*(odpowied|pytan))", re.I)

QSTART_RE = re.compile(
    r"^(jak|jaka|jakie|jaki|dlaczego|czym|kto|gdzie|kiedy|ile|czy|co|w jaki)\b", re.I)
DANGLING = {"w", "we", "z", "ze", "do", "na", "o", "i", "a", "że", "się", "od", "po",
            "dla", "jak", "nad", "pod", "przez", "między", "oraz", "lub", "czy", "niż",
            "ale", "bo", "gdy", "aby", "żeby", "the", "of", "to"}
REFUSAL_RE = re.compile(
    r"(podaj pełne pytanie|proszę podać|nie jest jasne|nie wiem|nie mogę|nie potrafię|"
    r"przepraszam|nie rozumiem|doprecyzuj|sprecyzuj|brakuje pytania|nie zostało podane|"
    r"podaj pytanie|zadaj pełne)", re.I)

_TOK = re.compile(r"[a-ząćęłńóśźż0-9]+", re.I)


def _tokens(text):
    return _TOK.findall((text or "").lower())


def _fragment_vocab(rows):
    """Zbiór tokenów-fragmentów: krótszy token będący prefiksem dłuższego („róż", „popular")."""
    vocab = set()
    for r in rows:
        vocab.update(t for t in _tokens(r["title"]) if len(t) >= 3)
    frags = set()
    for t in vocab:
        if len(t) < 4:
            continue
        for other in vocab:
            if len(other) > len(t) and other.startswith(t):
                frags.add(t)
                break
    return frags


def classify(row, frags):
    """Zwraca (powód|None) dla wpisu: META / TRUNC / REFUSAL."""
    title = (row["title"] or "").strip()
    text = (row["text"] or "").strip()
    if META_RE.search(title) or META_ANY.search(title):
        return "META"
    if REFUSAL_RE.search(text):
        return "REFUSAL"
    if QSTART_RE.match(title) and "?" not in title:
        toks = _tokens(title)
        last = toks[-1] if toks else ""
        if len(title) < 45 or last in DANGLING or (last in frags and len(last) <= 9):
            return "TRUNC"
    if not _good_learned(title, text):
        return "GATE"
    return None


def main():
    ap = argparse.ArgumentParser(description="Odsiewa szum z `learned` (meta/ucięte/odmowy)")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--sources", default="", help="filtr LIKE na source (np. remote_knowledge:%)")
    ap.add_argument("--apply", action="store_true", help="usuń wpisy (domyślnie tylko raport)")
    ap.add_argument("--dry-run", action="store_true", help="jawny tryb raportu (domyślny)")
    ap.add_argument("--delete-gate", action="store_true",
                    help="usuń też wpisy odrzucane przez bramkę _good_learned (ostrożnie!)")
    ap.add_argument("--buckets", default="META,TRUNC,REFUSAL",
                    help="kategorie do usunięcia (domyślnie META,TRUNC,REFUSAL; np. 'META,REFUSAL'). "
                         "TRUNC bywa fałszywie dodatni przy poprawnych pytaniach bez '?'")
    ap.add_argument("--include-curated", action="store_true", help="nie pomijaj facts/first_aid")
    ap.add_argument("--show", type=int, default=40, help="ile przykładów wypisać")
    args = ap.parse_args()

    mem = Memory(args.db)
    rows = mem.con.execute("SELECT id,title,text,source,verified FROM learned").fetchall()
    if args.sources:
        like = args.sources.replace("%", "%")
        rows = [r for r in rows if r["source"] and _like(r["source"], like)]
    if not args.include_curated:
        rows = [r for r in rows if r["source"] not in CURATED]

    frags = _fragment_vocab(rows)
    buckets = {"META": [], "TRUNC": [], "REFUSAL": [], "GATE": []}
    for r in rows:
        reason = classify(r, frags)
        if reason:
            buckets[reason].append(r)

    total = sum(len(v) for v in buckets.values())
    print(f"== knowledge_prune: {args.db} ==")
    print(f"przeskanowano (poza kuratorowanymi): {len(rows)} | do usunięcia: {total}")
    for name in ("META", "TRUNC", "REFUSAL", "GATE"):
        print(f"  {name:8s}: {len(buckets[name])}")
    for name in ("META", "TRUNC", "REFUSAL", "GATE"):
        for r in buckets[name][: args.show]:
            print(f"   [{name}] #{r['id']} {r['source']} :: {r['title'][:70]}")

    if not args.apply:
        print("\n[dry-run] nic nie zmieniono (użyj --apply, aby usunąć)")
        return 0

    wanted = {b.strip().upper() for b in args.buckets.split(",") if b.strip()}
    names = [n for n in ("META", "TRUNC", "REFUSAL") if n in wanted]
    if args.delete_gate:
        names.append("GATE")
    ids = [r["id"] for name in names for r in buckets[name]]
    if not ids:
        print("[apply] brak wpisów do usunięcia")
        return 0
    marks = ",".join("?" * len(ids))
    mem.con.execute(f"DELETE FROM learned_vectors WHERE learned_id IN ({marks})", ids)
    cur = mem.con.execute(f"DELETE FROM learned WHERE id IN ({marks})", ids)
    mem.con.commit()
    print(f"\n[apply] usunięto learned={cur.rowcount}, razem learned={mem.learned_count()}, "
          f"wektory={mem.learned_vector_count()}")
    return 0


def _like(value, pattern):
    regex = "^" + re.escape(pattern).replace("%", ".*") + "$"
    return re.match(regex, value) is not None


if __name__ == "__main__":
    sys.exit(main())
