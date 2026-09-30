from datetime import datetime, timezone
from fastapi import Depends
from app.core.db import get_db

class SettingsRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["settings"]

    async def get(self):
        doc = await self.col.find_one({"key": "platform"})
        if not doc:
            return {"key": "platform", "booking_window_days": 30, "working_hours": {"start": 9, "end": 22}, "flags": {}}
        doc.pop("_id", None)
        return doc

    async def update(self, payload: dict):
        payload = {
            "key": "platform",
            **payload,
            "updated_at": datetime.now(timezone.utc),
        }
        await self.col.update_one({"key": "platform"}, {"$set": payload}, upsert=True)
        return await self.get()
