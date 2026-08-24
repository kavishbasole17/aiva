import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken, User, utcnow

password_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(email: str, secret: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="AIVA")


def verify_totp(secret: str | None, code: str) -> bool:
    if not secret:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def _encode(payload: dict[str, object], secret: str) -> str:
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def _decode(token: str, secret: str) -> dict[str, object]:
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc


def issue_access_token(user: User, secret: str, lifetime_minutes: int) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "org": str(user.organization_id),
        "role": user.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=lifetime_minutes),
        "jti": uuid.uuid4().hex,
    }
    return _encode(payload, secret)


def decode_access_token(token: str, secret: str) -> dict[str, object]:
    payload = _decode(token, secret)
    if payload.get("type") != "access":
        raise AuthError("Wrong token type")
    return payload


def issue_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest


async def mint_session(
    session: AsyncSession,
    user: User,
    *,
    jwt_secret: str,
    access_minutes: int,
    refresh_days: int,
) -> tuple[str, str]:
    access = issue_access_token(user, jwt_secret, access_minutes)
    raw, digest = issue_refresh_token()
    family_id = uuid.uuid4()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=digest,
            expires_at=utcnow() + timedelta(days=refresh_days),
        )
    )
    await session.flush()
    return access, raw


async def rotate_refresh_token(
    session: AsyncSession,
    presented: str,
    *,
    jwt_secret: str,
    access_minutes: int,
    refresh_days: int,
) -> tuple[str, str, uuid.UUID]:
    digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == digest))
    ).scalar_one_or_none()

    if row is None:
        raise AuthError("Unknown refresh token")

    if row.is_reused():
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        raise AuthError("Refresh token reuse detected; family revoked", status_code=401)

    if not row.is_live():
        raise AuthError("Refresh token expired or revoked")

    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == row.id, RefreshToken.rotated_at.is_(None))
        .values(rotated_at=utcnow())
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise AuthError("Concurrent refresh rejected")

    user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthError("User inactive")

    access = issue_access_token(user, jwt_secret, access_minutes)
    new_raw, new_digest = issue_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=row.family_id,
            token_hash=new_digest,
            expires_at=utcnow() + timedelta(days=refresh_days),
        )
    )
    await session.flush()
    return access, new_raw, user.organization_id
