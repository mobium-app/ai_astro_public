#!/usr/bin/env python3
"""ASTRO — ciągły nasłuch wizji (Faza 2): zdarzenia obecności/twarzy -> inicjatywa.

Próbkuje kamerę co `--interval` sekund, rozpoznaje twarze (baza ASTRO) i wykrywa zdarzenia:
  * nieznana osoba w kadrze  -> alert („Uwaga, widzę w pokoju nieznaną osobę."),
  * rozpoznana osoba po przerwie -> powitanie („Widzę Cię, <imię>.").
Zdarzenia respektują politykę `core/initiative` (tryb cichy, cisza nocna, cooldown, limit/h).
Wypowiedź przez TTS (można wyłączyć `--no-speak` / `ASTRO_WATCH_SPEAK=0`). Zdarzenia zapisywane
w `runtime/vision_events.jsonl`.

Uruchomienie:  python3 scripts/vision_watch.py            # pętla (systemd astro-vision-watch)
              python3 scripts/vision_watch.py --once      # jeden cykl (diagnostyka)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(os.path.dirname(_HERE)), os.path.dirname(_HERE), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from astro import config  # noqa: E402
from astro.core.initiative import Initiative  # noqa: E402
from astro.tools import vision  # noqa: E402


def _state_path():
    return os.path.join(str(config.RUNTIME_DIR), "vision_watch.json")


def _events_path():
    return os.path.join(str(config.RUNTIME_DIR), "vision_events.jsonl")


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh) or {}
    except (OSError, ValueError):
        d = {}
    return {"last_unknown": float(d.get("last_unknown") or 0),
            "last_name": {str(k): float(v) for k, v in (d.get("last_name") or {}).items()}}


def save_state(path, state):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def plan_events(state, known, unknown, now, unknown_cd=300.0, known_cd=1800.0):
    """Czysta logika zdarzeń: zwraca (lista_tekstów, nowy_stan). Bez I/O i bez mówienia."""
    texts = []
    if unknown > 0 and now - state["last_unknown"] >= unknown_cd:
        texts.append(("alert", "Uwaga, widzę w pokoju nieznaną osobę."))
        state["last_unknown"] = now
    for name in known:
        if now - state["last_name"].get(name, 0) >= known_cd:
            texts.append(("return", f"Widzę Cię, {name}."))
            state["last_name"][name] = now
    return texts, state


def change_events(img, objects, now, cd_state):
    """Zdarzenia zmiany kadru (ruch/wejście-wyjście/nowe obiekty) na podstawie odcisku klatki.

    Zwraca (lista (kind,text), zaktualizowane cooldowny). Odcisk trzymamy w osobnym stanie
    `runtime/vision_diff.json`. Bezpieczne: brak cv2/starego stanu → pusta lista.
    """
    try:
        from astro.vision import diff as vdiff
        fp = vdiff._fingerprint(img)
        st = vdiff.load_state()
        prev_fp = vdiff.fingerprint_from_state(st)
        metrics = vdiff.diff_frame(prev_fp, fp)
        prev_labels = set(st.get("labels") or [])
        cur_labels = {o["label"] for o in (objects or [])}
        prev_occ, cur_occ = bool(st.get("occupied")), bool(cur_labels & {"person"})
        if not prev_labels and not st:
            prev_occ, cur_occ = cur_occ, cur_occ  # pierwszy cykl: brak zdarzeń wejścia/wyjścia
        texts, cd_state = vdiff.plan_change_events(
            prev_labels, cur_labels, prev_occ, cur_occ,
            metrics["motion"], metrics["scene_change"], cd_state, now)
        st.update(vdiff.state_from_fingerprint(fp))
        st["labels"] = sorted(cur_labels)
        st["occupied"] = cur_occ
        vdiff.save_state(st)
        return texts, cd_state
    except Exception:
        return [], cd_state



def cycle(memory, initiative, remember=True, speak=True, tts=None, state=None,
          state_path=None, now=None, unknown_cd=300.0, known_cd=1800.0, log=print):
    """Jeden cykl: klatka -> twarze -> zdarzenia (inicjatywa) -> ewentualna wypowiedź."""
    now = time.time() if now is None else float(now)
    # Twardy „watch off" (Faza 6): nie analizujemy nawet klatki, gdy nasłuch wyłączony.
    try:
        from astro.vision import privacy
        if privacy.watch_off():
            return []
    except Exception:
        pass
    frame = vision.capture_frame()
    img = vision._load_bgr(frame) if frame else None
    if img is None:
        return []
    if max(img.shape[:2]) > 1280:
        import cv2
        s = 1280.0 / max(img.shape[:2])
        img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)),
                         interpolation=cv2.INTER_AREA)
    entries = vision.face_entries(img, memory)
    known = sorted({e["name"] for e in entries if e["name"]})
    unknown = sum(1 for e in entries if not e["name"])
    # Sylwetka (re-ID): gdy twarzy nie widać, a są zapisane sylwetki — uzupełnij rozpoznanie.
    if not known and memory is not None:
        try:
            from astro.vision import engine
            if getattr(config, "BODY_ENABLED", True) and engine.available("bodies") \
                    and memory.list_bodies():
                for box in engine.person_boxes(img):
                    emb = engine.person_embedding(img, box)
                    if emb is None:
                        continue
                    name, _score = memory.match_body(
                        emb, getattr(config, "BODY_MATCH_THRESHOLD", 0.55))
                    if name and name not in known:
                        known.append(name)
        except Exception:
            pass
    state = state if state is not None else load_state(state_path or _state_path())
    planned, state = plan_events(state, known, unknown, now, unknown_cd, known_cd)
    # Zdarzenia zmiany kadru (Faza 2): ruch / wejście-wyjście / nowe obiekty. Opt-in:
    # ASTRO_WATCH_CHANGE=0 wyłącza. Respektują te same cooldowny inicjatywy.
    if getattr(config, "WATCH_CHANGE", True):
        try:
            from astro.vision import engine
            objects = engine.detect_objects(img) if engine.available("objects") else []
        except Exception:
            objects = []
        ch_texts, cd = change_events(img, objects, now,
                                     (state.get("change_cd") or {}))
        state["change_cd"] = cd
        planned = list(planned) + ch_texts
    spoken = []
    for kind, text in planned:
        allowed = initiative.event(text, kind=kind, now=now)
        if not allowed:
            continue
        spoken.append(allowed)
        log(f"[watch] {kind}: {allowed}")
        if remember:
            try:
                with open(_events_path(), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"ts": now, "kind": kind, "text": allowed,
                                         "known": known, "unknown": unknown},
                                        ensure_ascii=False) + "\n")
            except OSError:
                pass
        if speak and tts is not None:
            try:
                tts.speak(allowed)
            except Exception as e:
                log(f"[watch] TTS błąd: {e}")
    save_state(state_path or _state_path(), state)
    return spoken


def main():
    ap = argparse.ArgumentParser(description="ASTRO — ciągły nasłuch wizji (Faza 2)")
    ap.add_argument("--interval", type=float,
                    default=float(os.environ.get("ASTRO_WATCH_INTERVAL", "20")))
    ap.add_argument("--once", action="store_true", help="jeden cykl (diagnostyka)")
    ap.add_argument("--no-speak", action="store_true")
    ap.add_argument("--unknown-cooldown", type=float,
                    default=float(os.environ.get("ASTRO_WATCH_UNKNOWN_CD", "300")))
    ap.add_argument("--known-cooldown", type=float,
                    default=float(os.environ.get("ASTRO_WATCH_KNOWN_CD", "1800")))
    args = ap.parse_args()
    speak = not args.no_speak and os.environ.get("ASTRO_WATCH_SPEAK", "1").lower() not in \
        ("0", "false", "no", "off")
    from astro.memory import default_memory
    memory = default_memory()
    init = Initiative()
    tts = None
    if speak:
        try:
            from astro.audio.tts import TTS
            tts = TTS()
        except Exception as e:
            print(f"[watch] brak TTS: {e}")
            speak = False
    print(f"[watch] start (interval={args.interval}s, speak={speak}, "
          f"quiet={init.is_quiet()})")
    while True:
        try:
            cycle(memory, init, speak=speak, tts=tts,
                  unknown_cd=args.unknown_cooldown, known_cd=args.known_cooldown,
                  log=lambda m: print(m, flush=True))
        except Exception as e:
            print(f"[watch] błąd cyklu: {e}", flush=True)
        if args.once:
            return 0
        time.sleep(max(2.0, args.interval))


if __name__ == "__main__":
    sys.exit(main())
