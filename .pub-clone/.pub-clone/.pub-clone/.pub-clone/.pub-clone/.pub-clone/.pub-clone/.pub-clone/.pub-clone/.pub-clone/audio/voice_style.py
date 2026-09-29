"""Presety głosu ASTRO per nastrój (E7.5): mapowanie stanu PAD -> łańcuch efektów sox.

Piper nie steruje emocją (stan 2026), więc wyrażamy nastrój **prosodią**: ton, tempo, pogłos,
głośność. To przybliżenie, nie pełna emocja — świadome ograniczenie obecnego stosu.
"""

import json
import os

from .. import config

# Profil barwy głosu (przełączany głosowo): None = wg config.TTS_PITCH (domyślnie),
# "clean" = czysty głos (bez pitch), "robocik" = pitch robocika. Trwałość: runtime/voice_profile.json.
_ROBOCIK_FALLBACK = "pitch 350 tempo 1.06"
_profile_cache = {"mtime": None, "profile": None}


def _profile_path():
    return os.path.join(str(config.RUNTIME_DIR), "voice_profile.json")

# Łańcuchy sox. WNIOSEK Z POMIARU (scripts/tts_bench.py): pitch/chorus/reverb/echo istotnie
# POGARSZAJĄ zrozumiałość (czysty głos ~78%, z efektami ~40–65%). Dlatego nastrój wyrażamy
# **tempem i głośnością** (te nie szkodzą), a nie pogłosem/robotyzacją. Robotyzację można włączyć
# świadomie profilem `ASTRO_TTS_FX_PROFILE=subtle|classic`.
PRESETS = {
    "radosna": "tempo 1.06 gain 1",
    "zadowolona": None,  # None = domyślny profil z config.TTS_FX
    "zaciekawiona": "tempo 1.03",
    "skupiona": "tempo 0.98 gain -1",
    "neutralna": None,
    "czujna": "tempo 0.96 gain -2",
    "zmartwiona": "tempo 0.92 gain -2",
    "rozdrażniona": "tempo 1.08 gain 0",
    "zmęczona": "tempo 0.9 gain -3",
}


def load_profile():
    """Aktywny profil barwy głosu: None (wg config), „clean" albo „robocik".

    Cache unieważnia się po mtime pliku (podobnie jak cache gramatyki Voska)."""
    try:
        mtime = os.stat(_profile_path()).st_mtime
    except OSError:
        _profile_cache.update(mtime=None, profile=None)
        return None
    if _profile_cache["mtime"] == mtime:
        return _profile_cache["profile"]
    prof = None
    try:
        with open(_profile_path(), encoding="utf-8") as fh:
            prof = str(json.load(fh).get("profile", "")).strip().lower()
    except Exception:
        prof = None
    if prof not in ("clean", "robocik"):
        prof = None
    _profile_cache.update(mtime=mtime, profile=prof)
    return prof


def set_profile(name):
    """Ustawia i utrwala profil głosu („clean"/„robocik"/None=domyślny). Zwraca zapisany profil."""
    prof = (name or "").strip().lower()
    if prof not in ("clean", "robocik"):
        prof = None
    path = _profile_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"profile": prof or ""}, fh)
    _profile_cache.update(mtime=os.stat(path).st_mtime, profile=prof)
    return prof


def _base_pitch():
    """Bazowa warstwa barwy: profil nadpisuje config („clean" wyłącza pitch robocika)."""
    prof = load_profile()
    if prof == "clean":
        return ""
    if prof == "robocik":
        return getattr(config, "TTS_PITCH", "") or _ROBOCIK_FALLBACK
    return getattr(config, "TTS_PITCH", "")


def _compose(base, chain):
    parts = [p.strip() for p in (base or "", chain or "") if p and p.strip()]
    return " ".join(parts)


def fx_for(label, default=None):
    """Łańcuch sox dla etykiety nastroju (None -> domyślny profil z configu).

    Do łańcucha doklejana jest bazowa warstwa barwy `config.TTS_PITCH` (np. „dziecięcy" ton),
    dzięki czemu ton jest spójny we wszystkich nastrojach, a prosodia (tempo/gain) pozostaje
    per nastrój.
    """
    fx = PRESETS.get(label)
    if fx is None:
        chain = default if default is not None else config.TTS_FX
    else:
        chain = fx
    return _compose(_base_pitch(), chain)


def affect_fx(memory, default=None):
    """Łańcuch sox wynikający z aktualnego nastroju w pamięci."""
    store = getattr(memory, "affect", None) if memory is not None else None
    if store is None:
        return fx_for(None, default)
    try:
        label, _guidance = store.load().describe()
    except Exception:
        return fx_for(None, default)
    return fx_for(label, default)
