from fastapi import Depends
from datetime import datetime, timezone, date, timedelta
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, EmailStr, Field

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.errors import http_error
from app.repos.users import UsersRepo
from app.repos.patients import PatientsRepo
from app.repos.doctors import DoctorsRepo
from app.core.deps import get_current_user
from app.utils.phone import normalize_indian_phone

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class RegisterReq(BaseModel):
    # Match frontend fields
    firstName: str = Field(min_length=1, max_length=60)
    lastName: str = Field(min_length=1, max_length=60)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=20)
    # make `date` (non-optional) if you want backend-required
    dateOfBirth: str
    password: str = Field(min_length=8, max_length=128)
    # frontend has it; backend can validate if provided
    confirmPassword: Optional[str] = None
    accept_terms: bool = False

    # Optional extras (frontend may or may not send)
    role: Optional[str] = "patient"
    source: Optional[str] = "web"
    doctorProfile: dict | None = None
    patientProfile: dict | None = None


class LoginReq(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool | None = False
    type: str


class RefreshReq(BaseModel):
    refresh_token: str


class ForgotPasswordReq(BaseModel):
    email: EmailStr


class ResetPasswordReq(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
    confirmPassword: Optional[str] = None


class ChangePasswordReq(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirmPassword: Optional[str] = None


@router.post("/register")
async def register(
    payload: RegisterReq,
    users: UsersRepo = Depends(UsersRepo),
    patients: PatientsRepo = Depends(PatientsRepo),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
):
    # Terms
    if not payload.accept_terms:
        http_error(400, "TERMS_REQUIRED", "Terms must be accepted")

    # Optional confirmPassword check (frontend already checks, but good to enforce too)
    if payload.confirmPassword is not None and payload.password != payload.confirmPassword:
        http_error(400, "PASSWORD_MISMATCH", "Passwords do not match")

    email = payload.email.lower().strip()
    phone = normalize_indian_phone(payload.phone)
    if not phone:
        http_error(400, "INVALID_PHONE", "Please enter a valid 10-digit phone number")
    assert phone is not None
    first_name = payload.firstName.strip()
    last_name = payload.lastName.strip()
    full_name = f"{first_name} {last_name}".strip()

    # Uniqueness checks
    if await users.get_by_email(email):
        http_error(409, "EMAIL_EXISTS", "Email already registered")
    if await users.get_by_phone(str(phone)):
        http_error(409, "PHONE_EXISTS", "Phone already registered")

    role = (payload.role or "patient").lower().strip()
    if role not in {"patient", "doctor", "admin"}:
        http_error(400, "INVALID_ROLE", "role must be patient, doctor, or admin")

    patient_profile = payload.patientProfile or {}
    if patient_profile and not isinstance(patient_profile, dict):
        http_error(400, "INVALID_PROFILE", "patientProfile must be an object")

    normalized_gender = None
    normalized_date_of_birth = None
    if role == "patient":
        normalized_gender = patients._normalize_gender(patient_profile.get("gender")) if "gender" in patient_profile else None
        normalized_date_of_birth = patients._normalize_date_of_birth(
            patient_profile.get("date_of_birth") if "date_of_birth" in patient_profile else payload.dateOfBirth
        )
    else:
        normalized_date_of_birth = patients._normalize_date_of_birth(payload.dateOfBirth)

    user_doc = {
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "date_of_birth": normalized_date_of_birth,
        "gender": normalized_gender,
        "password_hash": hash_password(payload.password),
        "role": role,
        "status": "active",
        "created_at": datetime.now(timezone.utc),
        "source": payload.source or "web",
    }

    created = await users.create_user(user_doc)
    user_id = str(created["_id"])

    access = create_access_token(user_id, created["role"])
    refresh = create_refresh_token(user_id, created["role"])
    await users.save_refresh_token(user_id, refresh)

    if role == "patient":
        profile = patient_profile
        await patients.create_patient({
            "user_id": user_id,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "date_of_birth": normalized_date_of_birth,
            "gender": normalized_gender,
            **profile,
        })

    if role == "doctor":
        profile = payload.doctorProfile or {}
        if not isinstance(profile, dict):
            http_error(400, "INVALID_PROFILE", "doctorProfile must be an object")
        await doctors.create({
            "user_id": user_id,
            "name": full_name,
            "email": email,
            "phone": phone,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            **profile,
        })

    return {
        "user": {
            "id": user_id,
            "role": created["role"],
            "full_name": created["full_name"],
            "email": created["email"],
            "phone": created["phone"],
            "status": created["status"],
            "must_change_password": bool(created.get("must_change_password")),
        },
        "tokens": {"access_token": access, "refresh_token": refresh},
        "meta": {"welcome_message": "Registration successful."},
    }


@router.post("/login")
async def login(payload: LoginReq, users: UsersRepo = Depends(UsersRepo)):
    user = await users.get_by_email(payload.email.lower().strip())

    req_role = (getattr(payload, "role", None) or getattr(
        payload, "type", None) or "").lower().strip()

    db_role = (user.get("role") or user.get("type") or "").lower().strip()

    # print(req_role, user)
    if not req_role:
        http_error(400, "ROLE_REQUIRED", "Role is required")

    if req_role != db_role:
        http_error(403, "ROLE_MISMATCH", "Invalid role for this account")

    if not user:
        http_error(401, "INVALID_CREDENTIALS", "Invalid email or password")

    if user.get("status") != "active":
        http_error(423, "USER_DISABLED", "User is disabled")

    if not verify_password(payload.password, user.get("password_hash", "")):
        http_error(401, "INVALID_CREDENTIALS", "Invalid email or password")

    user_id = str(user["_id"])
    access = create_access_token(user_id, user["role"])
    refresh = create_refresh_token(user_id, user["role"])
    await users.save_refresh_token(user_id, refresh)

    return {
        "user": {
            "id": user_id,
            "role": user["role"],
            "full_name": user.get("full_name", ""),
            "email": user["email"],
            "phone": user.get("phone"),
            "status": user["status"],
            "must_change_password": bool(user.get("must_change_password")),
        },
        "tokens": {"access_token": access, "refresh_token": refresh},
        "meta": {"last_login_at": datetime.now(timezone.utc).astimezone().isoformat()},
    }


@router.post("/logout")
async def logout(
    refresh_token: str = Body(..., embed=True),
    _user=Depends(get_current_user),
    users: UsersRepo = Depends(UsersRepo),
):
    await users.revoke_refresh_token(refresh_token)
    return {"message": "Logged out."}


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordReq, users: UsersRepo = Depends(UsersRepo)):
    user = await users.get_by_email(payload.email.lower().strip())
    if user and user.get("status") == "active":
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await users.set_reset_token(str(user["_id"]), token, expires_at)

        # TODO: send email with reset link containing token
        return {"message": "Password reset link sent.", "reset_token": token}

    return {"message": "Password reset link sent."}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordReq, users: UsersRepo = Depends(UsersRepo)):
    if payload.confirmPassword is not None and payload.password != payload.confirmPassword:
        http_error(400, "PASSWORD_MISMATCH", "Passwords do not match")

    user = await users.get_by_reset_token(payload.token)
    if not user:
        http_error(400, "INVALID_TOKEN", "Invalid or expired token")

    expires_at = user.get("reset_token_expires_at")
    if not expires_at or expires_at < datetime.now(timezone.utc):
        http_error(400, "INVALID_TOKEN", "Invalid or expired token")

    await users.update_password(str(user["_id"]), hash_password(payload.password))
    await users.clear_reset_token(str(user["_id"]))

    return {"message": "Password updated."}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordReq,
    user=Depends(get_current_user),
    users: UsersRepo = Depends(UsersRepo),
):
    if payload.confirmPassword is not None and payload.new_password != payload.confirmPassword:
        http_error(400, "PASSWORD_MISMATCH", "Passwords do not match")

    if not verify_password(payload.current_password, user.get("password_hash", "")):
        http_error(401, "INVALID_CREDENTIALS", "Invalid current password")

    await users.update_password(str(user["_id"]), hash_password(payload.new_password))
    return {"message": "Password updated."}


