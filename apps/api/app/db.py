from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.settings import Settings


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def bind_rls_context(
    session: AsyncSession,
    *,
    organization_id: str | None,
    user_id: str | None,
    role: str | None,
) -> None:
    params: dict[str, Any] = {
        "org": organization_id or "",
        "user": user_id or "",
        "role": role or "",
    }
    await session.execute(
        text(
            "SELECT set_config('aiva.organization_id', :org, true), "
            "set_config('aiva.user_id', :user, true), "
            "set_config('aiva.role', :role, true)"
        ),
        params,
    )
