from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.core.deps import require_roles
from app.core.errors import http_error
from app.core.pagination import calc_has_more
from app.core.security import hash_password
from app.repos.patients import PatientsRepo
from app.repos.users import UsersRepo
from app.utils.bson import oid
from app.utils.bson import str_id
from app.utils.phone import normalize_indian_phone


router = APIRouter(prefix="/api", tags=["Users"])


@router.get("/users")
async def list_users(
    role: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: UsersRepo = Depends(UsersRepo),
):
    items, total = await repo.list_users(role=role, status=status, page=page, page_size=page_size)
    return {
        "data": items,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": calc_has_more(total, page, page_size),
        },
    }


@router.get("/users/{id}")
async def get_user(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: UsersRepo = Depends(UsersRepo),
):
    u = await repo.get_by_id(id)
    if not u:
        http_error(404, "USER_NOT_FOUND", "User not found")
    return {
        "data": {
            "id": str(u["_id"]),
            "role": u.get("role"),
            "status": u.get("status"),
            "full_name": u.get("full_name"),
            "email": u.get("email"),
            "phone": u.get("phone"),
            "created_at": u.get("created_at").isoformat() if u.get("created_at") else None,
        }
    }


@router.post("/users")
async def create_user(
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: UsersRepo = Depends(UsersRepo),
    patients: PatientsRepo = Depends(PatientsRepo),
):
    email = (payload.get("email") or "").lower().strip()
    full_name = (payload.get("full_name") or payload.get("name") or "").strip()
    password = payload.get("password") or payload.get("password_hash")
    raw_phone = (payload.get("phone") or payload.get("mobile") or "").strip() or None
    phone = normalize_indian_phone(raw_phone) if raw_phone else None
    role = (payload.get("role") or "patient").lower().strip()
    status = (payload.get("status") or "active").lower().strip()
    gender = patients._normalize_gender(payload.get("gender")) if "gender" in payload else None
    date_of_birth = patients._normalize_date_of_birth(
        payload.get("date_of_birth") if "date_of_birth" in payload else payload.get("dateOfBirth")
    ) if ("date_of_birth" in payload or "dateOfBirth" in payload) else None

    if not email or not full_name:
        http_error(400, "VALIDATION_ERROR", "email and full_name are required")
    if not password:
        http_error(400, "VALIDATION_ERROR", "password is required")

    existing = await repo.get_by_email(email)
    if existing:
        http_error(409, "EMAIL_EXISTS", "A user with this email already exists")
    if phone and await repo.get_by_phone(phone):
        http_error(409, "PHONE_EXISTS", "A user with this phone already exists")

    doc = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password_hash": hash_password(str(password)),
        "role": role,
        "status": status,
        "gender": gender,
        "date_of_birth": date_of_birth,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "source": payload.get("source") or "admin",
    }

    created = await repo.create_user(doc)
    created_id = str(created["_id"])
    if role == "patient":
        await patients.ensure_patient_profile(
            user_id=created_id,
            payload={
                **payload,
                "user_id": created_id,
                "full_name": full_name,
                "email": email,
                "phone": phone,
                "status": status,
                "gender": gender,
                "date_of_birth": date_of_birth,
            },
        )
    created_at = created.get("created_at")
    return {
        "id": created_id,
        "role": created.get("role"),
        "status": created.get("status"),
        "full_name": created.get("full_name"),
        "email": created.get("email"),
        "phone": created.get("phone"),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
    }


@router.put("/users/{id}")
async def update_user(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: UsersRepo = Depends(UsersRepo),
    patients: PatientsRepo = Depends(PatientsRepo),
):
    existing = await repo.get_by_id(id)
    if not existing:
        http_error(404, "USER_NOT_FOUND", "User not found")

    patch = dict(payload or {})
    user_patch = {}

    if "role" in patch:
        user_patch["role"] = str(patch["role"]).lower().strip()
    if "status" in patch:
        user_patch["status"] = str(patch["status"]).lower().strip()
    if "full_name" in patch or "name" in patch:
        user_patch["full_name"] = str(patch.get("full_name") or patch.get("name") or "").strip()
    if "phone" in patch or "mobile" in patch:
        raw_phone = str(patch.get("phone") or patch.get("mobile") or "").strip() or None
        if raw_phone:
            normalized_phone = normalize_indian_phone(raw_phone)
            if not normalized_phone:
                http_error(400, "INVALID_PHONE", "Please enter a valid 10-digit phone number")
            user_patch["phone"] = normalized_phone
        else:
            user_patch["phone"] = None
    if "email" in patch:
        user_patch["email"] = str(patch.get("email") or "").lower().strip() or None
    if "gender" in patch:
        user_patch["gender"] = patients._normalize_gender(patch.get("gender"))
    if "date_of_birth" in patch or "dateOfBirth" in patch:
        user_patch["date_of_birth"] = patients._normalize_date_of_birth(
            patch.get("date_of_birth") if "date_of_birth" in patch else patch.get("dateOfBirth")
        )

    email_value = user_patch.get("email")
    if isinstance(email_value, str) and email_value and email_value != existing.get("email"):
        normalized_email = str(email_value)
        email_owner = await repo.get_by_email(normalized_email)
        if email_owner and str(email_owner.get("_id")) != id:
            http_error(409, "EMAIL_EXISTS", "A user with this email already exists")

    phone_value = user_patch.get("phone")
    if isinstance(phone_value, str) and phone_value and phone_value != existing.get("phone"):
        normalized_phone = str(phone_value)
        phone_owner = await repo.get_by_phone(normalized_phone)
        if phone_owner and str(phone_owner.get("_id")) != id:
            http_error(409, "PHONE_EXISTS", "A user with this phone already exists")

    if user_patch:
        user_patch["updated_at"] = datetime.now(timezone.utc)
        await repo.col.update_one({"_id": oid(id)}, {"$set": user_patch})

    # Password change (optional)
    if "password" in patch and patch.get("password"):
        await repo.col.update_one(
            {"_id": oid(id)},
            {"$set": {"password_hash": hash_password(str(patch["password"])), "updated_at": datetime.now(timezone.utc)}},
        )

    role_after_update = user_patch.get("role") or existing.get("role")
    if role_after_update == "patient":
        await patients.ensure_patient_profile(
            user_id=id,
            payload={
                **patch,
                **user_patch,
                "user_id": id,
                "full_name": user_patch.get("full_name") or existing.get("full_name"),
                "email": user_patch.get("email") or existing.get("email"),
                "phone": user_patch.get("phone") if "phone" in user_patch else existing.get("phone"),
                "status": user_patch.get("status") or existing.get("status"),
                "gender": user_patch.get("gender") if "gender" in user_patch else existing.get("gender"),
                "date_of_birth": user_patch.get("date_of_birth") if "date_of_birth" in user_patch else existing.get("date_of_birth"),
            },
        )

    u = await repo.get_by_id(id)
    assert u is not None
    return str_id(u)


@router.delete("/users/{id}")
async def delete_user(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: UsersRepo = Depends(UsersRepo),
):
    ok = await repo.delete_user(id)
    if not ok:
        http_error(404, "USER_NOT_FOUND", "User not found")
    return {"ok": True}
    if raw_phone and not phone:
        http_error(400, "INVALID_PHONE", "Please enter a valid 10-digit phone number")
