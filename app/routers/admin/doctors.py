from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, UploadFile, File
from app.core.config import settings
from app.core.deps import require_roles
from app.core.security import hash_password
from app.repos.doctors import DoctorsRepo
from app.repos.users import UsersRepo
from app.core.pagination import calc_has_more
from app.core.errors import http_error
from app.utils.csv_import import parse_csv_bytes
from app.utils.phone import normalize_indian_phone

router = APIRouter(prefix="/api/admin/doctors", tags=["Admin"])


def _doctor_identity(payload: dict, fallback: dict | None = None) -> tuple[str, str, str | None]:
    base = fallback or {}
    full_name = str(payload.get("name") or base.get("name") or "").strip()
    email = str(payload.get("email") or base.get("email") or "").lower().strip()
    raw_phone = str(payload.get("phone") or base.get("phone") or "").strip()
    phone = normalize_indian_phone(raw_phone) if raw_phone else None
    return full_name, email, phone


async def _ensure_doctor_user(
    *,
    payload: dict,
    users: UsersRepo,
    existing_user_id: str | None = None,
    fallback: dict | None = None,
) -> str:
    full_name, email, phone = _doctor_identity(payload, fallback=fallback)

    if not full_name:
        http_error(400, "VALIDATION_ERROR", "Doctor name is required")
    if not email:
        http_error(400, "VALIDATION_ERROR", "Doctor email is required")

    linked_user = await users.get_by_id(existing_user_id) if existing_user_id else None
    email_owner = await users.get_by_email(email)
    phone_owner = await users.get_by_phone(phone) if phone else None

    candidate = linked_user or email_owner or phone_owner
    candidate_id = str(candidate.get("_id")) if candidate else None

    if email_owner and candidate_id != str(email_owner.get("_id")):
        http_error(409, "EMAIL_EXISTS", "Email already registered")
    if phone_owner and candidate_id != str(phone_owner.get("_id")):
        http_error(409, "PHONE_EXISTS", "Phone already registered")

    if candidate:
        if candidate.get("role") not in {None, "doctor"}:
            http_error(409, "USER_CONFLICT", "Doctor login cannot be linked to a non-doctor account")
        await users.update_doctor_login_profile(
            str(candidate["_id"]),
            full_name=full_name,
            email=email,
            phone=phone,
            status="active",
        )
        return str(candidate["_id"])

    created = await users.create_user({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password_hash": hash_password(settings.DOCTOR_DEFAULT_PASSWORD),
        "role": "doctor",
        "status": "active",
        "must_change_password": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "source": "admin_doctor_create",
    })
    return str(created["_id"])

@router.get("")
async def list_admin_doctors(
    search: str | None = None,
    specialty_id: str | None = None,
    city_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: DoctorsRepo = Depends(DoctorsRepo),
):
    data, total = await repo.admin_list(search=search, specialty_id=specialty_id, city_id=city_id, page=page, page_size=page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.post("")
async def create_doctor(
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: DoctorsRepo = Depends(DoctorsRepo),
    users: UsersRepo = Depends(UsersRepo),
):
    payload = dict(payload or {})
    payload["user_id"] = await _ensure_doctor_user(payload=payload, users=users)
    payload["createdAt"] = datetime.now(timezone.utc)
    payload["updatedAt"] = datetime.now(timezone.utc)
    doc = await repo.create(payload)
    return {"doctor": {"id": str(doc["_id"]), **{k:v for k,v in doc.items() if k != "_id"}}}

@router.put("/{id}")
async def update_doctor(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: DoctorsRepo = Depends(DoctorsRepo),
    users: UsersRepo = Depends(UsersRepo),
):
    existing = await repo.get_doctor(id)
    if not existing:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert existing is not None
    payload = dict(payload or {})
    payload["user_id"] = await _ensure_doctor_user(
        payload=payload,
        users=users,
        existing_user_id=str(existing.get("user_id") or existing.get("userId") or "") or None,
        fallback=existing,
    )
    payload["updatedAt"] = datetime.now(timezone.utc)
    doc = await repo.update(id, payload)
    if not doc:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
        return
    assert doc is not None
    return {"doctor": {"id": str(doc["_id"]), **{k:v for k,v in doc.items() if k != "_id"}}}

@router.post("/import")
async def import_doctors(
    file: UploadFile = File(...),
    _admin=Depends(require_roles("admin")),
    repo: DoctorsRepo = Depends(DoctorsRepo),
    users: UsersRepo = Depends(UsersRepo),
):
    data = await file.read()
    rows = parse_csv_bytes(data)
    inserted = 0
    for r in rows:
        r["user_id"] = await _ensure_doctor_user(payload=r, users=users)
        r["createdAt"] = datetime.now(timezone.utc)
        r["updatedAt"] = datetime.now(timezone.utc)
        await repo.create(r)
        inserted += 1
    return {"message": "Imported", "inserted": inserted}


@router.delete("/{id}")
async def delete_doctor(id: str, _admin=Depends(require_roles("admin")), repo: DoctorsRepo = Depends(DoctorsRepo)):
    ok = await repo.delete(id)
    if not ok:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    return {"ok": True}
