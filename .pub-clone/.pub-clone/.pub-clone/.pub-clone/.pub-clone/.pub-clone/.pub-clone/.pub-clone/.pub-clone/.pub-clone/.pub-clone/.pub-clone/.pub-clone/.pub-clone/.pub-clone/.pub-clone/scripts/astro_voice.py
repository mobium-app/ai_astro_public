#!/usr/bin/env python3
"""Uruchamia pętlę głosową ASTRO (nasłuch -> wake „Hej Astro" -> agent -> głos).

UWAGA: live wymaga wolnego mikrofonu i NPU. Jeśli działa inny asystent (inny proces na
`/dev/hailo0` lub mikrofonie), najpierw go zatrzymaj — inaczej urządzenia są zajęte.
"""

import argparse
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import backends as B  # noqa: E402
from astro import config, core, remote_support  # noqa: E402
from astro.audio import VoiceLoop, capture, signals, whisper_cpu  # noqa: E402
from astro.audio.wake import is_wake, strip_wake  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=None)
    parser.add_argument("--listen", type=float, default=None)
    parser.add_argument("--wav", default=None,
                        help="tryb testowy: przetwórz plik WAV 16k (bez mikrofonu)")
    args = parser.parse_args()

    loop = VoiceLoop(listen_s=args.listen)

    # Wstępne ładowanie dokładnego ASR CPU (faster-whisper) w tle — pierwsza niepewna
    # komenda nie czeka wtedy ~10-30 s na wczytanie modelu (jakość komend: ~97%).
    if whisper_cpu.preload():
        print("[voice] preload faster-whisper (CPU fallback) w tle", flush=True)

    # Rozgrzej silniki STT (NPU Whisper + model Vosk) w tle: pierwsze polecenie po starcie
    # nie płaci za wczytanie HEF/gramatyki (odczuwalne opóźnienie „pierwszej tury").
    def _warm_stt():
        try:
            if loop.stt.available():
                loop.stt.npu.warm()
                print("[voice] warm NPU Whisper gotowy", flush=True)
        except Exception:
            pass
        try:
            if loop.wake_det.available() and hasattr(loop.wake_det, "warm"):
                loop.wake_det.warm()
                print("[voice] warm Vosk gotowy", flush=True)
        except Exception:
            pass

    threading.Thread(target=_warm_stt, name="astro-warm-stt", daemon=True).start()

    # Kontekst trwały (P4): odśwież dzienne digesty i archiwum `.md` w tle (nie blokuje startu).
    def _warm_context():
        try:
            from astro.core import persistent_context
            res = persistent_context.warm_start(getattr(loop.agent, "memory", None))
            if res:
                print(f"[voice] kontekst: digesty={res.get('digests', 0)} "
                      f"archiwum={res.get('files', 0)} .md", flush=True)
        except Exception:
            pass

    if config.CONTEXT_ENABLED:
        threading.Thread(target=_warm_context, name="astro-warm-context", daemon=True).start()

    # Rozgrzej nauczyciela na PC-Kali (pierwszy w łańcuchu zdalnym) i trzymaj go w RAM —
    # inaczej pierwsze pytanie po przerwie czeka na zimny start modelu 11B.
    if config.PC_WARM and config.PC_URL:
        threading.Thread(target=remote_support.warm_pc, daemon=True).start()
        print("[voice] warm PC-Kali (Ollama keep_alive) w tle", flush=True)

    if args.wav:
        pcm, rate = capture.read_wav(args.wav)
        print(f"[voice] wav={args.wav} rate={rate} rms={capture.rms(pcm):.4f}")
        print(f"[voice] wake detect: {loop.wake_det.detect(pcm)}")
        inline = strip_wake(loop.stt.transcribe(pcm))
        print(f"[voice] NPU Whisper: {inline!r}")
        vosk = loop.wake_det.transcribe(pcm)
        print(f"[voice] Vosk full: {vosk!r}")
        command = inline if len(inline.split()) >= 2 else (strip_wake(vosk) if is_wake(vosk) else "")
        if command:
            reply = core.dispatch(command, loop.agent).reply
            print(f"[voice] polecenie: {command!r} -> {reply!r}")
        else:
            print("[voice] brak polecenia")
        return 0

    if B.device_busy():
        holders = ", ".join(f"{h['comm']}({h['pid']})" for h in B.device_holders())
        node = (B.device_paths() or ["/dev/hailo0"])[0]
        print(f"[voice] UWAGA: {node} zajęte przez {holders} — STT NPU może nie działać.")
    try:
        loop.say("Cześć! W czym mogę ci pomóc?")
        signals.done_signal()
        print("[voice] nasłuchuję... (powiedz „Astro ...”)")
        loop.run_forever(max_turns=args.turns)
    except RuntimeError as e:
        print(f"[voice] {e}")
        return 1
    except KeyboardInterrupt:
        print("\n[voice] stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
