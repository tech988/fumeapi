import re

from fastapi import Depends
from app.core.db import get_db
from app.utils.bson import oid, str_id
from app.utils.location_normalizer import canonical_city, normalize_india_location


def _as_list(v):
    return v if isinstance(v, list) else []


def _looks_like_objectid(s: str) -> bool:
    return isinstance(s, str) and len(s) == 24 and all(c in "0123456789abcdefABCDEF" for c in s)


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


def _hospital_dedupe_key(doc: dict) -> str:
    slug = str((doc or {}).get("slug") or "").strip().lower()
    if slug:
        return f"slug:{slug}"

    name = str((doc or {}).get("name") or "").strip().lower()
    location = str((doc or {}).get("location") or (doc or {}).get("city") or "").strip().lower()
    if name or location:
        return f"name:{name}|location:{location}"

    raw_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip().lower()
    return f"id:{raw_id}"


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


def _get_field(doc: dict, *names):
    for name in names:
        if name in doc and doc.get(name) is not None:
            return doc.get(name)
    return None


def _normalize_hospital_output(doc: dict) -> dict:
    if not doc:
        return doc

    mapped = dict(doc)

    established = _get_field(mapped, "established", "established_year", "founded_year", "yearEstablished", "year_established")
    if established is not None:
        mapped["established"] = established
        mapped["established_year"] = established

    bed_count = _get_field(mapped, "bedCount", "bed_count", "beds")
    if bed_count is not None:
        mapped["bedCount"] = bed_count
        mapped["bed_count"] = bed_count

    field_map = {
        "created_at": "createdAt",
        "updated_at": "updatedAt",
        "review_count": "reviewCount",
        "insurance_partners": "insurancePartners",
        "emergency_services": "emergencyServices",
        "is_verified": "verified",
        "website_url": "website",
        "contact_phone": "phone",
        "contact_email": "email",
        "facility_list": "facilities",
        "doctor_list": "doctors",
    }

    for src, dest in field_map.items():
        if src in mapped and dest not in mapped:
            mapped[dest] = mapped.get(src)

    return mapped


def _normalize_hospital_input(doc: dict) -> dict:
    if not doc:
        return doc

    mapped = dict(doc)

    established = _get_field(mapped, "established", "established_year", "founded_year", "yearEstablished", "year_established")
    if established is not None:
        mapped["established"] = established

    bed_count = _get_field(mapped, "bedCount", "bed_count", "beds")
    if bed_count is not None:
        mapped["bedCount"] = bed_count

    field_map = {
        "created_at": "createdAt",
        "updated_at": "updatedAt",
        "review_count": "reviewCount",
        "insurance_partners": "insurancePartners",
        "emergency_services": "emergencyServices",
        "is_verified": "verified",
        "website_url": "website",
        "contact_phone": "phone",
        "contact_email": "email",
        "facility_list": "facilities",
        "doctor_list": "doctors",
    }

    for src, dest in field_map.items():
        if src in mapped and dest not in mapped:
            mapped[dest] = mapped.get(src)

    if "created_at" in mapped:
        mapped["createdAt"] = mapped.get("created_at")
    if "updated_at" in mapped:
        mapped["updatedAt"] = mapped.get("updated_at")

    return mapped


class HospitalsRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["hospitals"]
        self.packages = db["packages"]

    def _hospital_match_clauses(self, hospital_ref: str) -> list[dict]:
        clauses: list[dict] = [{"_id": hospital_ref}]
        if _looks_like_objectid(hospital_ref):
            try:
                clauses.append({"_id": oid(hospital_ref)})
            except Exception:
                pass
        return clauses

    async def _sync_package_snapshots(self, hospital_doc: dict | None):
        if not hospital_doc:
            return

        hospital = _normalize_hospital_output(str_id(hospital_doc))
        hospital_id = str(hospital.get("id") or hospital.get("_id") or "")
        if not hospital_id:
            return

        name = hospital.get("name")
        location = hospital.get("location") or hospital.get("city")

        cursor = self.packages.find(
            {
                "hospitals": {
                    "$elemMatch": {
                        "$or": [
                            {"hospitalId": hospital_id},
                            {"id": hospital_id},
                            {"_id": hospital_id},
                            {"hospital_id": hospital_id},
                        ]
                    }
                }
            },
            {"hospitals": 1},
        )

        async for package in cursor:
            hospitals = _as_list(package.get("hospitals"))
            changed = False
            updated_hospitals = []
            for item in hospitals:
                if not isinstance(item, dict):
                    updated_hospitals.append(item)
                    continue

                item_id = item.get("hospitalId") or item.get("id") or item.get("_id") or item.get("hospital_id")
                if str(item_id or "") != hospital_id:
                    updated_hospitals.append(item)
                    continue

                next_item = dict(item)
                next_item["hospitalId"] = hospital_id
                if name:
                    next_item["name"] = name
                if location:
                    next_item["location"] = location
                    next_item["city"] = hospital.get("city") or location
                updated_hospitals.append(next_item)
                changed = True

            if changed:
                await self.packages.update_one({"_id": package.get("_id")}, {"$set": {"hospitals": updated_hospitals}})

    async def _list_unique_docs(self, q: dict, sort_fields: list[tuple[str, int]]):
        cur = self.col.find(q).sort(sort_fields)
        items = []
        seen: set[str] = set()
        async for hospital in cur:
            key = _hospital_dedupe_key(hospital)
            if key in seen:
                continue
            seen.add(key)
            items.append(hospital)
        return items

    async def _ensure_unique_slug(self, base: str) -> str | None:
        if not base:
            return None
        slug = base
        suffix = 2
        while await self.col.find_one({"slug": slug}, {"_id": 1}):
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    async def list_hospitals(
        self,
        search=None,
        city_id=None,         # keeping param for API compatibility
        specialty_ids=None,   # keeping param for API compatibility
        page=1,
        page_size=20,
        sort=None,
    ):
        q = {}

        # ✅ search by name/location
        if search:
            q["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"location": {"$regex": search, "$options": "i"}},
            ]

        # ✅ your DB uses "location" string (e.g. "Delhi")
        if city_id:
            city_value = canonical_city(city_id) or str(city_id).strip()
            city_clause = {
                "$or": [
                    {"city": {"$regex": f"^{city_value}$", "$options": "i"}},
                    {"location": {"$regex": f"^{city_value}$", "$options": "i"}},
                ]
            }
            _add_and(q, city_clause)

        # ✅ your DB uses "specialties": ["Cardiology", ...]
        if specialty_ids:
            if not isinstance(specialty_ids, list):
                specialty_ids = [specialty_ids]
            q["specialties"] = {"$all": specialty_ids}

        # ✅ sorting mapped to your schema
        if sort == "rating_desc":
            sort_fields = [("rating", -1), ("name", 1), ("_id", 1)]
        elif sort == "rating_asc":
            sort_fields = [("rating", 1), ("name", 1), ("_id", 1)]
        else:
            sort_fields = [("updated_at", -1), ("updatedAt", -1), ("name", 1), ("_id", 1)]

        unique_docs = await self._list_unique_docs(q, sort_fields)
        total = len(unique_docs)
        start = max(page - 1, 0) * page_size
        end = start + page_size
        page_docs = unique_docs[start:end]

        items = []
        for raw_hospital in page_docs:
            h = _normalize_hospital_output(str_id(raw_hospital))

            facilities = _as_list(h.get("facilities"))
            accreditation = _as_list(h.get("accreditation"))
            specialties = _as_list(h.get("specialties"))

            items.append({
                # could be "hosp_001" or ObjectId string after str_id()
                "id": h.get("_id"),
                "slug": h.get("slug"),
                "name": h.get("name"),
                "type": h.get("type"),
                "location": h.get("location"),
                "city": h.get("city"),
                "state": h.get("state"),
                "country": h.get("country"),
                "address": h.get("address"),
                "image": h.get("image"),
                "rating": h.get("rating"),
                "reviewCount": h.get("reviewCount"),

                "established": h.get("established"),
                "established_year": h.get("established"),
                "bedCount": h.get("bedCount"),
                "bed_count": h.get("bedCount"),

                # ✅ prevent frontend errors
                "accreditation": accreditation,
                "specialties": specialties,
                "facilities_summary": facilities[:6],

                # handy extras
                "phone": h.get("phone"),
                "email": h.get("email"),
                "website": h.get("website"),
            })

        return items, total

    # ----------------------------
    # 1) Slug-based getter (raw)
    # ----------------------------
    async def get_hospital_raw_by_slug(self, slug: str):
        if not slug:
            return None
        return await self.col.find_one({"slug": slug})

    # ----------------------------
    # 2) Slug-based getter (API)
    # ----------------------------
    async def get_hospital_by_slug(self, slug: str):
        h = await self.get_hospital_raw_by_slug(slug)
        return _normalize_hospital_output(str_id(h)) if h else None

    # ------------------------------------------------
    # 3) Backward compatible: slug OR _id (string/ObjectId)
    # ------------------------------------------------
    async def get_hospital_raw(self, hospital_ref: str):
        """
        hospital_ref can be:
          - slug (preferred)
          - _id string like "hosp_001"
          - Mongo ObjectId hex string (24 chars) if you migrate later
        """
        if not hospital_ref:
            return None

        # ✅ slug-first
        h = await self.col.find_one({"slug": hospital_ref})
        if h:
            return h

        # ✅ support current string _id like "hosp_001"
        h = await self.col.find_one({"_id": hospital_ref})
        if h:
            return h

        # ✅ optional: if you move to ObjectId later
        if _looks_like_objectid(hospital_ref):
            try:
                return await self.col.find_one({"_id": oid(hospital_ref)})
            except Exception:
                return None

        return None

    async def get_hospital(self, hospital_ref: str):
        h = await self.get_hospital_raw(hospital_ref)
        return str_id(h) if h else None

    # Keep old name for router compatibility
    async def get_hospital_detail(self, hospital_ref: str):
        return await self.get_hospital(hospital_ref)

    async def admin_list(self, search=None, city_id=None, page=1, page_size=20):
        q = {}
        if search:
            q["name"] = {"$regex": search, "$options": "i"}
        if city_id:
            city_value = canonical_city(city_id) or str(city_id).strip()
            city_clause = {
                "$or": [
                    {"city": {"$regex": f"^{city_value}$", "$options": "i"}},
                    {"location": {"$regex": f"^{city_value}$", "$options": "i"}},
                ]
            }
            _add_and(q, city_clause)

        unique_docs = await self._list_unique_docs(q, [("updated_at", -1), ("updatedAt", -1), ("name", 1), ("_id", 1)])
        total = len(unique_docs)
        start = max(page - 1, 0) * page_size
        end = start + page_size
        items = [_normalize_hospital_output(str_id(x)) for x in unique_docs[start:end]]
        return items, total

    async def create(self, doc: dict):
        doc = _normalize_hospital_input(doc)
        normalized_location = normalize_india_location(
            city=doc.get("city"),
            state=doc.get("state"),
            location=doc.get("location"),
            address=doc.get("address"),
            country=doc.get("country"),
        )
        if normalized_location.get("city"):
            doc["city"] = normalized_location["city"]
        if normalized_location.get("state"):
            doc["state"] = normalized_location["state"]
        if normalized_location.get("country"):
            doc["country"] = normalized_location["country"]

        raw_slug = (doc.get("slug") or "").strip()
        base = _slugify(raw_slug) if raw_slug else _slug_base(doc)
        if base:
            doc["slug"] = await self._ensure_unique_slug(base)
        res = await self.col.insert_one(doc)
        doc["_id"] = res.inserted_id
        await self._sync_package_snapshots(doc)
        return doc

    async def update(self, hospital_ref: str, doc: dict):
        """
        Update by slug (preferred) or by _id (string/ObjectId).
        """
        # try slug match
        q = {"slug": hospital_ref}

        # also allow matching current string _id ("hosp_001") or future ObjectId
        or_parts: list[dict] = [{"slug": hospital_ref}, {"_id": hospital_ref}]
        if _looks_like_objectid(hospital_ref):
            try:
                or_parts.append({"_id": oid(hospital_ref)})
            except Exception:
                pass

        doc = _normalize_hospital_input(doc)
        normalized_location = normalize_india_location(
            city=doc.get("city"),
            state=doc.get("state"),
            location=doc.get("location"),
            address=doc.get("address"),
            country=doc.get("country"),
        )
        if normalized_location.get("city"):
            doc["city"] = normalized_location["city"]
        if normalized_location.get("state"):
            doc["state"] = normalized_location["state"]
        if normalized_location.get("country"):
            doc["country"] = normalized_location["country"]

        await self.col.update_one({"$or": or_parts}, {"$set": doc})
        updated = await self.get_hospital_raw(hospital_ref)
        await self._sync_package_snapshots(updated)
        return updated

    async def delete(self, hospital_ref: str) -> bool:
        or_parts: list[dict] = [{"slug": hospital_ref}, {"_id": hospital_ref}]
        if _looks_like_objectid(hospital_ref):
            try:
                or_parts.append({"_id": oid(hospital_ref)})
            except Exception:
                pass
        res = await self.col.delete_one({"$or": or_parts})
        return res.deleted_count == 1
