#!/usr/bin/env python3
"""Status cyklu treningowego ASTRO: dataset, egzamin, postęp maszyn, ETA.

Uruchom bez argumentów (raport teraz) albo z --write (dopisz status JSON):
    python3 astro/scripts/train_cycle_status.py
    python3 astro/scripts/train_cycle_status.py --iter 3 --start 1789... --rc 0 --write
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
A = ROOT
LOGDIR = os.path.join(A, "runtime", "logs")
STATUS = os.path.join(A, "runtime", "train_cycle_status.json")
GENDIR = os.path.join(A, "runtime", "gauge")  # nieużywane
MACH = {
    "pc-max":   ("PC-MAX qwen3:30b-a3b (tools)", "http://127.0.0.1:11436"),
    "pc2":      ("PC-2  bielik-11b     (chat) ", "http://127.0.0.1:11437"),
    "pc":       ("PC    bielik-11b     (chat) ", "http://127.0.0.1:11435"),
    "kali":     ("KALI  bielik-11b     (tools)", "http://127.0.0.1:11435"),
    "kalichat": ("KALI  bielik-11b     (chat) ", "http://127.0.0.1:11435"),
}


def lines(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []


def bar(frac, w=20):
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * w))
    return "█" * n + "░" * (w - n)


def count(path, name):
    try:
        with open(path, encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def online(url, ttl=3):
    try:
        req = __import__("urllib.request", fromlist=["Request"]).Request(
            url + "/api/version")
        with __import__("urllib.request", fromlist=["urlopen"]).urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def gen_progress():
    """Postęp generacji z bieżącej iteracji (ostatni blok [prog] + expand)."""
    ls = lines(os.path.join(LOGDIR, "cycle_gen.log"))
    idx = [i for i, ln in enumerate(ls) if "równolegle:" in ln]
    seg = ls[idx[-1]:] if idx else ls[-200:]
    prog = {}
    for ln in seg:
        m = re.search(r"\[prog\] (\S+) (\d+)/(\d+)", ln)
        if m:
            prog[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        m = re.search(r"^  (\S+): dodane=(\d+) odrzucone=(\d+) cele=(\d+)", ln)
        if m:
            prog[m.group(1)] = (int(m.group(4)), int(m.group(4)))
    # faza expand (gdy brak [prog]): ostatni "expand k/N"
    expand = None
    for ln in reversed(ls[-400:]):
        m = re.search(r"expand (\d+)/(\d+)", ln)
        if m:
            expand = (int(m.group(1)), int(m.group(2)))
            break
    return prog, expand


def last_gate(iter_n):
    ls = lines(os.path.join(LOGDIR, f"gate_iter{iter_n}.log"))
    res = {}
    for ln in ls:
        m = re.match(r"^(PASS|FAIL) (\w+)\s*: (\d+)/(\d+)", ln)
        if m:
            res[m.group(2)] = (int(m.group(3)), int(m.group(4)), m.group(1))
        if ln.startswith("WYNIK:"):
            res["_wynik"] = ln.split(":", 1)[1].strip()
    return res


def find_status(path):
    ls = lines(os.path.join(LOGDIR, "cycle.log"))
    for ln in reversed(ls):
        m = re.search(r"iter (\d+) koniec", ln)
        if m:
            return int(m.group(1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", type=int, default=0)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--rc", type=int, default=0)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    tr = count(os.path.join(A, "datasets", "astro_train.jsonl"), "")
    va = count(os.path.join(A, "datasets", "astro_val.jsonl"), "")
    try:
        import sqlite3
        sys.path.insert(0, os.path.dirname(ROOT))
        from astro import config
        con = sqlite3.connect(str(config.DB_PATH))
        agent = con.execute("SELECT COUNT(*) FROM trajectories WHERE kind='agent'").fetchone()[0]
        tools = con.execute("SELECT COUNT(*) FROM trajectories WHERE kind='agent' AND "
                            "steps_json NOT IN ('[]','')").fetchone()[0]
    except Exception:
        agent = tools = 0

    prog, expand = gen_progress()
    status = {"ts": time.time(), "iter": args.iter, "train": tr, "val": va,
              "agent": agent, "agent_tools": tools, "rc": args.rc, "machines": {}}
    # czas startu bieżącej iteracji (do ETA fazy expand)
    it_start = None
    try:
        it_start = float(open(os.path.join(LOGDIR, "iter_start")).read().split()[0])
    except Exception:
        pass
    print(f"=== ASTRO CYKL — raport {time.strftime('%F %T')} ===")
    print(f"dataset: train={tr} val={va} | trajektorie: agent={agent} (z narzędziami={tools})")
    if expand and not prog:
        frac = expand[0] / expand[1] if expand[1] else 0
        eta = ""
        if it_start and expand[0]:
            rem = (time.time() - it_start) * (expand[1] - expand[0]) / expand[0]
            eta = f" ETA ~{int(rem // 60)}m{int(rem % 60):02d}s"
        print(f"  faza: BUDOWA BANKU SEEDÓW (expand PC-MAX) [{bar(frac)}] "
              f"{expand[0]}/{expand[1]}{eta}")
    for key, (name, url) in MACH.items():
        up = online(url)
        if key in prog:
            done, total = prog[key]
            pct = done / total if total else 0
            print(f"  {name} [{bar(pct)}] {done}/{total} {'ONLINE' if up else 'OFFLINE'}")
        else:
            print(f"  {name} [brak bieżącego zadania] {'ONLINE' if up else 'OFFLINE'}")
        status["machines"][key] = {"online": up, "progress": prog.get(key)}
    if args.iter:
        g = last_gate(args.iter)
        if g:
            parts = " | ".join(f"{k} {v[0]}/{v[1]} {v[2]}" for k, v in g.items() if k != "_wynik")
            print(f"egzamin iter {args.iter}: {parts} | WYNIK={g.get('_wynik','?')}")
            status["gate"] = g
        if args.start:
            dur = time.time() - args.start
            print(f"czas iteracji {args.iter}: {int(dur//60)}m{int(dur%60):02d}s")
            status["iter_secs"] = dur
    if find_status:
        status["last_done_iter"] = find_status(STATUS)
    if args.write:
        with open(STATUS, "w", encoding="utf-8") as fh:
            json.dump(status, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
