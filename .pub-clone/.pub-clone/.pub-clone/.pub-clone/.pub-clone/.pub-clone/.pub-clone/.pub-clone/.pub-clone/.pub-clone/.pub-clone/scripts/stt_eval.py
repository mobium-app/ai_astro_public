#!/usr/bin/env python3
"""Pomiar fazy mowa->tekst (STT) na liście komend must-have.

Tryby:
    --tts            # szybki baseline: Piper syntezuje komendy, STT je rozpoznaje (bez mikrofonu)
    --record N       # nagraj N komend z mikrofonu (realny test) do runtime/stt_eval/
    --eval           # policz skuteczność na nagraniach z --record

Silnik: Vosk (domyślnie, bez NPU) i/lub NPU Whisper (`--npu`; wymaga wolnego /dev/hailo0).
Metryki: exact (po normalizacji) oraz „do znanej komendy" (core.command_match).

Użycie:
    python3 astro/scripts/stt_eval.py --tts --vosk
    python3 astro/scripts/stt_eval.py --record 25
    python3 astro/scripts/stt_eval.py --eval --npu
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.audio import capture  # noqa: E402
from astro.core import command_match  # noqa: E402

OUT = os.path.join(str(config.REPO), "runtime", "stt_eval")


def _label(i):
    return f"{i:03d}"


def _wait_free(timeout=25, grace=2.0):
    """Czeka, aż NPU będzie wolne (astro.service zwalnia VDevice chwilę po `stop`)."""
    import time
    from astro.backends import npu as npumod
    time.sleep(grace)  # driver potrzebuje chwili po zamknięciu fd przez zatrzymany proces
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not npumod.device_holders():
            return True
        time.sleep(0.5)
    print("[stt-eval] uwaga: NPU nadal zajęte po stopie — pomiar NPU może się nie udać")
    return False


def _service(action):
    """Zatrzymaj/uruchom astro.service, żeby mikrofon/NPU był wolny podczas pomiaru."""
    try:
        subprocess.run(["sudo", "-n", "systemctl", action, "astro.service"],
                       capture_output=True, timeout=30)
        print(f"[stt-eval] astro.service: {action}")
        if action == "stop":
            _wait_free()
    except Exception as exc:
        print(f"[stt-eval] uwaga: nie udało się {action} usługi ({exc})")


def _read_wav_pcm16(path):
    pcm, rate = capture.read_wav(path)
    return pcm, rate


def _vosk_text(pcm):
    from astro.audio.wake import WakeDetector
    return WakeDetector().transcribe(pcm)


def _npu_text(pcm):
    from astro.audio.stt import STT
    return STT().transcribe(pcm)


def _score(got, label):
    g = command_match.normalize(got)
    l = command_match.normalize(label)
    exact = bool(g) and (g == l or l in g or g in l)
    cmd, sc = command_match.best(got)
    return exact, cmd, sc


def tts_pass(engine):
    from astro.audio.tts import TTS
    tts = TTS()
    if not tts.available():
        print("[stt-eval] TTS niedostępny"); return 2
    cmds = command_match.commands()
    tmp = tempfile.mkdtemp(prefix="stt-eval-")
    rows = []
    for i, cmd in enumerate(cmds):
        wav = tts.synthesize(cmd, os.path.join(tmp, f"{_label(i)}.wav"), fx="")
        if not wav:
            rows.append((cmd, "", False, None, 0.0)); continue
        pcm, _ = _read_wav_pcm16(wav)
        got = _npu_text(pcm) if engine == "npu" else _vosk_text(pcm)
        exact, m, sc = _score(got, cmd)
        rows.append((cmd, got, exact, m, sc))
    _report(rows, f"tts/{engine}")
    return 0


def _write_wav(path, pcm, rate):
    import struct
    import wave
    data = (np.clip(np.asarray(pcm, dtype="float32"), -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(data.tobytes())


def _double_beep(tts):
    """Podwójny sygnał startu (dwa krótkie tony 880 Hz z przerwą) — grany przed nagraniem."""
    import subprocess
    rate = int(config.SAMPLE_RATE)
    tone = 0.12
    gap = 0.10
    n = int(rate * tone)
    t = np.arange(n) / rate
    sig = 0.35 * np.sin(2 * np.pi * 880 * t)
    env = np.minimum(1.0, np.minimum(np.arange(n) / (0.01 * rate),
                                     (n - np.arange(n)) / (0.01 * rate)))
    beep = (sig * env).astype("float32")
    silence = np.zeros(int(rate * gap), dtype="float32")
    full = np.concatenate([beep, silence, beep])
    path = os.path.join(OUT, "double_beep.wav")
    _write_wav(path, full, rate)
    try:
        subprocess.run([config.PLAYER, "-D", config.AUDIO_DEVICE, path],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def record(limit=0, speak_prompt=False):
    from astro.audio.tts import TTS
    tts = TTS()
    os.makedirs(OUT, exist_ok=True)
    cmds = command_match.commands()
    if limit:
        cmds = cmds[:limit]
    labels = []
    print(f"[stt-eval] nagrywanie {len(cmds)} komend do {OUT}")
    if speak_prompt:
        print("  ASTRO wypowie komendę → podwójny beep → POWTÓRZ dokładnie to, co usłyszałeś.")
    else:
        print("  Podwójny beep = czytaj DOKŁADNIE tę linię z ekranu (bez pomijania!).")
    for i, cmd in enumerate(cmds):
        if speak_prompt:
            print(f"\n[{i+1}/{len(cmds)}] powtórz: {cmd}")
            if tts.available():
                w = tts.synthesize(cmd, os.path.join(OUT, "prompt.wav"), fx="")
                if w:
                    tts.play(w)
        else:
            ans = input(f"\n[{i+1}/{len(cmds)}] {cmd}\n  <Enter> uzbrój (lub 's' = pomiń)  ")
            if ans.strip().lower() in ("s", "skip", "pom", "pomin", "pomiń"):
                print("  pomijam"); continue
        _double_beep(None)
        pcm = capture.record_speech(max_s=5.0, silence_s=0.8)
        if pcm is None or len(pcm) == 0:
            print("  (nie usłyszałem nic — pomijam)"); continue
        path = os.path.join(OUT, f"{_label(i)}.wav")
        _write_wav(path, pcm, config.SAMPLE_RATE)
        labels.append({"idx": _label(i), "text": cmd, "path": path,
                       "seconds": round(len(pcm) / config.SAMPLE_RATE, 2),
                       "rms": round(capture.rms(pcm), 4)})
        print(f"  OK {len(pcm)/config.SAMPLE_RATE:.2f}s rms={capture.rms(pcm):.3f} -> {path}")
    with open(os.path.join(OUT, "labels.jsonl"), "w", encoding="utf-8") as fh:
        for r in labels:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n[stt-eval] zapisano {len(labels)} nagrań + etykiety: {OUT}/labels.jsonl")
    return 0


def _make_loop(engine):
    """Minimalny `VoiceLoop` (bez agenta/TTS/mikrofonu) do pomiaru `transcribe_ex`."""
    from astro.audio.loop import VoiceLoop
    from astro.audio.stt import STT
    from astro.audio.wake import WakeDetector
    loop = object.__new__(VoiceLoop)
    loop.stt = STT(engine="npu") if engine == "npu" else STT(engine="none")
    loop.wake_det = WakeDetector()
    return loop


def pipeline_saved(engine):
    """Pomiar PEŁNEGO pipeline'u mowy (NPU+Vosk+gramatyka+fuzzy+CPU) na nagraniach."""
    lp = os.path.join(OUT, "labels.jsonl")
    if not os.path.isfile(lp):
        print(f"[stt-eval] brak {lp} (najpierw --record)"); return 2
    loop = _make_loop(engine)
    rows = []
    with open(lp, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            pcm, _ = _read_wav_pcm16(r["path"])
            got, uncertain = loop.transcribe_ex(pcm)
            exact, m, sc = _score(got, r["text"])
            rows.append((r["text"], got, exact, m, sc, uncertain))
    _report_pipeline(rows, f"recorded-pipeline/{engine}")
    return 0


def _report_pipeline(rows, tag):
    n = len(rows) or 1
    exact = sum(1 for r in rows if r[2])
    tocmd = sum(1 for r in rows if r[3])
    unc = sum(1 for r in rows if r[5])
    print(f"\n== STT {tag}: {len(rows)} komend ==")
    print(f"  exact (dosłownie):        {exact}/{len(rows)} ({exact*100//n}%)")
    print(f"  do znanej komendy (fuzzy): {tocmd}/{len(rows)} ({tocmd*100//n}%)")
    print(f"  niepewne (potwierdzenie): {unc}/{len(rows)} ({unc*100//n}%)")
    miss = [r for r in rows if not r[3] and not r[2]]
    for cmd, got, _e, _m, sc, _u in miss[:12]:
        print(f"   BRAK {sc:.2f} | {cmd[:40]!r} -> {got[:40]!r}")
    unc_rows = [r for r in rows if r[5] and r[3]]
    for cmd, got, _e, _m, _sc, _u in unc_rows[:12]:
        print(f"   NIEPEWNE | {cmd[:40]!r} -> {got[:40]!r}")


def eval_saved(engine):
    lp = os.path.join(OUT, "labels.jsonl")
    if not os.path.isfile(lp):
        print(f"[stt-eval] brak {lp} (najpierw --record)"); return 2
    rows = []
    with open(lp, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            pcm, _ = _read_wav_pcm16(r["path"])
            got = _npu_text(pcm) if engine == "npu" else _vosk_text(pcm)
            exact, m, sc = _score(got, r["text"])
            rows.append((r["text"], got, exact, m, sc))
    _report(rows, f"recorded/{engine}")
    return 0


def _report(rows, tag):
    n = len(rows) or 1
    exact = sum(1 for r in rows if r[2])
    tocmd = sum(1 for r in rows if r[3])
    print(f"\n== STT {tag}: {len(rows)} komend ==")
    print(f"  exact (dosłownie):        {exact}/{len(rows)} ({exact*100//n}%)")
    print(f"  do znanej komendy (fuzzy): {tocmd}/{len(rows)} ({tocmd*100//n}%)")
    miss = [r for r in rows if not r[3] and not r[2]]
    for cmd, got, _e, _m, sc in miss[:12]:
        print(f"   BRAK {sc:.2f} | {cmd[:40]!r} -> {got[:40]!r}")


def main():
    ap = argparse.ArgumentParser(description="Pomiar STT na komendach must-have")
    ap.add_argument("--tts", action="store_true", help="baseline przez syntezę TTS")
    ap.add_argument("--record", action="store_true", help="nagraj komendy z mikrofonu (podwójny beep)")
    ap.add_argument("--limit", type=int, default=0, help="ogranicz liczbę komend do nagrania")
    ap.add_argument("--speak-prompt", action="store_true",
                    help="ASTRO wypowiada komendę, Ty powtarzasz (gwarancja zgodności etykiet)")
    ap.add_argument("--eval", action="store_true", help="oceń nagrania z runtime/stt_eval")
    ap.add_argument("--pipeline", action="store_true",
                    help="oceń PEŁNY pipeline mowy (transcribe_ex) na nagraniach")
    ap.add_argument("--npu", action="store_true", help="użyj NPU Whisper (wymaga wolnego NPU)")
    ap.add_argument("--vosk", action="store_true", help="użyj Vosk (domyślne)")
    args = ap.parse_args()
    engine = "npu" if args.npu else "vosk"
    if args.pipeline:
        if engine == "npu":
            _service("stop")
            try:
                return pipeline_saved(engine)
            finally:
                _service("start")
        return pipeline_saved(engine)
    if args.record:
        _service("stop")
        try:
            return record(args.limit, speak_prompt=args.speak_prompt)
        finally:
            _service("start")
    if args.eval:
        if engine == "npu":
            _service("stop")
            try:
                return eval_saved(engine)
            finally:
                _service("start")
        return eval_saved(engine)
    return tts_pass(engine)


if __name__ == "__main__":
    sys.exit(main())
