"""Przechwytywanie audio (arecord) i odczyt WAV bez zewnętrznych bibliotek."""

import subprocess
import wave
from collections import deque

import numpy as np

from .. import config


def read_wav(path):
    """WAV -> numpy float32 mono [-1,1] (konwersja z int16)."""
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        width = w.getsampwidth()
        channels = w.getnchannels()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"oczekiwano 16-bit WAV, jest {width * 8}-bit")
    data = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def rms(pcm):
    arr = np.asarray(pcm, dtype="float32")
    return float(np.sqrt(np.mean(arr ** 2))) if arr.size else 0.0


def stream_pcm(device=None, rate=None, chunk_ms=250):
    """Ciągły strumień audio z arecord (raw S16_LE mono) jako generatory float32."""
    device = device or config.AUDIO_DEVICE
    rate = int(rate or config.SAMPLE_RATE)
    cmd = [config.RECORDER, "-D", device, "-f", "S16_LE", "-r", str(rate), "-c", "1",
           "-t", "raw", "-q", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    bytes_per = max(2, rate * chunk_ms // 1000 * 2)
    try:
        while True:
            data = proc.stdout.read(bytes_per)
            if not data:
                break
            if len(data) < 2:
                continue
            yield np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _frame_level(arr):
    """Poziom RMS składowej zmiennej (bez DC) — wm8960 ma dryf DC po otwarciu arecord."""
    if arr.size == 0:
        return 0.0
    ac = arr - float(np.mean(arr))
    return float(np.sqrt(np.mean(ac ** 2)))


def level(pcm):
    """Publiczny poziom RMS bez DC (do barge-in) — odporny na dryf DC karty."""
    return _frame_level(np.asarray(pcm, dtype="float32").reshape(-1))


def speech_from_chunks(chunks, rate=None, max_s=10.0, silence_s=0.8,
                       min_speech_s=0.3, threshold=0.02, pre_roll_s=0.25, warmup_s=0.4):
    """Zbiera mowę z ciągłego strumienia: start po przekroczeniu progu, koniec po ciszy.

    Zwraca float32 mono (mowa wraz z krótkim wyprzedzeniem i ogonem ciszy), albo
    pustą tablicę, gdy nie wykryto mowy. To deterministyczny VAD progowy RMS —
    pozwala zakończyć nasłuch zaraz po tym, jak użytkownik przestanie mówić,
    zamiast czekać pełne okno (VOICE_LISTEN_S/VOICE_SESSION_S).

    `warmup_s` pomija początkowy trzask/dryf DC karty (wm8960) tuż po otwarciu
    arecord, żeby nie wystartował fałszywie na samym otwarciu urządzenia.
    """
    rate = int(rate or config.SAMPLE_RATE)
    max_s = float(max_s)
    silence_s = float(silence_s)
    min_speech_s = float(min_speech_s)
    threshold = float(threshold)
    warmup_s = float(warmup_s)
    pre_roll_samples = max(0, int(pre_roll_s * rate))

    pre = deque()
    pre_len = 0
    collected = []
    elapsed = 0.0
    voiced_s = 0.0
    silence_run = 0.0
    started = False
    noise_levels = []      # poziomy z rozgrzewki -> estymata szumu tła (wm8960 ~0.013 RMS)
    effective = float(threshold)

    for chunk in chunks:
        arr = np.asarray(chunk, dtype="float32").reshape(-1)
        if arr.size == 0:
            continue
        dt = arr.size / rate
        elapsed += dt

        if elapsed <= warmup_s:
            pre.append(arr)
            pre_len += arr.size
            while pre_len > pre_roll_samples and pre:
                pre_len -= pre.popleft().size
            # Szum szacujemy TYLKO z klatek poniżej progu — inaczej cicha mowa użytkownika
            # w rozgrzewce podnosiła próg i cała wypowiedź była odrzucana (min(noise)*2.2).
            lvl = _frame_level(arr)
            if lvl < threshold:
                noise_levels.append(lvl)
            continue

        if noise_levels:
            # Min (nie średnia) odporny na trzask/DC przy otwarciu karty; ograniczamy pułapem,
            # żeby zbyt głośne tło nie uczyniło nas głuchymi. Efekt: VAD nie startuje na szumie.
            noise = min(noise_levels)
            effective = max(float(threshold), min(noise * 2.2, 0.06))
            noise_levels = []

        level = _frame_level(arr)

        if not started:
            if level >= effective:
                started = True
                collected.extend(pre)
                collected.append(arr)
                voiced_s = dt
                silence_run = 0.0
            else:
                pre.append(arr)
                pre_len += arr.size
                while pre_len > pre_roll_samples and pre:
                    pre_len -= pre.popleft().size
            if elapsed >= max_s:
                break
            continue

        collected.append(arr)
        if level < effective:
            silence_run += dt
            if silence_run >= silence_s and voiced_s >= min_speech_s:
                break
        else:
            silence_run = 0.0
            voiced_s += dt
        if elapsed >= max_s:
            break

    if not started or voiced_s < min_speech_s or not collected:
        return np.zeros(0, dtype="float32")
    return np.concatenate(collected)


def record_speech(device=None, rate=None, max_s=None, silence_s=None,
                  min_speech_s=None, threshold=None, pre_roll_s=0.25, warmup_s=None):
    """Nagrywa jedną wypowiedź z mikrofonu (VAD). Zwraca float32 mono lub pustą tablicę."""
    device = device or config.AUDIO_DEVICE
    rate = int(rate or config.SAMPLE_RATE)
    max_s = float(max_s if max_s is not None else config.VOICE_LISTEN_S)
    silence_s = float(silence_s if silence_s is not None else config.VOICE_VAD_SILENCE_S)
    min_speech_s = float(min_speech_s if min_speech_s is not None else config.VOICE_VAD_MIN_SPEECH_S)
    threshold = float(threshold if threshold is not None else config.VOICE_VAD_THRESHOLD)
    warmup_s = float(warmup_s if warmup_s is not None else config.VOICE_VAD_WARMUP_S)
    # Pre-roll ≥ rozgrzewka: mowa zaczęta tuż po beepie (w oknie warmup) nie gubi pierwszej sylaby.
    pre_roll_s = max(float(pre_roll_s), warmup_s)
    try:
        gen = stream_pcm(device=device, rate=rate)
    except Exception:
        return np.zeros(0, dtype="float32")
    try:
        return speech_from_chunks(gen, rate=rate, max_s=max_s, silence_s=silence_s,
                                  min_speech_s=min_speech_s, threshold=threshold,
                                  pre_roll_s=pre_roll_s, warmup_s=warmup_s)
    except Exception:
        return np.zeros(0, dtype="float32")
    finally:
        try:
            gen.close()
        except Exception:
            pass


class PersistentMic:
    """Trwale otwarty arecord (jeden proces) — usuwa narzut otwarcia karty i warmup per-turę.

    Uwaga (M: wydajność UX): `stream_pcm` otwiera `arecord` i przy KAŻDEJ turze trzeba odczekać
    `warmup_s` na ustabilizowanie DC karty (wm8960). Ten obiekt otwiera strumień raz i współdzieli
    go między detekcją wake a nagraniem poleceń; rozgrzewkę odrzucamy tylko raz. Wymaga weryfikacji
    live (`ASTRO_MIC_PERSISTENT=1`); przy włączonym barge-in NIE używać (osobny strumień na mikrofon).
    """

    def __init__(self, device=None, rate=None, chunk_ms=250):
        self.device = device or config.AUDIO_DEVICE
        self.rate = int(rate or config.SAMPLE_RATE)
        self._gen = stream_pcm(device=self.device, rate=self.rate, chunk_ms=chunk_ms)
        self._primed = False

    def _prime(self, warmup_s):
        if self._primed:
            return
        target = int(max(0.0, float(warmup_s or 0.0)) * self.rate)
        got = 0
        for chunk in self._gen:
            got += chunk.size
            if got >= target:
                break
        self._primed = True

    def chunks(self):
        """Ciągły strumień klatek (po jednorazowej rozgrzewce) dla detekcji wake."""
        self._prime(config.VOICE_VAD_WARMUP_S)
        return self._gen

    def record(self, max_s=None, silence_s=None, min_speech_s=None, threshold=None,
               pre_roll_s=0.25, warmup_s=0.0):
        """Nagrywa wypowiedź z już otwartego strumienia (bez ponownego otwarcia karty)."""
        self._prime(config.VOICE_VAD_WARMUP_S)
        return speech_from_chunks(
            self._gen, rate=self.rate,
            max_s=float(max_s if max_s is not None else config.VOICE_LISTEN_S),
            silence_s=float(silence_s if silence_s is not None else config.VOICE_VAD_SILENCE_S),
            min_speech_s=float(min_speech_s if min_speech_s is not None
                               else config.VOICE_VAD_MIN_SPEECH_S),
            threshold=float(threshold if threshold is not None else config.VOICE_VAD_THRESHOLD),
            pre_roll_s=float(pre_roll_s), warmup_s=float(warmup_s))

    def close(self):
        try:
            self._gen.close()
        except Exception:
            pass

