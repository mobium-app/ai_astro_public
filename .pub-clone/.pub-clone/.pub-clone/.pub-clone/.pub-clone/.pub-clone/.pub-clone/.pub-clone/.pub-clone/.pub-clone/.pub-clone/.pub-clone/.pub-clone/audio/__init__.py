"""Warstwa audio ASTRO: wake „Hej Astro", STT (NPU), TTS (słodki robocik), pętla głosowa."""

from .text import feminize, pl_number, pl_plural, prepare_speech, speakable, strip_markdown
from .wake import WAKE_GRAMMAR, WAKE_VARIANTS, WAKE_WORD, WakeDetector, is_wake, strip_wake, wake_tokens
from .stt import STT
from .tts import TTS
from .loop import SLEEP_REPLY, VoiceLoop, is_sleep
from . import capture, engines, express, signals, voice_style, wake

__all__ = ["feminize", "speakable", "strip_markdown", "prepare_speech", "pl_number", "pl_plural",
           "is_wake", "strip_wake", "wake_tokens", "WakeDetector", "WAKE_WORD", "WAKE_VARIANTS",
           "WAKE_GRAMMAR", "STT", "TTS", "VoiceLoop", "is_sleep", "SLEEP_REPLY",
           "capture", "engines", "wake", "signals", "voice_style", "express"]
