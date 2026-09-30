from datetime import datetime, timezone

from fastapi import Depends

from app.core.db import get_db
from app.core.errors import http_error
from app.utils.bson import oid, str_id


class ConsultationsRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["consultation_requests"]

    async def create_request(self, payload: dict):
        source = str(payload.get("source") or "web").strip().lower() or "web"
        consultation_type = payload.get("consultation_type")

        required = [
            "full_name",
            "phone",
            "email",
        ]
        if consultation_type:
            required.append("consultation_type")
        if source not in {"contact", "quotation", "support"}:
            required.extend(["consultation_type", "preferred_date", "preferred_time"])

        missing = [k for k in required if not payload.get(k)]
        if missing:
            http_error(400, "VALIDATION_ERROR", f"Missing fields: {', '.join(missing)}")

        preferred_date = payload.get("preferred_date") or datetime.now(timezone.utc).date().isoformat()
        preferred_time = payload.get("preferred_time") or "09:00"
        resolved_type = consultation_type or ("support" if source == "contact" else source or "general")

        doc = {
            "full_name": payload.get("full_name"),
            "phone": payload.get("phone"),
            "email": (payload.get("email") or "").lower(),
            "consultation_type": resolved_type,
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "subject": payload.get("subject"),
            "message": payload.get("message"),
            "source": source,
            "status": "new",
            "created_at": datetime.now(timezone.utc),
        }
        res = await self.col.insert_one(doc)
        doc["_id"] = res.inserted_id
        doc = str_id(doc)
        consultation_id = doc.get("id") or doc.get("_id")
        return {
            "consultation": {
                "id": consultation_id,
                "full_name": doc.get("full_name"),
                "phone": doc.get("phone"),
                "email": doc.get("email"),
                "consultation_type": doc.get("consultation_type"),
                "source": doc.get("source"),
                "preferred_date": doc.get("preferred_date"),
                "preferred_time": doc.get("preferred_time"),
                "status": doc.get("status"),
                "created_at": doc.get("created_at").astimezone().isoformat(),
            },
            "message": "Thank you. Our team will contact you.",
        }

    async def admin_list(
        self,
        status: str | None,
        consultation_type: str | None,
        date_from: str | None,
        date_to: str | None,
        page: int,
        page_size: int,
    ):
        q: dict = {}
        if status:
            q["status"] = status
        if consultation_type:
            q["consultation_type"] = consultation_type
        if date_from or date_to:
            band: dict = {}
            if date_from:
                band["$gte"] = date_from
            if date_to:
                band["$lte"] = date_to
            q["preferred_date"] = band

        cur = self.col.find(q).skip((page - 1) * page_size).limit(page_size).sort([("created_at", -1), ("_id", -1)])
        items = []
        async for c in cur:
            c = str_id(c)
            items.append(c)
        total = await self.col.count_documents(q)
        return items, total

    async def admin_get(self, request_id: str):
        doc = await self.col.find_one({"_id": oid(request_id)})
        return str_id(doc) if doc else None
