"""Sygnały dźwiękowe ASTRO (jak w Atenie): wake = dzwonek 880->1320 Hz, done = 587 Hz."""

import os
import subprocess
import tempfile
import wave

import numpy as np

from .. import config

TTS_RATE = 22050
# Stały katalog roboczy na sygnały (nadpisujemy jeden plik) — wcześniej mkdtemp per beep
# zostawiał katalog w /tmp po każdej turze (done_signal gra po każdej odpowiedzi).
_SCRATCH = os.path.join(tempfile.gettempdir(), "astro-signals")


def _scratch_path(name):
    os.makedirs(_SCRATCH, exist_ok=True)
    return os.path.join(_SCRATCH, name)


def wake_pcm(rate=TTS_RATE):
    """Dzwonek: 880 Hz (0,10 s) + 0,05 s ciszy + 1320 Hz (0,10 s)."""
    t = np.arange(int(rate * 0.10))
    seg1 = 0.35 * np.sin(2 * np.pi * 880 * t / rate)
    gap = np.zeros(int(rate * 0.05), dtype=np.float32)
    seg2 = 0.35 * np.sin(2 * np.pi * 1320 * t / rate)
    return np.concatenate([seg1, gap, seg2]).astype("float32")


def done_pcm(rate=TTS_RATE):
    """Krótki, niski ton 587 Hz (0,12 s) - „możesz mówić dalej"."""
    t = np.arange(int(rate * 0.12))
    return (0.3 * np.sin(2 * np.pi * 587 * t / rate)).astype("float32")


def tick_pcm(rate=TTS_RATE):
    """Krótki „tick" (~70 ms, 1200 Hz) — potwierdzenie każdej przyjętej literki hasła."""
    t = np.arange(int(rate * 0.07))
    env = np.linspace(1.0, 0.0, t.size)
    return (0.22 * env * np.sin(2 * np.pi * 1200 * t / rate)).astype("float32")


def play_pcm(pcm, rate=TTS_RATE):
    pcm16 = (np.clip(np.asarray(pcm, dtype="float32"), -1.0, 1.0) * 32767).astype("<i2")
    path = _scratch_path("astro-signal.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16.tobytes())
    try:
        subprocess.run([config.PLAYER, "-q", "-D", config.AUDIO_DEVICE,
                        "-f", "S16_LE", "-r", str(rate), "-c", "1", path],
                       capture_output=True, timeout=10)
    except Exception:
        return None
    return path


def wake_signal(rate=TTS_RATE):
    return play_pcm(wake_pcm(rate), rate)


def done_signal(rate=TTS_RATE):
    return play_pcm(done_pcm(rate), rate)


def tick_signal(rate=TTS_RATE):
    return play_pcm(tick_pcm(rate), rate)
