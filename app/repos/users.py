from datetime import datetime, timezone
from fastapi import Depends
from app.core.db import get_db
from app.utils.bson import oid
from app.utils.phone import normalize_indian_phone

class UsersRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["users"]
        self.tokens = db["auth_tokens"]

    async def get_by_email(self, email: str):
        return await self.col.find_one({"email": email.lower()})

    async def get_by_phone(self, phone: str):
        normalized_phone = normalize_indian_phone(phone)
        if normalized_phone:
            return await self.col.find_one({"phone": normalized_phone})
        return await self.col.find_one({"phone": phone})

    async def get_by_id(self, user_id: str):
        return await self.col.find_one({"_id": oid(user_id)})

    async def create_user(self, doc: dict) -> dict:
        res = await self.col.insert_one(doc)
        doc["_id"] = res.inserted_id
        return doc

    async def set_reset_token(self, user_id: str, token: str, expires_at: datetime):
        await self.col.update_one(
            {"_id": oid(user_id)},
            {"$set": {"reset_token": token, "reset_token_expires_at": expires_at}},
        )

    async def get_by_reset_token(self, token: str):
        return await self.col.find_one({"reset_token": token})

    async def clear_reset_token(self, user_id: str):
        await self.col.update_one(
            {"_id": oid(user_id)},
            {"$unset": {"reset_token": "", "reset_token_expires_at": ""}},
        )

    async def update_password(self, user_id: str, password_hash: str):
        await self.col.update_one(
            {"_id": oid(user_id)},
            {"$set": {"password_hash": password_hash, "updated_at": datetime.now(timezone.utc), "must_change_password": False}},
        )

    async def update_doctor_login_profile(self, user_id: str, *, full_name: str, email: str, phone: str | None, status: str | None = None):
        patch = {
            "full_name": full_name,
            "email": email.lower(),
            "phone": phone,
            "role": "doctor",
            "updated_at": datetime.now(timezone.utc),
        }
        if status is not None:
            patch["status"] = status
        await self.col.update_one({"_id": oid(user_id)}, {"$set": patch})

    async def list_users(self, role: str | None, status: str | None, page: int, page_size: int):
        q = {}
        if role:
            q["role"] = role
        if status:
            q["status"] = status
        cur = self.col.find(q).skip((page-1)*page_size).limit(page_size).sort([("created_at", -1), ("_id", -1)])
        items = []
        async for u in cur:
            items.append({
                "id": str(u["_id"]),
                "role": u.get("role"),
                "status": u.get("status"),
                "full_name": u.get("full_name"),
                "email": u.get("email"),
                "phone": u.get("phone"),
                "city": u.get("city"),
                "location": u.get("location"),
                "specialty": u.get("specialty"),
                "hospital": u.get("hospital"),
                "source": u.get("source"),
                "created_at": u.get("created_at").isoformat() if u.get("created_at") else None,
            })
        total = await self.col.count_documents(q)
        return items, total

    async def update_user(self, user_id: str, patch: dict):
        allowed = {}
        for k in ("role", "status", "full_name", "phone"):
            if k in patch:
                allowed[k] = patch[k]
        await self.col.update_one({"_id": oid(user_id)}, {"$set": allowed})
        return await self.get_by_id(user_id)

    async def delete_user(self, user_id: str) -> bool:
        res = await self.col.delete_one({"_id": oid(user_id)})
        return res.deleted_count == 1

    async def save_refresh_token(self, user_id: str, refresh_token: str):
        await self.tokens.insert_one({"user_id": user_id, "refresh_token": refresh_token, "created_at": datetime.now(timezone.utc)})

    async def get_refresh_token(self, refresh_token: str):
        return await self.tokens.find_one({"refresh_token": refresh_token})

    async def revoke_refresh_token(self, refresh_token: str):
        await self.tokens.delete_one({"refresh_token": refresh_token})
