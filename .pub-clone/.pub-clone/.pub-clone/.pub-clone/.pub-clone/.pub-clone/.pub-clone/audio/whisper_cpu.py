"""Dokładny ASR na CPU (faster-whisper) — fallback dla NIEPEWNYCH krótkich komend.

Pomiar na realnych nagraniach (2026-09-23, Pi 5): Whisper-small int8 rozpoznaje krótkie
komendy znacznie lepiej niż nasze pozostałe silniki („do znanej komendy" 95% vs Vosk 82%,
NPU Whisper-Base 68%), ale jest ~7 s/komendę. Dlatego używamy go tylko wtedy, gdy szybkie
silniki (NPU/Vosk) nie dały pewnego dopasowania do listy must-have.

Leniwy import + leniwe ładowanie modelu: gdy brak `faster_whisper`, moduł jest „niedostępny"
i nic nie psuje (offline-first, zasada jakości przed tempem).
"""

import threading

from .. import config

_lock = threading.Lock()
_model = None
_preload_started = False


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def loaded():
    """True, gdy model jest już w pamięci (preload zakończony)."""
    return _model is not None


def preload():
    """Ładuje model w tle, by pierwsza niepewna komenda nie czekała ~10-30 s.

    Bezpieczne do wielokrotnego wołania; nic nie robi, gdy fallback wyłączony lub brak
    `faster_whisper`. Zwraca True, gdy uruchomiono ładowanie w tym wywołaniu."""
    global _preload_started
    if _preload_started:
        return False
    if not getattr(config, "STT_WHISPER_ENABLED", True) or not available():
        return False
    _preload_started = True

    def _work():
        try:
            _get()
        except Exception:
            pass

    threading.Thread(target=_work, name="astro-whisper-preload", daemon=True).start()
    return True


def _get():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(
                getattr(config, "STT_WHISPER_MODEL", "small"),
                device="cpu", compute_type="int8",
                cpu_threads=int(getattr(config, "STT_WHISPER_THREADS", 4)))
        return _model


def transcribe(pcm):
    """pcm float32 mono 16 kHz -> tekst ('' gdy niedostępne/błąd)."""
    if not getattr(config, "STT_WHISPER_ENABLED", True) or not available():
        return ""
    try:
        import numpy as np
        audio = np.asarray(pcm, dtype="float32").reshape(-1)
        # Sygnał stały/ton (brak zmienności) potrafi wpaść w pętlę generowania Whispera —
        # pomijamy; dla mowy warunek nigdy nie zachodzi (wariancja > 0).
        if audio.size == 0 or float(np.std(audio)) < 1e-3:
            return ""
        segments, _info = _get().transcribe(audio, language="pl", beam_size=1)
        return "".join(s.text for s in segments).strip()
    except Exception:
        return ""
