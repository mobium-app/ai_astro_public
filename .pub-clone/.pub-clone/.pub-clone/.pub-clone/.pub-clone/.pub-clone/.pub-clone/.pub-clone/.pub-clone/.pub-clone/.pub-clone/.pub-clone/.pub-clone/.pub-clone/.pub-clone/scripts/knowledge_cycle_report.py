#!/usr/bin/env python3
"""Automatyczne podsumowanie cyklu nauki: dodane/duble/nieudane/rundy/czas + pasek postępu.

Reguła 2026-09-27: każdy raport treningu/nauki ma graficzny pasek (jakość, tempo, ETA).
Użycie:
    python3 astro/scripts/knowledge_cycle_report.py            # ostatni bieg
    python3 astro/scripts/knowledge_cycle_report.py --all      # wszystkie biegi
    ... --append runtime/logs/cycle_reports.log                # dopisz (auto w pętli)
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astro.scripts import train_book  # noqa: E402

LOG = ROOT / "runtime" / "logs" / "knowledge_loop.log"
_TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"


def parse_runs(path):
    """Zwraca listę biegów pętli: start/koniec, learned A->B, dodane/duble/nieudane/rundy."""
    runs = []
    cur = None
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return runs
    for ln in lines:
        m = re.search(_TS + r" .*===== runda (\d+) start \(learned=(\d+)\)", ln)
        if m:
            cur = {"ts": m.group(1), "round": int(m.group(2)), "before": int(m.group(3))}
            runs.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r"KONIEC dodane=(\d+) duble=(\d+) nieudane=(\d+) .*rund=(\d+)", ln)
        if m:
            cur.update(added=int(m.group(1)), dup=int(m.group(2)),
                       failed=int(m.group(3)), rounds=int(m.group(4)))
            continue
        m = re.search(_TS + r" .*runda (\d+) koniec: learned (\d+) -> (\d+) \(\+(\d+)\)", ln)
        if m:
            cur.update(ts_end=m.group(1), after=int(m.group(4)), delta=int(m.group(5)))
    return runs


def _dur(a, b):
    try:
        d = datetime.strptime(b, "%Y-%m-%d %H:%M:%S") - datetime.strptime(a, "%Y-%m-%d %H:%M:%S")
        mins = int(d.total_seconds() // 60)
        return f"{mins // 60}h {mins % 60}min"
    except Exception:
        return "?"


def format_run(r, target=0):
    if r.get("after") is None:
        return f"runda {r['round']}: w toku (learned={r['before']})"
    delta = r.get("delta", 0)
    added = r.get("added", delta)
    dup = r.get("dup", 0)
    failed = r.get("failed", 0)
    rounds = r.get("rounds", 0)
    tgt = target or added
    bar = train_book.report_line(delta, tgt, label=f"bieg {r['round']}:")
    pct_dup = (dup * 100 // (added + dup)) if (added + dup) else 0
    return (f"{bar} | dodane={added} duble={dup} ({pct_dup}%) nieudane={failed} rund={rounds} "
            f"| learned {r['before']}->{r['after']} | czas {_dur(r['ts'], r['ts_end'])}")


def main():
    ap = argparse.ArgumentParser(description="Podsumowanie cyklu nauki (pasek + statystyki)")
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--all", action="store_true", help="wszystkie biegi (domyślnie ostatni)")
    ap.add_argument("--target", type=int, default=0, help="cel paska (domyślnie = dodane)")
    ap.add_argument("--append", default="", help="dopisz wynik do pliku")
    args = ap.parse_args()

    runs = [r for r in parse_runs(args.log) if r.get("after") is not None]
    if not runs:
        print("[cycle] brak zakończonych biegów w logu")
        return 0
    sel = runs if args.all else runs[-1:]
    out = [format_run(r, args.target) for r in sel]
    text = "\n".join(out)
    print(text)
    if args.append:
        try:
            with open(args.append, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
