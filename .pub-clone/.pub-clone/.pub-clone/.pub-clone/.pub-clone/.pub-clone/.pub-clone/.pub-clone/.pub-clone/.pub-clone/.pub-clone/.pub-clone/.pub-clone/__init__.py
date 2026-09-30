"""ASTRO — samodzielny, uczący się agent SDK."""

from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    __version__ = "0.0.0"
