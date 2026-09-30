#!/usr/bin/env python3
"""Samo-test AUDIO na żywo (B6): mikrofon -> STT (NPU) oraz TTS -> głośnik.

Wymaga mikrofonu/głośnika (WM8960) i — najlepiej — ZATRZYMANEJ usługi `astro.service`
(urządzenie jest pół-dupleks; działająca usługa trzyma kartę). Skrypt nic nie zmienia
w systemie poza odtworzeniem podanej frazy.

Przykłady:
    python3 astro/scripts/audio_selftest.py --seconds 5
    python3 astro/scripts/audio_selftest.py --speak "Uruchamiam tryb offline." --voice clean
    python3 astro/scripts/audio_selftest.py --speak "Melduję się." --voice robocik
    sudo systemctl stop astro.service && python3 astro/scripts/audio_selftest.py --allow-busy
Użycie: patrz `--help`.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402


def service_active():
    try:
        out = subprocess.run(["systemctl", "is-active", "astro.service"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() == "active"
    except Exception:
        return False


def card_present():
    try:
        with open("/proc/asound/cards", encoding="utf-8") as fh:
            return "wm8960" in fh.read()
    except OSError:
        return False


def do_record(seconds):
    from astro.audio import capture
    pcm = capture.record_speech(max_s=seconds)
    rms = float(capture.rms(pcm)) if pcm is not None else 0.0
    print(f"[audio] nagrano {0 if pcm is None else pcm.size} próbek, RMS={rms:.4f}")
    return pcm


def do_stt(pcm):
    if pcm is None or pcm.size == 0:
        print("[audio] brak nagrania — pomijam STT")
        return
    from astro.audio.stt import STT
    stt = STT()
    text = stt.transcribe(pcm)
    print(f"[audio] STT: {text!r}")


def do_tts(text, voice=None):
    from astro.audio import voice_style
    if voice:
        voice_style.set_profile(voice)
        print(f"[audio] profil głosu: {voice}")
    from astro.audio.tts import TTS
    tts = TTS()
    if not tts.available():
        print("[audio] TTS niedostępny (brak Piper/modelu)")
        return
    ok = tts.speak(text)
    print(f"[audio] TTS zagrane: {bool(ok)}  ({text!r})")


def main():
    ap = argparse.ArgumentParser(description="Samo-test audio ASTRO (mikrofon/STT + TTS)")
    ap.add_argument("--seconds", type=float, default=5.0, help="maks. długość nagrania")
    ap.add_argument("--speak", default="", help="fraza do wypowiedzenia przez TTS")
    ap.add_argument("--voice", choices=("clean", "robocik", ""), default="",
                    help="profil głosu dla TTS")
    ap.add_argument("--no-stt", action="store_true", help="pomiń rozpoznawanie mowy")
    ap.add_argument("--no-tts", action="store_true", help="pomiń syntezę mowy")
    ap.add_argument("--record", action="store_true", help="nagraj i rozpoznaj (domyślnie: tak)")
    ap.add_argument("--allow-busy", action="store_true",
                    help="nie ostrzegaj o działającej usłudze (karta może być zajęta)")
    args = ap.parse_args()

    print(f"[audio] urządzenie: {config.AUDIO_DEVICE} | karta wm8960: {card_present()}")
    if not card_present():
        print("[audio] BRAK karty wm8960 — wymaga ZIMNEGO STARTU (power cycle), patrz NEXT_SESSION.")
        return 2
    if service_active() and not args.allow_busy:
        print("[audio] UWAGA: astro.service działa i trzyma mikrofon/głośnik. "
              "Zatrzymaj: sudo systemctl stop astro.service (albo użyj --allow-busy).")
        return 2

    if args.speak and not args.no_tts:
        do_tts(args.speak, args.voice or None)

    if not args.no_stt:
        pcm = do_record(args.seconds)
        do_stt(pcm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