@router.post("/refresh")
async def refresh(payload: RefreshReq, users: UsersRepo = Depends(UsersRepo)):
    token_data: dict = {}
    try:
        token_data = decode_token(payload.refresh_token)
    except Exception:
        http_error(401, "INVALID_TOKEN", "Invalid refresh token")

    if token_data.get("type") != "refresh":
        http_error(401, "INVALID_TOKEN", "Invalid refresh token")

    user_id_raw = token_data.get("sub")
    if not isinstance(user_id_raw, str) or not user_id_raw:
        http_error(401, "INVALID_TOKEN", "Invalid refresh token")
    user_id = str(user_id_raw)

    stored = await users.get_refresh_token(payload.refresh_token)
    if not stored or stored.get("user_id") != user_id:
        http_error(401, "INVALID_TOKEN", "Invalid refresh token")

    user = await users.get_by_id(user_id)
    if not user:
        http_error(401, "INVALID_TOKEN", "Invalid refresh token")
    if user.get("status") != "active":
        http_error(423, "USER_DISABLED", "User is disabled")

    access = create_access_token(user_id, user["role"])
    refresh = create_refresh_token(user_id, user["role"])
    await users.revoke_refresh_token(payload.refresh_token)
    await users.save_refresh_token(user_id, refresh)

    return {"tokens": {"access_token": access, "refresh_token": refresh}}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {
        "id": str(user["_id"]),
        "role": user["role"],
        "status": user["status"],
        "full_name": user.get("full_name", ""),
        "email": user["email"],
        "phone": user.get("phone"),
        "must_change_password": bool(user.get("must_change_password")),
        "date_of_birth": user.get("date_of_birth"),
        "gender": user.get("gender"),
        "image": user.get("image"),
        "created_at": user.get("created_at").isoformat() if user.get("created_at") else None,
    }


