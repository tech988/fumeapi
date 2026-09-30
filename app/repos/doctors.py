import re

from fastapi import Depends
from app.core.db import get_db
from app.utils.bson import oid, str_id
from app.utils.location_normalizer import canonical_city, normalize_india_location


def _as_list(v):
    return v if isinstance(v, list) else []


def _get_field(d: dict, *names):
    for name in names:
        if name in d:
            return d.get(name)
    return None


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _slug_base(doc: dict) -> str:
    name = (doc or {}).get("name") or ""
    location = (doc or {}).get("location") or ""
    if name and location:
        return _slugify(f"{name}-{location}")
    if name:
        return _slugify(name)
    return ""


def _looks_like_objectid(s: str) -> bool:
    # very lightweight check; oid() will still be the source of truth
    return isinstance(s, str) and len(s) == 24 and all(c in "0123456789abcdefABCDEF" for c in s)


def _add_and(q: dict, clause: dict) -> None:
    if "$and" in q:
        q["$and"].append(clause)
        return
    if q:
        existing = q.copy()
        q.clear()
        q["$and"] = [existing, clause]
        return
    q.update(clause)


def _normalize_doctor_output(doc: dict) -> dict:
    if not doc:
        return doc

    mapped = dict(doc)
    field_map = {
        "consultation_fee": "consultationFee",
        "consultation_types": "consultationTypes",
        "created_at": "createdAt",
        "updated_at": "updatedAt",
        "seeded_at": "seededAt",
        "sub_specialty": "subSpecialty",
        "review_count": "reviewCount",
        "affiliated_hospitals": "affiliatedHospitals",
    }

    for src, dest in field_map.items():
        if src in mapped and dest not in mapped:
            mapped[dest] = mapped.get(src)

    for src in field_map:
        if src in mapped:
            mapped.pop(src, None)

    return mapped


def _normalize_doctor_input(doc: dict) -> dict:
    if not doc:
        return doc

    mapped = dict(doc)
    field_map = {
        "consultation_fee": "consultationFee",
        "consultation_types": "consultationTypes",
        "created_at": "createdAt",
        "updated_at": "updatedAt",
        "seeded_at": "seededAt",
        "sub_specialty": "subSpecialty",
        "review_count": "reviewCount",
        "affiliated_hospitals": "affiliatedHospitals",
    }

    for src, dest in field_map.items():
        if src in mapped and dest not in mapped:
            mapped[dest] = mapped.get(src)
            mapped.pop(src, None)

    normalized_location = normalize_india_location(
        city=mapped.get("city"),
        state=mapped.get("state"),
        location=mapped.get("location"),
        address=mapped.get("address"),
        country=mapped.get("country"),
    )
    if normalized_location.get("city"):
        mapped["city"] = normalized_location["city"]
    if normalized_location.get("state"):
        mapped["state"] = normalized_location["state"]
    if normalized_location.get("country"):
        mapped["country"] = normalized_location["country"]

    return mapped


class DoctorsRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["doctors"]
        self.users = db["users"]
        self.hospitals = db["hospitals"]

    def _doctor_hospital_ids(self, doc: dict) -> list[str]:
        hospital_ids: list[str] = []
        for hospital in _as_list(doc.get("affiliatedHospitals")):
            if not isinstance(hospital, dict):
                continue
            hospital_id = hospital.get("hospitalId") or hospital.get("id") or hospital.get("hospital_id")
            if hospital_id:
                hospital_ids.append(str(hospital_id))
        return hospital_ids

    def _doctor_hospital_payload(self, doc: dict) -> dict:
        return {
            "id": str(doc.get("id") or doc.get("_id") or ""),
            "slug": doc.get("slug"),
            "name": doc.get("name"),
            "specialty": doc.get("specialty") or doc.get("specialty_label"),
            "location": doc.get("location") or doc.get("city"),
            "image": doc.get("image"),
        }

    async def _sync_hospital_backlinks(self, doc: dict, previous: dict | None = None):
        doctor_id = str(doc.get("id") or doc.get("_id") or "")
        if not doctor_id:
            return

        current_ids = set(self._doctor_hospital_ids(doc))
        previous_ids = set(self._doctor_hospital_ids(previous or {}))
        payload = self._doctor_hospital_payload(doc)

        for hospital_id in previous_ids - current_ids:
            clauses: list[dict[str, object]] = [{"_id": hospital_id}]
            if _looks_like_objectid(hospital_id):
                object_id_clause: dict[str, object] = {"_id": oid(hospital_id)}
                clauses.append(object_id_clause)
            await self.hospitals.update_many({"$or": clauses}, {"$pull": {"doctors": {"id": doctor_id}}})

        for hospital_id in current_ids:
            clauses: list[dict[str, object]] = [{"_id": hospital_id}]
            if _looks_like_objectid(hospital_id):
                object_id_clause: dict[str, object] = {"_id": oid(hospital_id)}
                clauses.append(object_id_clause)
            await self.hospitals.update_many({"$or": clauses}, {"$pull": {"doctors": {"id": doctor_id}}})
            await self.hospitals.update_many({"$or": clauses}, {"$addToSet": {"doctors": payload}})

    def _build_sort(self, sort: str | None):
        if sort == "experience_desc":
            return [("experience", -1), ("name", 1), ("_id", 1)]
        if sort == "experience_asc":
            return [("experience", 1), ("name", 1), ("_id", 1)]
        return [("updatedAt", -1), ("name", 1), ("_id", 1)]

    async def _ensure_unique_slug(self, base: str) -> str | None:
        if not base:
            return None
        slug = base
        suffix = 2
        while await self.col.find_one({"slug": slug}, {"_id": 1}):
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    async def list_doctors(
        self,
        search=None,
        specialty_id=None,   # keeping arg for API compatibility
        city_id=None,
        hospital_id=None,
        language_ids=None,   # can be list[str] OR a single str
        consultation_type=None,
        page=1,
        page_size=20,
        sort=None,
    ):
        q = {}

        # ✅ text search
        if search:
            q["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"specialty": {"$regex": search, "$options": "i"}},
                {"location": {"$regex": search, "$options": "i"}},
                {"languages": {"$regex": search, "$options": "i"}},
            ]

        # ✅ Your DB uses "specialty" (string), not specialty_id
        if specialty_id:
            q["specialty"] = {"$regex": f"^{specialty_id}$", "$options": "i"}

        # ✅ Your DB uses "location" string (e.g. "Delhi")
        if city_id:
            city_value = canonical_city(city_id) or str(city_id).strip()
            city_clause = {
                "$or": [
                    {"city": {"$regex": f"^{city_value}$", "$options": "i"}},
                    {"location": {"$regex": f"^{city_value}$", "$options": "i"}},
                ]
            }
            _add_and(q, city_clause)

        # ✅ Your DB has "affiliatedHospitals" array with {id,name,location}
        if hospital_id:
            hospital_clause: dict = {
                "$or": [
                    {"affiliatedHospitals.id": hospital_id},
                    {"affiliatedHospitals.hospitalId": hospital_id},
                ]
            }
            if _looks_like_objectid(hospital_id):
                try:
                    hospital_clause["$or"].extend(
                        [
                            {"affiliatedHospitals.id": oid(hospital_id)},
                            {"affiliatedHospitals.hospitalId": oid(hospital_id)},
                        ]
                    )
                except Exception:
                    pass
            _add_and(q, hospital_clause)

        # ✅ Your DB has "languages": ["English", "Hindi", ...]
        if language_ids:
            if not isinstance(language_ids, list):
                language_ids = [language_ids]
            q["languages"] = {"$all": language_ids}

        # ✅ consultation_type filter: check in "consultationTypes"
        if consultation_type:
            q["consultationTypes"] = {
                "$elemMatch": {"type": consultation_type, "available": True}
            }

        cursor = self.col.find(q).skip((page - 1) * page_size).limit(page_size)
        cursor = cursor.sort(self._build_sort(sort))

        items = []
        async for d in cursor:
            d = _normalize_doctor_output(str_id(d))

            # ✅ fees from your schema
            in_person_fee = _get_field(d, "consultationFee", "consultation_fee")
            video_fee = None
            phone_fee = None

            for ct in _as_list(_get_field(d, "consultationTypes", "consultation_types")):
                t = (ct.get("type") or "").lower()
                if t == "in-person":
                    in_person_fee = ct.get("fee", in_person_fee)
                elif t == "video":
                    video_fee = ct.get("fee")
                elif t == "phone":
                    phone_fee = ct.get("fee")

            items.append({
                # ✅ keep id for compatibility, but slug becomes primary for detail routes
                "id": d.get("_id"),
                "legacy_id": d.get("id"),
                "slug": d.get("slug"),

                "name": d.get("name"),
                "specialty_id": None,
                "specialty_label": d.get("specialty"),
                "experience_years": d.get("experience", 0),
                "languages": _as_list(d.get("languages")),
                "fee_in_person_paise": (in_person_fee * 100) if isinstance(in_person_fee, (int, float)) else None,
                "fee_video_paise": (video_fee * 100) if isinstance(video_fee, (int, float)) else None,
                "fee_phone_paise": (phone_fee * 100) if isinstance(phone_fee, (int, float)) else None,
                "hospitals": _as_list(_get_field(d, "affiliatedHospitals", "affiliated_hospitals")),
                "image": d.get("image"),
                "rating": d.get("rating"),
                "reviewCount": _get_field(d, "reviewCount", "review_count"),
                "city": d.get("city"),
                "state": d.get("state"),
                "country": d.get("country"),
                "location": d.get("location"),
                "qualification": d.get("qualification"),
                "verified": d.get("verified", False),
            })

        total = await self.col.count_documents(q)
        return items, total

    # ----------------------------
    # Slug-based getters (primary)
    # ----------------------------
    async def get_doctor_raw_by_slug(self, slug: str):
        if not slug:
            return None
        return await self.col.find_one({"slug": slug})

    async def get_doctor_by_slug(self, slug: str):
        d = await self.get_doctor_raw_by_slug(slug)
        return _normalize_doctor_output(str_id(d)) if d else None

    # -----------------------------------------
    # Backward compatible: accept slug OR _id
    # -----------------------------------------
    async def get_doctor_raw(self, doctor_ref: str):
        """
        doctor_ref can be:
          - slug (preferred)
          - Mongo _id string (24 hex chars) for legacy routes
        """
        if not doctor_ref:
            return None

        # try slug first (most common once you switch routes)
        d = await self.col.find_one({"slug": doctor_ref})
        if d:
            return d

        # fallback to ObjectId
        if _looks_like_objectid(doctor_ref):
            try:
                return await self.col.find_one({"_id": oid(doctor_ref)})
            except Exception:
                return None

        return None

    async def get_doctor(self, doctor_ref: str):
        d = await self.get_doctor_raw(doctor_ref)
        return _normalize_doctor_output(str_id(d)) if d else None

    async def get_doctor_by_user_id(self, user_id: str):
        if not user_id:
            return None

        clauses: list[dict[str, object]] = [{"user_id": user_id}, {"userId": user_id}]
        if _looks_like_objectid(user_id):
            object_id = oid(user_id)
            clauses.append({"user_id": object_id})
            clauses.append({"userId": object_id})

        d = await self.col.find_one({"$or": clauses})
        if d:
            return _normalize_doctor_output(str_id(d))

        user = None
        if _looks_like_objectid(user_id):
            try:
                user = await self.users.find_one({"_id": oid(user_id)})
            except Exception:
                user = None

        if user:
            fallback_or = []
            email = str(user.get("email") or "").strip().lower()
            phone = str(user.get("phone") or "").strip()
            full_name = str(user.get("full_name") or "").strip()
            if email:
                fallback_or.append({"email": email})
            if phone:
                fallback_or.append({"phone": phone})
            if full_name:
                fallback_or.append({"name": full_name})
            if fallback_or:
                d = await self.col.find_one({"$or": fallback_or})
        return _normalize_doctor_output(str_id(d)) if d else None

    async def admin_list(self, search=None, specialty_id=None, city_id=None, page=1, page_size=20):
        q = {}
        if search:
            q["name"] = {"$regex": search, "$options": "i"}

        if specialty_id:
            q["specialty"] = {"$regex": f"^{specialty_id}$", "$options": "i"}
        if city_id:
            city_value = canonical_city(city_id) or str(city_id).strip()
            city_clause = {
                "$or": [
                    {"city": {"$regex": f"^{city_value}$", "$options": "i"}},
                    {"location": {"$regex": f"^{city_value}$", "$options": "i"}},
                ]
            }
            _add_and(q, city_clause)

        cur = (
            self.col.find(q)
            .skip((page - 1) * page_size)
            .limit(page_size)
            .sort(self._build_sort(None))
        )

        items = []
        async for d in cur:
            items.append(_normalize_doctor_output(str_id(d)))

        total = await self.col.count_documents(q)
        return items, total

    async def create(self, doc: dict):
        normalized = _normalize_doctor_input(doc)
        raw_slug = (normalized.get("slug") or "").strip()
        base = _slugify(raw_slug) if raw_slug else _slug_base(normalized)
        if base:
            normalized["slug"] = await self._ensure_unique_slug(base)
        res = await self.col.insert_one(normalized)
        normalized["_id"] = res.inserted_id
        await self._sync_hospital_backlinks(str_id(normalized))
        return _normalize_doctor_output(str_id(normalized))

    async def update(self, doctor_ref: str, doc: dict):
        """
        Update by slug (preferred) or _id (legacy).
        """
        q = {"slug": doctor_ref}
        if _looks_like_objectid(doctor_ref):
            # If caller still passes _id, allow it
            q = {"$or": [{"slug": doctor_ref}, {"_id": oid(doctor_ref)}]}

        previous = await self.col.find_one(q)
        normalized = _normalize_doctor_input(doc)
        await self.col.update_one(q, {"$set": normalized})
        updated = await self.get_doctor_raw(doctor_ref)
        if updated:
            await self._sync_hospital_backlinks(str_id(updated), previous=str_id(previous) if previous else None)
        return _normalize_doctor_output(str_id(updated)) if updated else None

    async def delete(self, doctor_ref: str) -> bool:
        q = {"slug": doctor_ref}
        if _looks_like_objectid(doctor_ref):
            q = {"$or": [{"slug": doctor_ref}, {"_id": oid(doctor_ref)}]}
        res = await self.col.delete_one(q)
        return res.deleted_count == 1
