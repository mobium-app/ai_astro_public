"""OCR ASTRO (Faza 5 „oczy"): czytanie tekstu z obrazu/kamery — offline, lokalnie.

Silnik: **Tesseract** (pakiet systemowy `tesseract-ocr` + `tesseract-ocr-pol`). Wybór świadomy:
działa w procesie `astro.service` (bez NPU, bez GStreamera), offline, prosty w utrzymaniu —
a NPU Hailo-10H i tak nie ma publicznego HEF OCR (paddle_ocr to pipeline GStreamer z `.so`).
Tesseract jest wystarczający do „przeczytaj, co jest na kartce".

Wymaga: `tesseract` w PATH (albo `ASTRO_TESSERACT`). Gdy brak — czytelny komunikat, brak wyjątku.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .. import config


def available():
    return bool(_bin())


def _bin():
    return getattr(config, "TESSERACT_BIN", "") or shutil.which("tesseract") or ""


def read_text(image_path, lang=None, psm=6, timeout=25):
    """Zwraca rozpoznany tekst z obrazu (str) albo "".

    `psm=6` = jednolity blok tekstu (dobry dla kartek/ekranów); `lang` domyślnie `pol+eng`.
    """
    binary = _bin()
    if not binary or not image_path or not os.path.isfile(image_path):
        return ""
    lang = lang or getattr(config, "OCR_LANG", "pol+eng")
    try:
        out = subprocess.run([binary, image_path, "stdout", "-l", lang, "--psm", str(psm)],
                             capture_output=True, timeout=timeout)
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    return _clean(out.stdout.decode("utf-8", "replace"))


def read_text_bytes(image_bytes, lang=None, psm=6):
    """OCR ze strumienia obrazu (JPEG/PNG). Zapisuje tymczasowo i woła `read_text`."""
    import tempfile
    if not image_bytes:
        return ""
    tmp = os.path.join(tempfile.gettempdir(), "astro-ocr.png")
    try:
        with open(tmp, "wb") as fh:
            fh.write(image_bytes)
        return read_text(tmp, lang=lang, psm=psm)
    except OSError:
        return ""


def _clean(text):
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    # Sklej łamane linie w akapity, jeśli pojedyncze słowa (typowe przy psm=6).
    merged = []
    for ln in lines:
        if merged and len(ln.split()) <= 2 and not merged[-1].endswith((".", "!", "?", ":")):
            merged[-1] = merged[-1] + " " + ln
        else:
            merged.append(ln)
    return "\n".join(merged).strip()
