from datetime import datetime, timezone
from fastapi import Depends
from app.core.db import get_db
from app.utils.bson import oid, str_id
from app.utils.location_normalizer import normalize_india_location

class InsuranceRepo:
    def __init__(self, db=Depends(get_db)):
        self.partners = db["insurance_partners"]
        self.leads = db["insurance_leads"]
        # Used by /api/insurance CRUD endpoints (frontend expects this collection)
        self.plans = db["insurance_plans"]

    # -----------------
    # Public insurance partners / leads
    # -----------------

    async def list_partners(self):
        cur = self.partners.find({}).sort("name", 1)
        return [
            {
                "id": str(d["_id"]),
                "name": d.get("name"),
                "logo_url": d.get("logo_url"),
                "city": d.get("city"),
                "state": d.get("state"),
                "country": d.get("country"),
            }
            async for d in cur
        ]

    async def create_partner(self, doc: dict):
        normalized_location = normalize_india_location(
            city=doc.get("city"),
            state=doc.get("state"),
            location=doc.get("location"),
            address=doc.get("address"),
            headquarters=doc.get("headquarters"),
            country=doc.get("country"),
        )
        if normalized_location.get("city"):
            doc["city"] = normalized_location["city"]
        if normalized_location.get("state"):
            doc["state"] = normalized_location["state"]
        if normalized_location.get("country"):
            doc["country"] = normalized_location["country"]

        res = await self.partners.insert_one(doc)
        doc["_id"] = res.inserted_id
        return doc

    async def update_partner(self, partner_id: str, doc: dict):
        normalized_location = normalize_india_location(
            city=doc.get("city"),
            state=doc.get("state"),
            location=doc.get("location"),
            address=doc.get("address"),
            headquarters=doc.get("headquarters"),
            country=doc.get("country"),
        )
        if normalized_location.get("city"):
            doc["city"] = normalized_location["city"]
        if normalized_location.get("state"):
            doc["state"] = normalized_location["state"]
        if normalized_location.get("country"):
            doc["country"] = normalized_location["country"]

        await self.partners.update_one({"_id": oid(partner_id)}, {"$set": doc})
        return await self.partners.find_one({"_id": oid(partner_id)})

    async def admin_list_partners(self, page: int, page_size: int):
        cur = self.partners.find({}).skip((page-1)*page_size).limit(page_size).sort([("updated_at", -1), ("_id", -1)])
        items = [str_id(x) async for x in cur]
        total = await self.partners.count_documents({})
        return items, total

    async def delete_partner(self, partner_id: str) -> bool:
        res = await self.partners.delete_one({"_id": oid(partner_id)})
        return res.deleted_count == 1

    async def create_lead(self, payload: dict):
        partner_id = payload.get("partner_id")
        if partner_id:
            p = await self.partners.find_one({"_id": oid(partner_id)})
            if not p:
                return None
        lead = {
            "partner_id": partner_id,
            "full_name": payload.get("full_name"),
            "email": (payload.get("email") or "").lower(),
            "phone": payload.get("phone"),
            "age": payload.get("age"),
            "gender": payload.get("gender"),
            "city": payload.get("city"),
            "preferred_date": payload.get("preferred_date"),
            "preferred_time": payload.get("preferred_time"),
            "notes": payload.get("notes"),
            "source": payload.get("source") or "web",
            "consent_to_contact": bool(payload.get("consent_to_contact", True)),
            "status": "new",
            "created_at": datetime.now(timezone.utc),
        }
        res = await self.leads.insert_one(lead)
        lead["_id"] = res.inserted_id
        lead = str_id(lead)
        return {
            "lead": {
                "id": lead["id"],
                "partner_id": lead.get("partner_id"),
                "full_name": lead.get("full_name"),
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "age": lead.get("age"),
                "gender": lead.get("gender"),
                "city": lead.get("city"),
                "preferred_date": lead.get("preferred_date"),
                "preferred_time": lead.get("preferred_time"),
                "status": lead.get("status"),
                "created_at": lead.get("created_at").astimezone().isoformat(),
            },
            "message": "Thank you. Our team will contact you.",
            "next_actions": {"email_sent": True},
        }

    async def admin_list_leads(self, partner_id: str | None, status: str | None, date_from: str | None, date_to: str | None, page: int, page_size: int):
        q = {}
        if partner_id:
            q["partner_id"] = partner_id
        if status:
            q["status"] = status
        cur = self.leads.find(q).skip((page-1)*page_size).limit(page_size).sort([("created_at", -1), ("_id", -1)])
        items = []
        async for l in cur:
            l = str_id(l)
            items.append(l)
        total = await self.leads.count_documents(q)
        return items, total

    async def admin_update_lead(self, lead_id: str, patch: dict):
        allowed = {}
        for k in ("status", "notes"):
            if k in patch:
                allowed[k] = patch[k]
        await self.leads.update_one({"_id": oid(lead_id)}, {"$set": allowed})
        return await self.leads.find_one({"_id": oid(lead_id)})

    async def delete_lead(self, lead_id: str) -> bool:
        res = await self.leads.delete_one({"_id": oid(lead_id)})
        return res.deleted_count == 1

    # -----------------
    # Insurance plans CRUD (used by frontend /api/insurance)
    # -----------------
    async def list_plans(self, q: str | None, page: int, page_size: int):
        query: dict = {}
        if q:
            query["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"provider": {"$regex": q, "$options": "i"}},
                {"type": {"$regex": q, "$options": "i"}},
            ]
        cur = (
            self.plans.find(query)
            .skip((page - 1) * page_size)
            .limit(page_size)
            .sort([("updated_at", -1), ("_id", -1)])
        )
        items = [str_id(x) async for x in cur]
        total = await self.plans.count_documents(query)
        return items, total

    async def get_plan(self, plan_id: str):
        return await self.plans.find_one({"_id": oid(plan_id)})

    async def create_plan(self, payload: dict):
        doc = {
            **payload,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        res = await self.plans.insert_one(doc)
        doc["_id"] = res.inserted_id
        return str_id(doc)

    async def update_plan(self, plan_id: str, payload: dict):
        payload = {**payload, "updated_at": datetime.now(timezone.utc)}
        await self.plans.update_one({"_id": oid(plan_id)}, {"$set": payload})
        doc = await self.get_plan(plan_id)
        return str_id(doc) if doc else None

    async def delete_plan(self, plan_id: str) -> bool:
        res = await self.plans.delete_one({"_id": oid(plan_id)})
        return res.deleted_count == 1
