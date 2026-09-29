"""Stan afektywny ASTRO (E7.2): PAD + dwuszybki zanik (emocja szybka, nastrój wolny).

PAD = Pleasure (przyjemność), Arousal (pobudzenie), Dominance (sprawczość), zakres -1..1.
To warstwa zmienna osobowości; temperament (stabilny) żyje w `persona/`. Bez modelu i bez sieci.
"""

import math
import time

from .. import config

# Kotwice semantyczne PAD -> opis słowny + wskazówka ekspresji (najbliższa odległość).
ANCHORS = (
    ("radosna", "mów żywo i ciepło", (0.7, 0.6, 0.3)),
    ("zadowolona", "mów spokojnie i ciepło", (0.4, 0.2, 0.2)),
    ("zaciekawiona", "okaż ciekawość, możesz dopytać", (0.3, 0.5, 0.1)),
    ("skupiona", "mów zwięźle i konkretnie", (0.1, -0.2, 0.4)),
    ("neutralna", "mów rzeczowo", (0.0, 0.0, 0.0)),
    ("czujna", "bądź ostrożna, ostrzeż o ryzyku", (-0.2, 0.4, -0.2)),
    ("zmartwiona", "mów spokojnie i współczująco", (-0.5, 0.2, -0.4)),
    ("rozdrażniona", "hamuj emocje, bądź rzeczowa", (-0.5, 0.6, 0.3)),
    ("zmęczona", "mów krótko i cicho", (-0.2, -0.5, -0.3)),
)


def _clip(v):
    return max(-1.0, min(1.0, float(v)))


def _as_pad(triple):
    return tuple(_clip(x) for x in (triple or (0.0, 0.0, 0.0)))


class AffectState:
    def __init__(self, mood=(0.0, 0.0, 0.0), emotion=(0.0, 0.0, 0.0), ts=None,
                 emotion_half_life=None, mood_half_life=None):
        self.mood = list(_as_pad(mood))
        self.emotion = list(_as_pad(emotion))
        self.ts = time.time() if ts is None else float(ts)
        self.emotion_half_life = (config.AFFECT_EMOTION_HALF_LIFE if emotion_half_life is None
                                  else float(emotion_half_life))
        self.mood_half_life = (config.AFFECT_MOOD_HALF_LIFE if mood_half_life is None
                               else float(mood_half_life))

    @staticmethod
    def _factor(elapsed, half_life):
        if half_life <= 0:
            return 0.0
        return math.pow(0.5, max(0.0, elapsed) / half_life)

    def decay(self, now=None):
        now = time.time() if now is None else float(now)
        elapsed = now - self.ts
        if elapsed <= 0:
            return self
        fe = self._factor(elapsed, self.emotion_half_life)
        fm = self._factor(elapsed, self.mood_half_life)
        self.emotion = [v * fe for v in self.emotion]
        self.mood = [v * fm for v in self.mood]
        self.ts = now
        return self

    def apply(self, pleasure=0.0, arousal=0.0, dominance=0.0, mood_share=0.25):
        """Dodaje bodziec: mocno do emocji (szybkiej), słabiej do nastroju (wolnego)."""
        for i, delta in enumerate((pleasure, arousal, dominance)):
            self.emotion[i] = _clip(self.emotion[i] + float(delta))
            self.mood[i] = _clip(self.mood[i] + float(delta) * float(mood_share))
        return self

    def effective(self):
        return tuple(_clip(self.mood[i] + self.emotion[i]) for i in range(3))

    def describe(self, now=None):
        self.decay(now)
        p = self.effective()
        label, guidance, _anchor = min(
            ANCHORS, key=lambda a: sum((p[i] - a[2][i]) ** 2 for i in range(3)))
        return label, guidance

    def context_block(self, now=None):
        label, guidance = self.describe(now)
        return f"NASTRÓJ ASTRO: {label}. {guidance.capitalize()}."

    def snapshot(self):
        return {"ts": self.ts,
                "mood": list(self.mood), "emotion": list(self.emotion)}

    @classmethod
    def from_snapshot(cls, data):
        data = data or {}
        return cls(mood=data.get("mood") or (0, 0, 0),
                   emotion=data.get("emotion") or (0, 0, 0),
                   ts=data.get("ts"))
