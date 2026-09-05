"""Unit tests for AES-256-GCM encryption at rest (ADR-025).

No database needed: exercises encrypt_text/decrypt_text and the
EncryptedText TypeDecorator's bind/result methods directly.
"""

import base64

import pytest

from app.crypto import DecryptionError, EncryptedText, decrypt_text, encrypt_text


def test_round_trip_preserves_plaintext() -> None:
    original = "Jane Doe — 5 years Python, jane@example.com, +1 555 0100"
    blob = encrypt_text(original)
    assert decrypt_text(blob) == original


def test_ciphertext_does_not_contain_plaintext() -> None:
    original = "sensitive-resume-content-marker"
    blob = encrypt_text(original)
    assert original.encode("utf-8") not in blob


def test_two_encryptions_of_same_plaintext_differ() -> None:
    original = "same input twice"
    first = encrypt_text(original)
    second = encrypt_text(original)
    assert first != second  # fresh random nonce each time
    assert decrypt_text(first) == decrypt_text(second) == original


def test_tampered_ciphertext_fails_to_decrypt() -> None:
    blob = bytearray(encrypt_text("do not tamper with me"))
    blob[-1] ^= 0xFF  # flip last byte of the GCM auth tag
    with pytest.raises(DecryptionError):
        decrypt_text(bytes(blob))


def test_truncated_blob_rejected() -> None:
    with pytest.raises(DecryptionError):
        decrypt_text(b"short")


def test_encrypted_text_type_decorator_round_trips() -> None:
    column = EncryptedText()
    bound = column.process_bind_param("candidate answer text", dialect=None)
    assert isinstance(bound, bytes)
    assert column.process_result_value(bound, dialect=None) == "candidate answer text"


def test_encrypted_text_type_decorator_passes_through_none() -> None:
    column = EncryptedText()
    assert column.process_bind_param(None, dialect=None) is None
    assert column.process_result_value(None, dialect=None) is None


def test_wrong_key_cannot_decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.crypto as crypto_module

    blob = encrypt_text("secret under key A")

    crypto_module._aesgcm.cache_clear()
    other_key = base64.b64encode(b"\x01" * 32).decode()
    monkeypatch.setenv("AIVA_ENCRYPTION_KEY", other_key)
    crypto_module.get_settings.cache_clear()  # type: ignore[attr-defined]

    with pytest.raises(DecryptionError):
        crypto_module.decrypt_text(blob)

    crypto_module._aesgcm.cache_clear()
    crypto_module.get_settings.cache_clear()  # type: ignore[attr-defined]
