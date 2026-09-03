import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.auth_service import (
    AuthError,
    generate_mfa_secret,
    hash_password,
    mint_session,
    provisioning_uri,
    rotate_refresh_token,
    verify_password,
    verify_totp,
)
from app.deps import get_app_settings, get_db, get_db_public, require_roles
from app.models import Organization, Role, User
from app.rate_limit import AUTH_LOGIN_LIMIT, AUTH_REFRESH_LIMIT, AUTH_REGISTER_LIMIT, limiter
from app.validation import EmailAddress

router = APIRouter(tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


class RegisterOrgRequest(BaseModel):
    organization_name: str = PydField(min_length=2, max_length=200)
    admin_email: EmailAddress
    admin_password: str = PydField(min_length=12)


class LoginRequest(BaseModel):
    email: EmailAddress
    password: str
    totp_code: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MfaEnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaActivateRequest(BaseModel):
    code: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    organization_id: uuid.UUID
    mfa_enabled: bool


@router.post("/auth/register-org", status_code=201)
@limiter.limit(AUTH_REGISTER_LIMIT)
async def register_organization(
    request: Request, body: RegisterOrgRequest, db: AsyncSession = Depends(get_db_public)
) -> dict[str, object]:
    existing = (
        await db.execute(select(Organization).where(Organization.name == body.organization_name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Organization already exists")

    email_taken = (
        await db.execute(select(User).where(User.email == body.admin_email.lower()))
    ).scalar_one_or_none()
    if email_taken is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    org = Organization(name=body.organization_name)
    db.add(org)
    await db.flush()
    admin = User(
        organization_id=org.id,
        email=body.admin_email.lower(),
        password_hash=hash_password(body.admin_password),
        role=Role.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    await record_event(
        db,
        action="organization.registered",
        entity_type="organization",
        entity_id=org.id,
        actor_id=admin.id,
        organization_id=org.id,
    )
    return {"organization_id": str(org.id), "admin_user_id": str(admin.id)}


@router.post("/auth/login", response_model=TokenPairResponse)
@limiter.limit(AUTH_LOGIN_LIMIT)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    user = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    if user.mfa_enabled:
        if body.totp_code is None:
            raise HTTPException(status_code=401, detail="TOTP code required")
        if not verify_totp(user.mfa_secret, body.totp_code):
            raise HTTPException(status_code=401, detail="Invalid TOTP code")

    settings = get_app_settings(request)
    access, refresh = await mint_session(
        db,
        user,
        jwt_secret=settings.jwt_secret,
        access_minutes=settings.access_token_minutes,
        refresh_days=settings.refresh_token_days,
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenPairResponse(access_token=access, refresh_token=refresh)


@router.post("/auth/refresh", response_model=TokenPairResponse)
@limiter.limit(AUTH_REFRESH_LIMIT)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    settings = get_app_settings(request)
    try:
        access, new_refresh, _org = await rotate_refresh_token(
            db,
            body.refresh_token,
            jwt_secret=settings.jwt_secret,
            access_minutes=settings.access_token_minutes,
            refresh_days=settings.refresh_token_days,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return TokenPairResponse(access_token=access, refresh_token=new_refresh)


@router.post("/auth/mfa/enroll", response_model=MfaEnrollResponse)
async def enroll_mfa(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_roles(Role.ADMIN.value, Role.HIRING_MANAGER.value, Role.RECRUITER.value)
    ),
) -> MfaEnrollResponse:
    fresh = await db.merge(user)
    secret = generate_mfa_secret()
    fresh.mfa_secret = secret
    fresh.mfa_enabled = False
    await record_event(
        db,
        action="mfa.enrolled",
        entity_type="user",
        entity_id=fresh.id,
        actor_id=fresh.id,
        organization_id=fresh.organization_id,
    )
    return MfaEnrollResponse(secret=secret, otpauth_uri=provisioning_uri(fresh.email, secret))


@router.post("/auth/mfa/activate")
async def activate_mfa(
    body: MfaActivateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_roles(Role.ADMIN.value, Role.HIRING_MANAGER.value, Role.RECRUITER.value)
    ),
) -> dict[str, object]:
    fresh = await db.merge(user)
    if fresh.mfa_secret is None:
        raise HTTPException(status_code=400, detail="No MFA enrollment in progress")
    if not verify_totp(fresh.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    fresh.mfa_enabled = True
    await record_event(
        db,
        action="mfa.activated",
        entity_type="user",
        entity_id=fresh.id,
        actor_id=fresh.id,
        organization_id=fresh.organization_id,
    )
    return {"status": "enabled"}


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(require_roles())) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        organization_id=user.organization_id,
        mfa_enabled=user.mfa_enabled,
    )
