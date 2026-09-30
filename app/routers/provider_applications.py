import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.errors import http_error
from app.core.security import hash_password
from app.repos.doctors import DoctorsRepo
from app.repos.users import UsersRepo
from app.utils.phone import normalize_indian_phone

router = APIRouter(prefix="/api/provider-applications", tags=["Provider Applications"])


@router.post("")
async def create_provider_application(
    payload: dict,
    users: UsersRepo = Depends(UsersRepo),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
):
    full_name = str(payload.get("full_name") or payload.get("name") or "").strip()
    email = str(payload.get("email") or "").lower().strip()
    raw_phone = str(payload.get("phone") or payload.get("mobile") or "").strip()
    phone = normalize_indian_phone(raw_phone)
    role = str(payload.get("role") or "doctor").strip().lower()
    specialty = str(payload.get("specialty") or "").strip()
    hospital = str(payload.get("hospital") or payload.get("clinic") or "").strip()
    city = str(payload.get("city") or payload.get("location") or "").strip()
    message = str(payload.get("message") or "").strip()

    if role == "hospital":
        role = "hospital_admin"

    if role not in {"doctor", "hospital_admin"}:
        http_error(400, "INVALID_ROLE", "role must be doctor or hospital")
    if not full_name or not email or not raw_phone:
        http_error(400, "VALIDATION_ERROR", "full_name, email, and phone are required")
    if not phone:
        http_error(400, "INVALID_PHONE", "Please enter a valid 10-digit phone number")
    if await users.get_by_email(email):
        http_error(409, "EMAIL_EXISTS", "A user with this email already exists")
    if await users.get_by_phone(phone):
        http_error(409, "PHONE_EXISTS", "A user with this phone already exists")

    generated_password = secrets.token_urlsafe(24)
    created = await users.create_user(
        {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "password_hash": hash_password(generated_password),
            "role": role,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "source": "provider_application",
            "city": city or None,
            "location": city or None,
            "specialty": specialty or None,
            "hospital": hospital or None,
            "application_message": message or None,
        }
    )

    created_id = str(created.get("_id"))
    if role == "doctor":
        await doctors.create(
            {
                "user_id": created_id,
                "name": full_name,
                "specialty": specialty or None,
                "hospital": hospital or None,
                "location": city or None,
                "city": city or None,
                "about": message or None,
                "status": "pending",
                "verified": False,
                "phone": phone,
                "email": email,
                "experience": int(payload.get("experience") or 0) if str(payload.get("experience") or "").strip() else 0,
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
                "source": "provider_application",
            }
        )

    return {
        "message": "Application received.",
        "application": {
            "id": created_id,
            "role": role,
            "status": "pending",
            "full_name": full_name,
            "email": email,
            "phone": phone,
        },
    }
