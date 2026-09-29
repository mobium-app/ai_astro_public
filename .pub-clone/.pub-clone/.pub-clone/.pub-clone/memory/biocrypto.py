"""Ochrona biometrii ASTRO (Faza 6): szyfrowanie embeddingów twarzy/sylwetek w spoczynku.

Dane biometryczne (twarze, sylwetki) to dane wrażliwe — nie trzymamy ich jawnie w SQLite.
Embeddingi zapisujemy jako **AES-GCM** (klucz w pliku poza repo, uprawnienia 0600), z losowym
nonce. Bez klucza danych nie da się odczytać; klucza można użyć do rotacji.

Zgodność wstecz: odczyt próbuje odszyfrować; jeśli wpis nie jest zaszyfrowany (stary format),
zwraca go jawnie (i można go przepisać `encrypt_existing_bio()`). Gdy `cryptography` niedostępne,
moduł działa jako „przezroczysty" (jawny) — reszta systemu nie pada.
"""

from __future__ import annotations

import os

from .. import config

_MAGIC = b"ASTROBIO1"  # znacznik wersji formatu zaszyfrowanego


def _key_path():
    return str(getattr(config, "BIO_KEY_FILE", ""))


def _load_key():
    path = _key_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return raw if len(raw) == 32 else None
    except OSError:
        return None


def ensure_key(path=None):
    """Tworzy klucz AES-256 (32 B) w pliku 0600, jeśli go nie ma. Zwraca ścieżkę lub None."""
    path = path or _key_path()
    if not path:
        return None
    if os.path.isfile(path):
        return path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(os.urandom(32))
        os.chmod(path, 0o600)
    except OSError:
        return None
    return path


def available():
    """Czy szyfrowanie jest włączone i możliwe (klucz + biblioteka)."""
    if not getattr(config, "BIO_ENCRYPT", True):
        return False
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    except Exception:
        return False
    ensure_key()  # utwórz klucz przy pierwszym użyciu
    return _load_key() is not None


def encrypt(blob):
    """Szyfruje bajty (AES-GCM). Gdy brak klucza/biblioteki — zwraca jawnie."""
    if not blob:
        return blob
    if not available():
        return blob
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _load_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, blob, None)
    return _MAGIC + nonce + ct


def decrypt(blob):
    """Odszyfrowuje bajty. Gdy to nie nasz format — zwraca jak jest (zgodność wstecz)."""
    if not blob or not blob.startswith(_MAGIC):
        return blob
    if not available():
        return b""  # nie mamy klucza — nie zgadujemy
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _load_key()
    nonce, ct = blob[len(_MAGIC):len(_MAGIC) + 12], blob[len(_MAGIC) + 12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None)
    except Exception:
        return b""


def is_encrypted(blob):
    return bool(blob) and blob.startswith(_MAGIC)
