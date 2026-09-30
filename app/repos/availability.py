from datetime import datetime, timezone

from fastapi import Depends

from app.core.db import get_db


class AvailabilityRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["availability_slots"]
        self.weekly = db["availability_weekly"]

    async def get_slots(self, doctor_id: str, date: str):
        doc = await self.col.find_one({"doctor_id": doctor_id, "date": date})
        if not doc:
            return None
        return {
            "doctor_id": doc.get("doctor_id"),
            "date": doc.get("date"),
            "timezone": doc.get("timezone"),
            "slots": doc.get("slots") or [],
        }

    async def upsert_slots(self, doctor_id: str, date: str, timezone_label: str | None, slots: list[dict]):
        now = datetime.now(timezone.utc)
        await self.col.update_one(
            {"doctor_id": doctor_id, "date": date},
            {
                "$set": {
                    "timezone": timezone_label,
                    "slots": slots,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return await self.get_slots(doctor_id, date)

    async def get_weekly(self, doctor_id: str):
        doc = await self.weekly.find_one({"doctor_id": doctor_id})
        if not doc:
            return None
        return {
            "doctor_id": doc.get("doctor_id"),
            "timezone": doc.get("timezone"),
            "days": doc.get("days") or [],
        }

    async def upsert_weekly(self, doctor_id: str, timezone_label: str | None, days: list[dict]):
        now = datetime.now(timezone.utc)
        await self.weekly.update_one(
            {"doctor_id": doctor_id},
            {
                "$set": {
                    "timezone": timezone_label,
                    "days": days,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return await self.get_weekly(doctor_id)
