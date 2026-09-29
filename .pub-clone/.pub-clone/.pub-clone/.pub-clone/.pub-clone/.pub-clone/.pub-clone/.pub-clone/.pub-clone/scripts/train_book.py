#!/usr/bin/env python3
"""PRAKTYKI TRENINGU ASTRO (reguła użytkownika 2026-09-27) — stosowane do KAŻDEGO treningu.

Zasada: **jakość lepsza w krótszym czasie przy tym samym zużyciu energii**. Powtarzalne elementy:
  1. **Graficzny pasek postępu** w każdym raporcie (done/target, tempo, ETA) — `report_line()`.
  2. **Dedup semantyczny** kandydatów PRZED treningiem/kwantyzacją — `semantic_dedup()`.
  3. **Rotacja duplikatów → świeże dane** (odrzucone wracają jako lista „nie powtarzaj") —
     `write_avoid()` / `load_avoid()`; generacja przez `remote_ai` + OpenCode (jakość > koszt).
  4. **Generator jakościowy z walidacją partii** (nie pierwszy lepszy dostawca) — patrz
     `remote_knowledge.generator_chain` + `_invent_questions`.
"""
import time


def bar(pct, width=30):
    """Graficzny pasek postępu: [████░░░░] (pct 0..100)."""
    pct = max(0, min(100, int(pct)))
    filled = pct * width // 100
    return "█" * filled + "░" * (width - filled)


def report_line(done, target, start_ts=None, label="", width=30, extra=""):
    """Jednolinijkowy raport z paskiem: `label done/target [bar] pct% | tempo | ETA`."""
    target = max(0, int(target))
    done = max(0, int(done))
    pct = (done * 100 // target) if target else 0
    rate = "?"; eta = "?"
    if start_ts and done > 0:
        elapsed = max(0.001, time.time() - start_ts)
        per_min = done / elapsed * 60.0
        rate = f"{per_min:.0f}/min"
        if per_min > 0 and target > done:
            eta = f"{(target - done) / per_min:.0f} min"
    seg = f"{label} " if label else ""
    return f"{seg}{done}/{target} [{bar(pct, width)}] {pct}% | tempo {rate} | ETA {eta}{extra}"


def semantic_dedup(keys, threshold=0.93, embedder=None, label="dedup", progress=True):
    """Zachowawczy dedup semantyczny (cosine). Zwraca (keep_idx, drop_idx, dup_keys).

    Zachłannie: rekord zostaje, gdy maksymalne podobieństwo do już zachowanych < `threshold`.
    Bez embeddera/przy <2 rekordach = brak odsiewu (bezpieczny fallback)."""
    n = len(keys)
    if not embedder or threshold <= 0 or n < 2:
        return list(range(n)), [], []
    try:
        import numpy as np
    except Exception:
        return list(range(n)), [], []
    t0 = time.time()
    dim = 0
    rows = []
    for i, k in enumerate(keys):
        v = embedder(k or "")
        rows.append(v)
        if v and not dim:
            dim = len(v)
        if progress and i and i % 50 == 0:
            print("[train] " + report_line(i, n, t0, label=label), flush=True)
    if not dim:
        return list(range(n)), [], []
    mat = np.zeros((n, dim), dtype=np.float32)
    have = np.zeros(n, dtype=bool)
    for i, v in enumerate(rows):
        if v:
            mat[i] = v[:dim]
            have[i] = True
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = mat / norms
    sims = unit @ unit.T
    keep = np.ones(n, dtype=bool)
    for i in range(n):
        if not keep[i]:
            continue
        similar = np.where((sims[i] >= threshold) & (np.arange(n) > i))[0]
        keep[similar] = False
    keep_idx = [i for i in range(n) if keep[i]]
    drop_idx = [i for i in range(n) if not keep[i]]
    dups = [keys[i] for i in drop_idx]
    if progress:
        print("[train] " + report_line(n, n, t0, label=label)
              + f" | odsiane dup={len(drop_idx)}", flush=True)
    return keep_idx, drop_idx, dups


def write_avoid(path, goals):
    """Dopisz odrzucone duplikaty do listy „nie powtarzaj" (rotacja → świeże dane)."""
    if not path or not goals:
        return 0
    try:
        seen = set()
        try:
            with open(path, encoding="utf-8") as fh:
                seen = {ln.strip() for ln in fh if ln.strip()}
        except OSError:
            pass
        new = []
        for g in goals:
            g = (g or "").strip()
            if g and g not in seen:
                seen.add(g)
                new.append(g)
        if new:
            with open(path, "a", encoding="utf-8") as fh:
                for g in new:
                    fh.write(g + "\n")
        return len(new)
    except OSError:
        return 0


def load_avoid(path, limit=200):
    """Wczytaj listę „nie powtarzaj" (dla generatora świeżych danych)."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        return lines[-limit:]
    except OSError:
        return []
