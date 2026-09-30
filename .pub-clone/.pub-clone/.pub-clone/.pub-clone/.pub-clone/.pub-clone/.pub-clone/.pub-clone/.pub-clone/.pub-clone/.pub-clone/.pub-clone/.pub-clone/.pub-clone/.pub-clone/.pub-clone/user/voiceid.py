"""Identyfikacja mówcy (D1): rozpoznawanie użytkownika po głosie.

Szkielet: z audio wyznaczamy wektor cech mówcy (wstrzykiwany `embedder`; domyślnie Vosk
`vosk-model-spk-0.4`, jeśli dostępny), zapisujemy profile w `runtime/voiceid.json` i rozpoznajemy
po podobieństwie kosinusowym do centroidu. Poniżej progu = „nieznany" (nie zgadujemy).

To warstwa bezpieczeństwa/UX (personalizacja, „to Ty?"), nie biometria krytyczna. Prywatność:
wektory i audio zostają lokalnie; brak wysyłki do chmury.
"""

import json
import math
import os

from .. import config

VOICEID_FILE = os.path.join(str(config.RUNTIME_DIR), "voiceid.json")
DEFAULT_THRESHOLD = 0.82


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def load_profiles(path=None):
    try:
        with open(path or VOICEID_FILE, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def save_profiles(profiles, path=None):
    try:
        os.makedirs(os.path.dirname(path or VOICEID_FILE), exist_ok=True)
        with open(path or VOICEID_FILE, "w", encoding="utf-8") as fh:
            json.dump(profiles, fh)
    except OSError:
        pass


def vosk_embedder(model_path=None):
    """Zwraca funkcję audio->wektor (Vosk spk) albo None, gdy brak modelu.

    Użycie: `v = vosk_embedder(); vec = v(audio_f32)`.
    """
    path = model_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models", "vosk", "vosk-model-spk-0.4")
    if not os.path.isdir(path):
        return None

    def embed(audio_f32):
        import numpy as np
        from vosk import KaldiRecognizer, Model, SpkModel
        model = Model(os.path.dirname(path))  # model ASR obok; tu tylko do recognizera
        spk = SpkModel(path)
        rec = KaldiRecognizer(model, 16000, spk)
        pcm = (np.clip(np.asarray(audio_f32, dtype="float32"), -1, 1) * 32767).astype("int16")
        rec.AcceptWaveform(pcm.tobytes())
        rec.FinalResult()
        xvec = rec.FinalResult()  # spk vector pobierany przez właściwość w nowszych API
        return None if xvec is None else list(np.asarray(xvec, dtype="float32"))

    return embed


class VoiceID:
    def __init__(self, embedder=None, path=None, threshold=None):
        self.embedder = embedder
        self.path = path or VOICEID_FILE
        self.threshold = DEFAULT_THRESHOLD if threshold is None else float(threshold)
        self.profiles = load_profiles(self.path)

    def _save(self):
        save_profiles(self.profiles, self.path)

    def enroll(self, name, vector):
        """Dodaje próbkę mówcy (aktualizuje centroid jako średnią kroczącą)."""
        name = (name or "").strip()
        if not name or not vector:
            return False
        vec = [float(x) for x in vector]
        prof = self.profiles.get(name) or {"count": 0, "centroid": []}
        n = int(prof.get("count", 0))
        c = prof.get("centroid") or []
        if len(c) != len(vec):
            c = [0.0] * len(vec)
            n = 0
        prof["centroid"] = [(ci * n + vi) / (n + 1) for ci, vi in zip(c, vec)]
        prof["count"] = n + 1
        self.profiles[name] = prof
        self._save()
        return True

    def identify(self, vector):
        """Zwraca (imię, wynik) albo ('', 0.0) poniżej progu/brak profili."""
        if not vector:
            return "", 0.0
        best_name, best_score = "", 0.0
        for name, prof in self.profiles.items():
            score = _cosine(vector, prof.get("centroid") or [])
            if score > best_score:
                best_name, best_score = name, score
        return (best_name, round(best_score, 3)) if best_score >= self.threshold else ("", round(best_score, 3))

    def forget(self, name):
        return self.profiles.pop((name or "").strip(), None) is not None


__all__ = ["VoiceID", "vosk_embedder", "load_profiles", "save_profiles"]
