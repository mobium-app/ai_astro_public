"""TTS ASTRO: Piper + robotyczna barwa z pogłosem (efekty sox).

Głos bazowy: żeński PL (`pl_PL-gosia-medium`); profil podnosi ton, dodaje chór/tremolo
(robotyzacja) oraz echo i reverb (robotyczny pogłos). To oryginalny profil brzmieniowy,
nie kopia konkretnej postaci/aktora. Konfiguracja: ASTRO_TTS_ENGINE, ASTRO_PIPER, ASTRO_TTS_MODEL,
ASTRO_TTS_FX (łańcuch efektów sox). Uwaga: tego sox nie ma `vibrato` — używać chorus/tremolo.
"""

import os
import shutil
import subprocess
import tempfile

from .. import config
from . import voice_style
from .text import prepare_speech

# Stały katalog roboczy TTS (nadpisujemy jeden plik) — mkdtemp per wypowiedź zostawiał katalogi.
_SCRATCH = os.path.join(tempfile.gettempdir(), "astro-tts")


def _scratch_wav():
    os.makedirs(_SCRATCH, exist_ok=True)
    return os.path.join(_SCRATCH, "astro-tts.wav")


class TTS:
    def __init__(self, engine=None, piper=None, model=None, fx=None, player=None,
                 device=None):
        self.engine = (engine or config.TTS_ENGINE or "piper").lower()
        self.piper = piper or config.PIPER
        self.model = model or config.TTS_MODEL
        # Domyślny fx = profil głosu (bazowy ton + TTS_FX), NIE goły config.TTS_FX.
        # Dzięki temu każdy tor mowy (także streaming/zapowiedź bez fx) mówi TĄ SAMĄ barwą;
        # jawne fx="" (np. pomiar STT) nadal wyłącza efekty.
        if fx is None:
            try:
                self.fx = voice_style.fx_for(None)
            except Exception:
                self.fx = config.TTS_FX
        else:
            self.fx = fx
        self.player = player or config.PLAYER
        self.device = device or config.AUDIO_DEVICE
        self._proc = None

    def available(self):
        if self.engine == "none":
            return False
        if self.engine == "piper":
            return os.path.isfile(self.piper) and os.path.isfile(self.model)
        return bool(shutil.which(self.engine))

    def synth_cmd(self, out_wav, model=None):
        if self.engine == "piper":
            return [self.piper, "--model", model or self.model, "--output_file", out_wav]
        return [self.engine, "-v", "pl+f3", "-p", "80", "-s", "150", "-w", out_wav]

    def fx_argv(self, in_wav, out_wav, fx=None):
        tokens = ((self.fx if fx is None else fx) or "").split()
        if not tokens or not shutil.which("sox"):
            return None
        return ["sox", in_wav, out_wav] + tokens

    def play_cmd(self, wav):
        return [self.player, "-D", self.device, wav]

    def synthesize(self, text, out_wav, fx=None, model=None):
        # Kosmetyka mowy (jak w Atenie): markdown -> rodzaj żeński -> wymowa liczb/symboli/dat.
        text = prepare_speech(text)
        text = (text or "").strip()
        if not text or not self.available():
            return None
        raw = out_wav + ".raw.wav"
        try:
            proc = subprocess.run(self.synth_cmd(raw, model), input=text.encode("utf-8"),
                                  capture_output=True, timeout=60)
        except Exception:
            return None
        if proc.returncode != 0 or not os.path.isfile(raw):
            return None
        fx_argv = self.fx_argv(raw, out_wav, fx)
        if not fx_argv:
            os.replace(raw, out_wav)
            return out_wav
        try:
            r = subprocess.run(fx_argv, capture_output=True, timeout=60)
        except Exception:
            r = None
        if r is None or r.returncode != 0 or not os.path.isfile(out_wav):
            os.replace(raw, out_wav)
        else:
            try:
                os.remove(raw)
            except OSError:
                pass
        return out_wav

    def play(self, wav):
        if not wav or not os.path.isfile(wav):
            return False
        try:
            self._proc = subprocess.Popen(self.play_cmd(wav), stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
        except Exception:
            self._proc = None
            return False
        try:
            rc = self._proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.stop()
            rc = -1
        finally:
            self._proc = None
        return rc == 0

    def stop(self):
        """Przerywa bieżące odtwarzanie (barge-in). True, gdy coś przerwano."""
        p = self._proc
        if p is None or p.poll() is not None:
            return False
        try:
            p.terminate()
        except Exception:
            try:
                p.kill()
            except Exception:
                return False
        return True

    def speak(self, text, out_wav=None, fx=None, model=None):
        """Syntezuje i odtwarza tekst. Zwraca ścieżkę WAV albo None."""
        out_wav = out_wav or _scratch_wav()
        wav = self.synthesize(text, out_wav, fx=fx, model=model)
        if not wav:
            return None
        self.play(wav)
        return wav
