"""Application-level encryption at rest for the most sensitive text columns.

AES-256-GCM (via the `cryptography` library), key from `AIVA_ENCRYPTION_KEY`
(base64-encoded, must decode to exactly 32 raw bytes — validated fail-closed
in `settings.py`, same discipline as `jwt_secret`). Each encrypted value
stores a fresh random 12-byte nonce concatenated with the GCM ciphertext
(which includes its own 16-byte authentication tag), so tampering with
stored bytes fails decryption rather than silently returning garbage.

`EncryptedText` is a SQLAlchemy `TypeDecorator`: every other module keeps
reading/writing these columns as plain Python `str`, exactly as before —
only the bytes actually persisted to Postgres change. This means
`text_extract.py`, `matching.py`, and every existing test that reads
`.full_text`/`.value`/`.source_quote`/`.answer_text` needs no changes.

Scope (ADR-025): resume full text, extracted PII field values/quotes, and
candidate interview answers — the highest-sensitivity text this system
stores. Code submissions, discussion messages, and whiteboard strokes are
explicitly out of scope for this pass (lower sensitivity; tracked as a
follow-up, not silently omitted). Object-storage encryption (MinIO
server-side encryption via KES/Vault) remains deferred to Milestone 12 per
ADR-008 — this module only covers Postgres-resident text.
"""

import base64
import os
from functools import lru_cache

import sqlalchemy as sa
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.settings import get_settings

NONCE_BYTES = 12


class EncryptionKeyError(RuntimeError):
    """Raised when AIVA_ENCRYPTION_KEY is missing or malformed at use time."""


class DecryptionError(RuntimeError):
    """Raised when stored ciphertext fails authentication (wrong key or tampering)."""


@lru_cache
def _aesgcm() -> AESGCM:
    raw = get_settings().encryption_key
    key = base64.b64decode(raw, validate=True)  # already validated by Settings
    return AESGCM(key)


def encrypt_text(plaintext: str) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = _aesgcm().encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt_text(blob: bytes) -> str:
    if len(blob) < NONCE_BYTES:
        raise DecryptionError("Encrypted blob shorter than nonce length")
    nonce, ciphertext = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    try:
        plaintext = _aesgcm().decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise DecryptionError("Ciphertext failed authentication (wrong key or tampered)") from exc
    return plaintext.decode("utf-8")


class EncryptedText(sa.types.TypeDecorator[str]):
    """Transparent AES-256-GCM encryption for a Text-like SQLAlchemy column."""

    impl = sa.LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: sa.Dialect) -> bytes | None:
        del dialect
        if value is None:
            return None
        return encrypt_text(value)

    def process_result_value(self, value: bytes | None, dialect: sa.Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        return decrypt_text(bytes(value))


__all__ = [
    "DecryptionError",
    "EncryptedText",
    "EncryptionKeyError",
    "decrypt_text",
    "encrypt_text",
]
