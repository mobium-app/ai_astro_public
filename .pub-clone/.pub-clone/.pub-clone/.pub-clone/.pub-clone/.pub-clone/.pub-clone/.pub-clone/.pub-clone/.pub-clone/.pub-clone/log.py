"""Logowanie ASTRO (C6): jeden logger (`astro`), poziomy, plik + konsola.

Stopniowe zastępowanie `print`/cichych `except … pass`. Zapis do `runtime/logs/astro.log`.
Brak konfiguracji = brak wyjątku (logowanie nigdy nie może wywalić agenta).
"""

import logging
import os

from . import config

_configured = False


def _configure():
    root = logging.getLogger("astro")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        os.makedirs(str(config.LOGS_DIR), exist_ok=True)
        fh = logging.FileHandler(os.path.join(str(config.LOGS_DIR), "astro.log"),
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(sh)


def get_logger(name="astro"):
    """Logger podrzędny `astro.<name>` (konfiguracja przy pierwszym użyciu)."""
    global _configured
    if not _configured:
        _configure()
        _configured = True
    return logging.getLogger("astro" if name == "astro" else f"astro.{name}")


__all__ = ["get_logger"]
