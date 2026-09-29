"""Rejestr silników STT/TTS (wtyczki audio ASTRO).

Formalizuje to, co wcześniej było przełączane przez `ASTRO_STT`/`ASTRO_TTS_ENGINE`: dodanie
nowego silnika (Vosk, Whisper inny, Piper, espeak, …) to rejestracja fabryki — bez zmian
w pętli głosowej. `build_stt`/`build_tts` tworzą instancję wg konfiguracji.
"""

from .. import config

_STT = {}
_TTS = {}


def register_stt(name, factory):
    _STT[str(name).lower()] = factory
    return factory


def register_tts(name, factory):
    _TTS[str(name).lower()] = factory
    return factory


def stt_engines():
    return sorted(_STT)


def tts_engines():
    return sorted(_TTS)


def build_stt(name=None, **kwargs):
    name = (name or config.STT_ENGINE or "npu").lower()
    if name not in _STT:
        raise KeyError(f"nieznany silnik STT: {name} (dostępne: {stt_engines()})")
    return _STT[name](**kwargs)


def build_tts(name=None, **kwargs):
    name = (name or config.TTS_ENGINE or "piper").lower()
    if name not in _TTS:
        raise KeyError(f"nieznany silnik TTS: {name} (dostępne: {tts_engines()})")
    return _TTS[name](**kwargs)


def _register_builtins():
    from .stt import STT
    from .tts import TTS
    register_stt("npu", lambda **kw: STT(engine="npu", **kw))
    register_stt("none", lambda **kw: STT(engine="none", **kw))
    register_tts("piper", lambda **kw: TTS(engine="piper", **kw))
    register_tts("espeak", lambda **kw: TTS(engine="espeak", **kw))
    register_tts("none", lambda **kw: TTS(engine="none", **kw))


_register_builtins()
