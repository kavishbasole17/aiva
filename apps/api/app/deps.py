import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import bind_rls_context
from app.email import EmailProvider
from app.models import User
from app.settings import Settings

bearer_scheme = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_email_provider(request: Request) -> EmailProvider:
    provider: EmailProvider = request.app.state.email
    return provider


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def _resolve_user(request: Request, token: str) -> User | None:
    from app.auth_service import AuthError, decode_access_token

    try:
        payload = decode_access_token(token, get_app_settings(request).jwt_secret)
    except AuthError:
        return None
    factory = get_session_factory(request)
    async with factory() as session:
        found: User | None = (
            await session.execute(select(User).where(User.id == uuid.UUID(str(payload["sub"]))))
        ).scalar_one_or_none()
    if found is None or not found.is_active:
        return None
    return found


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    if credentials is None:
        return None
    return await _resolve_user(request, credentials.credentials)


async def require_user(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_roles(
    *allowed: str,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    async def dependency(user: User = Depends(require_user)) -> User:
        if allowed and user.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return dependency


async def get_db(
    request: Request,
    user: User | None = Depends(get_optional_user),
) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(request)
    async with factory() as session:
        try:
            if user is not None:
                await bind_rls_context(
                    session,
                    organization_id=str(user.organization_id),
                    user_id=str(user.id),
                    role=user.role,
                )
            else:
                await bind_rls_context(session, organization_id=None, user_id=None, role=None)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_public(request: Request) -> AsyncIterator[AsyncSession]:
    """DB session for genuinely public, org-agnostic endpoints (org registration).

    Deliberately does not resolve or bind to any caller identity, even if the
    request happens to carry a valid Bearer token for a different organization
    (e.g. an already-authenticated staff member registering a new org from the
    same browser session). Using the normal get_db here would bind RLS to the
    caller's own organization_id via bind_rls_context, which then rejects the
    INSERT of the new organization's admin user as a row-level-security
    violation instead of using the bootstrap (no-org-context) exception.
    """
    factory = get_session_factory(request)
    async with factory() as session:
        try:
            await bind_rls_context(session, organization_id=None, user_id=None, role=None)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
