import uuid

import jwt as pyjwt
import pytest

from app.auth_service import (
    AuthError,
    decode_access_token,
    hash_password,
    issue_access_token,
    issue_refresh_token,
    verify_password,
    verify_totp,
)
from app.models import Role, User, utcnow


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="tester@example.test",
        password_hash="x",
        role=Role.RECRUITER.value,
    )


def test_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "wrong password")


def test_access_token_roundtrip() -> None:
    user = _user()
    token = issue_access_token(user, "secret-value-at-least-24-chars!", 15)
    payload = decode_access_token(token, "secret-value-at-least-24-chars!")
    assert payload["sub"] == str(user.id)
    assert payload["role"] == Role.RECRUITER.value
    assert payload["type"] == "access"


def test_expired_access_token_rejected() -> None:
    user = _user()
    token = issue_access_token(user, "secret-value-at-least-24-chars!", -1)
    with pytest.raises(AuthError):
        decode_access_token(token, "secret-value-at-least-24-chars!")


def test_wrong_secret_rejected() -> None:
    user = _user()
    token = issue_access_token(user, "secret-value-at-least-24-chars!", 15)
    with pytest.raises(AuthError):
        decode_access_token(token, "different-secret-value-24chars!!")


def test_tampered_payload_rejected() -> None:
    secret = "secret-value-at-least-24-chars!"
    user = _user()
    token = issue_access_token(user, secret, 15)
    header, body, signature = token.split(".")
    tampered_body = body[:-4] + ("AAAA" if not body.endswith("AAAA") else "BBBB")
    with pytest.raises(AuthError):
        decode_access_token(f"{header}.{tampered_body}.{signature}", secret)


def test_wrong_type_token_rejected() -> None:
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    refresh_only = pyjwt.encode(
        {"sub": str(_user().id), "type": "refresh", "exp": now + datetime.timedelta(minutes=5)},
        "secret-value-at-least-24-chars!",
        algorithm="HS256",
    )
    assert isinstance(refresh_only, str)
    with pytest.raises(AuthError):
        decode_access_token(refresh_only, "secret-value-at-least-24-chars!")


def test_refresh_tokens_unique_and_digest_shaped() -> None:
    raw_a, digest_a = issue_refresh_token()
    raw_b, digest_b = issue_refresh_token()
    assert raw_a != raw_b
    assert digest_a != digest_b
    assert len(digest_a) == 64
    int(digest_a, 16)


def test_totp_verify_accepts_current_code_only() -> None:
    import pyotp

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    assert verify_totp(secret, totp.now())
    assert not verify_totp(secret, "000000")
    assert not verify_totp(None, totp.now())


def test_utcnow_is_timezone_aware() -> None:
    assert utcnow().tzinfo is not None
