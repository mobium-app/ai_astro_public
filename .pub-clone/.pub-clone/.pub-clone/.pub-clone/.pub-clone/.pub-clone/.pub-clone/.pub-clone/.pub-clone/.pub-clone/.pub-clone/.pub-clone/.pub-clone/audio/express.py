"""Ekspresyjny TTS ASTRO (E8.2): plan wyrażania per nastrój.

Spina temperament/nastrój z brzmieniem głosu: łańcuch efektów sox (`voice_style`), opcjonalny
głos per nastrój (Piper: inne modele .onnx) oraz **pauza** po wypowiedzi. To w pełni offline;
docelowo można podmienić silnik na ekspresyjny model PL przez `ASTRO_TTS_VOICE_<NASTRÓJ>`.
Piper nie ma wbudowanej emocji — wyrażamy ją prosodią (znane ograniczenie).
"""

import os

from .. import config
from ..safety import normalize_facts
from . import voice_style

# Pauza po wypowiedzi (s) wg nastroju — spokojniejsze/cięższe mówią wolniej i zostawiają oddech.
PAUSE = {
    "radosna": 0.2, "zadowolona": 0.5, "zaciekawiona": 0.4, "skupiona": 0.5,
    "neutralna": 0.6, "czujna": 0.7, "zmartwiona": 0.9, "rozdrażniona": 0.4, "zmęczona": 1.0,
}


def _env_voice(label):
    key = "ASTRO_TTS_VOICE_" + normalize_facts(label).upper().replace(" ", "_")
    return os.environ.get(key, "").strip()


def voice_for(label, default=None):
    """Głos (model Piper) dla nastroju: `ASTRO_TTS_VOICE_<NASTRÓJ>`, inaczej domyślny."""
    return _env_voice(label) or (default or config.TTS_MODEL)


def pause_for(label, scale=None):
    scale = getattr(config, "TTS_PAUSE_SCALE", 1.0) if scale is None else float(scale)
    return round(PAUSE.get(label, 0.6) * scale, 3)


def plan(label="neutralna", text=""):
    """Plan wyrażania: fx + model + pauza. Gdy brak nastroju — neutralny."""
    label = label or "neutralna"
    return {
        "mood": label,
        "fx": voice_style.fx_for(label),
        "model": voice_for(label),
        "pause": pause_for(label),
        "text": text or "",
    }


def plan_for_affect(memory, text=""):
    """Plan na podstawie aktualnego nastroju z pamięci (albo neutralny)."""
    store = getattr(memory, "affect", None) if memory is not None else None
    if store is None:
        return plan("neutralna", text)
    try:
        label, _guidance = store.load().describe()
    except Exception:
        label = "neutralna"
    return plan(label, text)
