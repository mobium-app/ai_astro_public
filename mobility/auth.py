"""Autoryzacja tokenem sha256 (wzorzec API v1; token w ~/astro/secrets/mobility.token, 600)."""

import hmac
import hashlib
from pathlib import Path

DEFAULT_TOKEN_PATH = Path(__file__).resolve().parents[1] / "secrets" / "mobility.token"


def load_token(path: Path = DEFAULT_TOKEN_PATH) -> str:
    if not path.exists():
        raise RuntimeError(f"Brak tokenu: {path} (wygeneruj: sha256sum /dev/urandom)")
    return path.read_text().strip()


def check_token(header: str | None, token: str) -> bool:
    if not header or not header.startswith("Bearer "):
        return False
    given = header[len("Bearer "):].strip()
    digest = hashlib.sha256(given.encode()).hexdigest()
    return hmac.compare_digest(digest, token)