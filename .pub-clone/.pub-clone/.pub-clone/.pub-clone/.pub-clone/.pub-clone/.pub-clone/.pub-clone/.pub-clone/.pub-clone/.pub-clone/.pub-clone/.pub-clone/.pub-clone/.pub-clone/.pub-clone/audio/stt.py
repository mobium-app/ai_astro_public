"""STT dla ASTRO: NPU Whisper (Hailo) z korektą typowych zniekształceń PL."""

import re

import numpy as np

from .. import config
from ..backends.npu import NPU_ENGINE

ASR_HALLUCINATIONS = {"ga", "gad", "eli", "ely", "o", "e", "y", "mm", "hmm", "yyy"}

ASR_FIXES = {
    "gocina": "godzina", "goczina": "godzina", "godzine": "godzinę",
    "ktura": "która", "ktora": "która", "kture": "które", "ktory": "który",
    "pamienci": "pamięci", "pamienc": "pamięć",
    "ktoragojinna": "która godzina", "ktoragodzina": "która godzina",
    "ktoregogojinna": "która godzina", "ktorajestgodzina": "która jest godzina",
    # Komendy zasilania/sieci (Whisper-Base gubi nosowość i końcówki: „Restaart", „wylancz").
    "restaart": "restart", "restarcie": "restarcie", "restart": "restart",
    "wylancz": "wyłącz", "wlancz": "włącz", "wylanczyc": "wyłączyć",
    "polancz": "połącz", "podlancz": "podłącz", "zasobl": "zasoby",
    # Głośność: Whisper-Base gubi „l" („gośność") albo zamienia „ś" na „sz" („gorszność").
    "gośność": "głośność", "gośności": "głośności", "gośnością": "głośnością",
    "gosnosc": "głośność", "gosnosci": "głośności",
    "gorszność": "głośność", "gorszności": "głośności", "gorsznością": "głośnością",
    "gorszosc": "głośność", "gorszosci": "głośności",
    "głosność": "głośność", "głosności": "głośności",
    # Potwierdzenia (Whisper gubi „d": „Potwierzam", „Zatwirdzam").
    "potwierzam": "potwierdzam", "potwirdzam": "potwierdzam", "potfierdzam": "potwierdzam",
    "potwierdzan": "potwierdzam", "zatwierzam": "zatwierdzam", "zatwirdzam": "zatwierdzam",
}

# Dopasowanie po rdzeniu: Whisper-Base PL myli końcówki/łagodzi spółgłoski.
ASR_STEMS = (
    ("gocina", "godzina"), ("goczyn", "godzina"), ("godzin", "godzina"),
    ("któr", "która"), ("ktur", "która"), ("kstr", "która"),
    ("temperat", "temperatura"), ("dysk", "dysk"), ("pamię", "pamięć"),
    ("pamien", "pamięć"), ("pogod", "pogoda"),
    # „gośność"/„gorszność"/„głosność" (każda odmiana) -> „głośność".
    ("gośno", "głośność"), ("gosno", "głośność"), ("gorszno", "głośność"),
    ("gorszos", "głośność"), ("głosno", "głośność"),
    # Potwierdzenia z zgubionym/przekręconym „d" (każda końcówka).
    ("potwierz", "potwierdzam"), ("potwirdz", "potwierdzam"),
    ("potfierdz", "potwierdzam"), ("zatwierz", "zatwierdzam"),
)


def fix_asr(text):
    """Poprawia najczęstsze błędy Whisper-Base PL (np. „gocina"/„kstrangocina" -> „godzina")."""
    if not text:
        return text
    # „IP" dyktowane literami: „i p"/„i b"/„i pe"/„i pa" -> „ip"; urwane „podaj i" -> „podaj ip".
    text = re.sub(r"\bi\s+([bp])(?:e|a)?\b", "ip", text, flags=re.I)
    text = re.sub(r"\bpodaj\s+i\s*$", "podaj ip", text, flags=re.I)

    def repl(m):
        w = m.group(0)
        low = w.lower()
        if low in ASR_FIXES:
            fix = ASR_FIXES[low]
        else:
            fix = None
            for stem, rep in ASR_STEMS:
                # Dopasowanie PREFIKSU słowa (nie dowolnej podciąg): „dysk" łapie „dysku",
                # ale nie „dyskusja"; mniej fałszywych korekt zwykłego tekstu rozmowy.
                if low.startswith(stem):
                    fix = rep
                    break
        if not fix:
            return w
        return fix[:1].upper() + fix[1:] if w[:1].isupper() else fix

    return re.sub(r"\w+", repl, text)


class STT:
    def __init__(self, engine=None, language="pl", npu=None):
        self.engine = (engine or config.STT_ENGINE or "npu").lower()
        self.language = language
        self.npu = npu or NPU_ENGINE

    def available(self):
        if self.engine == "npu":
            return self.npu.whisper_ready()
        return False

    def transcribe(self, pcm_f32):
        """pcm: numpy float32 mono 16 kHz [-1,1]. Zwraca tekst ('' gdy brak silnika/sygnału)."""
        if self.engine != "npu":
            return ""
        if not self.npu.whisper_ready():
            return ""
        audio = np.asarray(pcm_f32, dtype="float32").reshape(-1)
        if audio.size == 0:
            return ""
        # Odrzuć sygnał stały/ton (Whisper halucynuje na DC/tonie; VAD pilnuje tego tylko w nasłuchu).
        if float(np.std(audio)) < 1e-3:
            return ""
        # Normalizacja głośności (M3.6) PRZED bramką ciszy: cicha mowa bywa źle rozpoznawana,
        # a wcześniej rms<0.01 ucinał ją, zanim zadziałało skalowanie szczytu.
        if getattr(config, "STT_NORMALIZE", True):
            peak = float(np.max(np.abs(audio)))
            if 0.0 < peak < 0.95:
                audio = audio * (0.95 / peak)
        if float(np.sqrt(np.mean(audio ** 2))) < 0.01:
            return ""
        text = fix_asr(self.npu.transcribe(audio, language=self.language))
        norm = (text or "").strip().lower().strip(" .,!?")
        if len(norm) < 3 or norm in ASR_HALLUCINATIONS:
            return ""
        return text
