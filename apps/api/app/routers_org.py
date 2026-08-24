import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_db, require_roles
from app.models import Department, Organization, Requisition, RequisitionStatus, Role, User

router = APIRouter(tags=["orgs"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
    Role.INTERVIEWER.value,
    Role.AUDITOR.value,
)
REQUISITION_EDIT_ROLES = (Role.ADMIN.value, Role.HIRING_MANAGER.value, Role.RECRUITER.value)


class DepartmentCreate(BaseModel):
    name: str = PydField(min_length=1, max_length=200)


class StaffUserCreate(BaseModel):
    email: EmailStr
    password: str = PydField(min_length=12)
    role: Role


class RequisitionCreate(BaseModel):
    title: str = PydField(min_length=1, max_length=300)
    department_id: uuid.UUID


class RequisitionUpdate(BaseModel):
    title: str | None = PydField(default=None, min_length=1, max_length=300)
    status: RequisitionStatus | None = None


async def _get_org(db: AsyncSession, organization_id: uuid.UUID) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.id == organization_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.get("/orgs/{organization_id}", dependencies=[Depends(require_roles(*STAFF_ROLES))])
async def get_organization(
    organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    org = await _get_org(db, organization_id)
    return {"id": str(org.id), "name": org.name}


@router.post("/orgs/{organization_id}/users", status_code=201)
async def create_staff_user(
    organization_id: uuid.UUID,
    body: StaffUserCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN.value)),
) -> dict[str, object]:
    await _get_org(db, organization_id)
    if user.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")
    if body.role == Role.CANDIDATE:
        raise HTTPException(status_code=400, detail="Candidates are not org staff")
    email_taken = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if email_taken is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    from app.auth_service import hash_password

    staff = User(
        organization_id=organization_id,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role=body.role.value,
    )
    db.add(staff)
    await db.flush()
    await record_event(
        db,
        action="user.created",
        entity_type="user",
        entity_id=staff.id,
        actor_id=user.id,
        organization_id=organization_id,
        payload={"role": staff.role},
    )
    return {"id": str(staff.id), "email": staff.email, "role": staff.role}


@router.post("/orgs/{organization_id}/departments", status_code=201)
async def create_department(
    organization_id: uuid.UUID,
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN.value)),
) -> dict[str, object]:
    await _get_org(db, organization_id)
    if user.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")
    dept = Department(organization_id=organization_id, name=body.name)
    db.add(dept)
    await db.flush()
    await record_event(
        db,
        action="department.created",
        entity_type="department",
        entity_id=dept.id,
        actor_id=user.id,
        organization_id=organization_id,
        payload={"name": body.name},
    )
    return {"id": str(dept.id), "name": dept.name, "organization_id": str(organization_id)}


@router.get("/departments/{department_id}")
async def get_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    dept = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if dept is None or dept.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"id": str(dept.id), "name": dept.name, "organization_id": str(dept.organization_id)}


@router.post("/departments/{department_id}/requisitions", status_code=201)
async def create_requisition(
    department_id: uuid.UUID,
    body: RequisitionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*REQUISITION_EDIT_ROLES)),
) -> dict[str, object]:
    if body.department_id != department_id:
        raise HTTPException(status_code=400, detail="Department mismatch")
    dept = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if dept is None or dept.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Department not found")

    req = Requisition(
        department_id=department_id,
        title=body.title,
        status=RequisitionStatus.DRAFT.value,
        created_by=user.id,
    )
    db.add(req)
    await db.flush()
    await record_event(
        db,
        action="requisition.created",
        entity_type="requisition",
        entity_id=req.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"title": body.title},
    )
    return {"id": str(req.id), "title": req.title, "status": req.status, "version": req.version}


@router.get("/requisitions/{requisition_id}")
async def get_requisition(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    req = (
        await db.execute(select(Requisition).where(Requisition.id == requisition_id))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    dept = (
        await db.execute(select(Department).where(Department.id == req.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Requisition not found")
    return {
        "id": str(req.id),
        "title": req.title,
        "status": req.status,
        "version": req.version,
        "department_id": str(req.department_id),
    }


@router.patch("/requisitions/{requisition_id}")
async def update_requisition(
    requisition_id: uuid.UUID,
    body: RequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*REQUISITION_EDIT_ROLES)),
) -> dict[str, object]:
    existing = await _read_requisition_scoped(db, user, requisition_id)
    changes: dict[str, object] = {}
    if body.title is not None and body.title != existing["title"]:
        changes["title"] = body.title
    if body.status is not None and body.status.value != existing["status"]:
        changes["status"] = body.status.value
    if not changes:
        return existing

    req = (
        await db.execute(select(Requisition).where(Requisition.id == requisition_id))
    ).scalar_one()
    for field, value in changes.items():
        setattr(req, field, value)
    req.version += 1
    await db.flush()
    await record_event(
        db,
        action="requisition.updated",
        entity_type="requisition",
        entity_id=req.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"changes": changes},
    )
    return {
        "id": str(req.id),
        "title": req.title,
        "status": req.status,
        "version": req.version,
        "department_id": str(req.department_id),
    }


@router.delete("/requisitions/{requisition_id}", status_code=204)
async def delete_requisition(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN.value)),
) -> None:
    existing = await _read_requisition_scoped(db, user, requisition_id)
    req = (
        await db.execute(select(Requisition).where(Requisition.id == requisition_id))
    ).scalar_one()
    await db.delete(req)
    await record_event(
        db,
        action="requisition.deleted",
        entity_type="requisition",
        entity_id=req.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"title": existing["title"]},
    )


async def _read_requisition_scoped(
    db: AsyncSession, user: User, requisition_id: uuid.UUID
) -> dict[str, object]:
    result = (
        await db.execute(select(Requisition).where(Requisition.id == requisition_id))
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    dept = (
        await db.execute(select(Department).where(Department.id == result.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Requisition not found")
    return {"title": result.title, "status": result.status}