@router.patch("/me")
async def update_me(
    payload: dict,
    user=Depends(get_current_user),
    users: UsersRepo = Depends(UsersRepo),
    patients: PatientsRepo = Depends(PatientsRepo),
):
    user_id = str(user["_id"])
    existing = await users.get_by_id(user_id)
    if not existing:
        http_error(404, "USER_NOT_FOUND", "User not found")

    patch = dict(payload or {})
    user_patch: dict = {}

    if "full_name" in patch or "name" in patch:
        user_patch["full_name"] = str(patch.get("full_name") or patch.get("name") or "").strip() or None
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
    if "image" in patch:
        user_patch["image"] = patch.get("image")

    email_value = user_patch.get("email")
    if isinstance(email_value, str) and email_value and email_value != existing.get("email"):
        email_owner = await users.get_by_email(email_value)
        if email_owner and str(email_owner.get("_id")) != user_id:
            http_error(409, "EMAIL_EXISTS", "A user with this email already exists")

    phone_value = user_patch.get("phone")
    if isinstance(phone_value, str) and phone_value and phone_value != existing.get("phone"):
        phone_owner = await users.get_by_phone(str(phone_value))
        if phone_owner and str(phone_owner.get("_id")) != user_id:
            http_error(409, "PHONE_EXISTS", "A user with this phone already exists")

    if user_patch:
        user_patch["updated_at"] = datetime.now(timezone.utc)
        await users.col.update_one({"_id": existing["_id"]}, {"$set": user_patch})

    role = str(existing.get("role") or user.get("role") or "")
    if role == "patient":
        await patients.ensure_patient_profile(
            user_id=user_id,
            payload={
                **patch,
                **user_patch,
                "user_id": user_id,
                "full_name": user_patch.get("full_name") or existing.get("full_name"),
                "email": user_patch.get("email") or existing.get("email"),
                "phone": user_patch.get("phone") if "phone" in user_patch else existing.get("phone"),
                "status": existing.get("status"),
                "gender": user_patch.get("gender") if "gender" in user_patch else existing.get("gender"),
                "date_of_birth": user_patch.get("date_of_birth") if "date_of_birth" in user_patch else existing.get("date_of_birth"),
            },
        )

    updated = await users.get_by_id(user_id)
    assert updated is not None
    return {
        "id": str(updated["_id"]),
        "role": updated.get("role"),
        "status": updated.get("status"),
        "full_name": updated.get("full_name", ""),
        "email": updated.get("email"),
        "phone": updated.get("phone"),
        "date_of_birth": updated.get("date_of_birth"),
        "gender": updated.get("gender"),
        "image": updated.get("image"),
        "created_at": updated.get("created_at").isoformat() if updated.get("created_at") else None,
    }
