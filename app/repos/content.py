from datetime import datetime, timezone

from fastapi import Depends

from app.core.db import get_db
from app.utils.bson import str_id


class ContentRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["content_pages"]

    async def get_public(self, key: str):
        doc = await self.col.find_one({"key": key})
        return str_id(doc) if doc else None

    async def get_admin(self, key: str):
        doc = await self.col.find_one({"key": key})
        return str_id(doc) if doc else None

    async def update(self, key: str, payload: dict):
        existing = await self.col.find_one({"key": key})
        doc = {
            **(existing or {}),
            **payload,
            "key": key,
            "updated_at": datetime.now(timezone.utc),
        }
        doc.pop("_id", None)
        await self.col.update_one({"key": key}, {"$set": doc}, upsert=True)
        return await self.get_admin(key)
