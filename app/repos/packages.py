import re

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorCollection

from app.core.db import get_db
from app.utils.bson import oid, str_id


def _as_list(v):
    return v if isinstance(v, list) else []


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _slug_base(doc: dict) -> str:
    name = (doc or {}).get("name") or (doc or {}).get("title") or ""
    city = (doc or {}).get("city") or ""
    if name and city:
        return _slugify(f"{name}-{city}")
    if name:
        return _slugify(name)
    return ""

def _looks_like_objectid(s: str) -> bool:
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


def normalize_id(package_id: str):
    # your _id is a string like pkg_001
    return package_id


def _primary_price_min(p: dict):
    pr = p.get("priceRange") or {}
    if isinstance(pr, dict) and pr.get("min") is not None:
        return pr.get("min")
    # checkup style fallback: prefer discountPrice if present else price
    if p.get("discountPrice") is not None:
        return p.get("discountPrice")
    return p.get("price")


def _primary_price_max(p: dict):
    pr = p.get("priceRange") or {}
    if isinstance(pr, dict) and pr.get("max") is not None:
        return pr.get("max")
    # fallback: for checkup-style, max is same as price
    if p.get("price") is not None:
        return p.get("price")
    return None


def _coerce_number(value):
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        raw = value.strip().replace(",", "")
        if not raw:
            return None
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return None
    return None


def _hospital_key(h: dict) -> str:
    hid = h.get("hospitalId") or h.get("hospital_id") or h.get("id") or h.get("_id")
    if hid is not None:
        return f"id:{str(hid)}"
    name = (h.get("name") or h.get("hospitalName") or "").strip().lower()
    location = (h.get("location") or h.get("city") or "").strip().lower()
    return f"name:{name}|location:{location}"


def _offer_to_hospital(offer: dict | None) -> dict:
    offer_data: dict = offer if isinstance(offer, dict) else {}

    hospital_info_raw = offer_data.get("hospital")
    hospital_info: dict = hospital_info_raw if isinstance(hospital_info_raw, dict) else {}

    hospital_id = (
        offer_data.get("hospitalId")
        or offer_data.get("hospital_id")
        or offer_data.get("id")
        or offer_data.get("_id")
        or hospital_info.get("hospitalId")
        or hospital_info.get("hospital_id")
        or hospital_info.get("id")
        or hospital_info.get("_id")
    )
    hospital_name = (
        offer_data.get("hospitalName")
        or offer_data.get("name")
        or hospital_info.get("name")
    )
    hospital_location = (
        offer_data.get("location")
        or offer_data.get("city")
        or hospital_info.get("location")
        or hospital_info.get("city")
    )

    direct_price = _coerce_number(
        offer_data.get("price")
        or offer_data.get("offerPrice")
        or offer_data.get("finalPrice")
        or offer_data.get("discountPrice")
        or offer_data.get("amount")
    )
    price_range = offer_data.get("priceRange")
    price_range = price_range if isinstance(price_range, dict) else {}

    price_min = _coerce_number(
        offer_data.get("priceMin")
        or offer_data.get("price_min")
        or price_range.get("min")
    )
    price_max = _coerce_number(
        offer_data.get("priceMax")
        or offer_data.get("price_max")
        or price_range.get("max")
    )

    if direct_price is not None and price_min is None:
        price_min = direct_price
    if direct_price is not None and price_max is None:
        price_max = direct_price
    if price_min is None and price_max is not None:
        price_min = price_max
    if price_max is None and price_min is not None:
        price_max = price_min

    hospital = {
        "hospitalId": hospital_id,
        "name": hospital_name,
        "location": hospital_location,
        "price": direct_price if direct_price is not None else price_min,
        "priceMin": price_min,
        "priceMax": price_max,
        "priceRange": {
            "min": price_min,
            "max": price_max,
        } if price_min is not None or price_max is not None else None,
    }

    if offer_data.get("roomType") is not None:
        hospital["roomType"] = offer_data.get("roomType")
    elif offer_data.get("room_type") is not None:
        hospital["roomType"] = offer_data.get("room_type")

    inclusions = _as_list(offer_data.get("inclusions"))
    exclusions = _as_list(offer_data.get("exclusions"))
    if inclusions:
        hospital["inclusions"] = inclusions
    if exclusions:
        hospital["exclusions"] = exclusions

    cost_breakdown = offer_data.get("costBreakdown") or offer_data.get("cost_breakdown")
    if isinstance(cost_breakdown, dict) and cost_breakdown:
        hospital["costBreakdown"] = cost_breakdown

    compact = {}
    for k, v in hospital.items():
        if v is not None and v != "":
            compact[k] = v
    return compact


def _merge_hospitals(existing: list[dict], derived: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []

    for item in existing:
        if not isinstance(item, dict):
            continue
        key = _hospital_key(item)
        merged[key] = dict(item)
        order.append(key)

    for item in derived:
        if not isinstance(item, dict):
            continue
        key = _hospital_key(item)
        base = merged.get(key, {})
        base.update(item)
        merged[key] = base
        if key not in order:
            order.append(key)

    return [merged[k] for k in order if k in merged]


def _doctor_key(doctor: dict) -> str:
    if not isinstance(doctor, dict):
        return ""
    for key in ("id", "_id", "slug"):
        value = doctor.get(key)
        if value:
            return f"{key}:{str(value).strip().lower()}"
    name = str(doctor.get("name") or "").strip().lower()
    return f"name:{name}" if name else ""


def _dedupe_doctors(doctors: list[dict]) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for doctor in doctors:
        if not isinstance(doctor, dict):
            continue
        key = _doctor_key(doctor)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        items.append(doctor)
    return items


def _package_specialty_hints(package_doc: dict) -> set[str]:
    text = " ".join(
        str(package_doc.get(field) or "")
        for field in ("name", "title", "category", "description", "specialty", "department")
    ).lower()

    hints: set[str] = set()
    specialty_rules = {
        "ent": ["ent", "ear", "nose", "throat", "adenoid", "tonsil", "sinus"],
        "gynecology": ["gynec", "gynaec", "uterus", "ovary", "breast", "pregnan", "fibroid"],
        "general surgery": ["surgery", "surgical", "excision", "laparoscopic", "hernia", "appendix"],
        "oncology": ["cancer", "tumor", "tumour", "oncology", "breast lump"],
        "orthopedics": ["ortho", "joint", "knee", "hip", "spine", "bone", "fracture"],
        "cardiology": ["heart", "cardio", "angioplasty", "bypass"],
        "neurology": ["neuro", "brain", "stroke", "spine"],
        "urology": ["uro", "kidney", "prostate", "bladder"],
        "gastroenterology": ["gastro", "liver", "stomach", "colon", "gallbladder"],
        "ophthalmology": ["eye", "retina", "cataract"],
    }

    for specialty, keywords in specialty_rules.items():
      if any(keyword in text for keyword in keywords):
          hints.add(specialty)

    return hints


def _doctor_matches_package_hints(doctor: dict, hints: set[str]) -> bool:
    if not hints:
        return True
    specialty_text = " ".join(
        str(doctor.get(field) or "") for field in ("specialty", "specialty_label", "department")
    ).lower()
    return any(hint in specialty_text for hint in hints)


def _compute_package_price_aggregates(hospitals: list[dict]) -> dict:
    mins = []
    maxs = []
    for h in hospitals:
        if not isinstance(h, dict):
            continue
        row = h if isinstance(h, dict) else {}
        pr_raw = row.get("priceRange")
        pr: dict = pr_raw if isinstance(pr_raw, dict) else {}
        h_min = _coerce_number(row.get("priceMin") or row.get("price_min") or pr.get("min") or row.get("price"))
        h_max = _coerce_number(row.get("priceMax") or row.get("price_max") or pr.get("max") or row.get("price"))
        if h_min is not None:
            mins.append(h_min)
        if h_max is not None:
            maxs.append(h_max)

    if not mins and not maxs:
        return {}

    agg_min = min(mins) if mins else min(maxs)
    agg_max = max(maxs) if maxs else max(mins)
    return {
        "priceRange": {"min": agg_min, "max": agg_max},
        "price": agg_min,
        "discountPrice": agg_min,
    }


def _normalize_package_write_doc(doc: dict, existing: dict | None = None) -> dict:
    normalized = dict(doc or {})
    existing_hospitals = _as_list((existing or {}).get("hospitals"))

    incoming_hospitals = _as_list(normalized.get("hospitals"))
    offer_rows = _as_list(normalized.get("offers"))
    offer_rows.extend(_as_list(normalized.get("hospitalOffers")))

    offers_derived = []
    for row in offer_rows:
        if isinstance(row, dict):
            converted = _offer_to_hospital(row)
            if converted:
                offers_derived.append(converted)

    if offers_derived:
        base_hospitals = incoming_hospitals if incoming_hospitals else existing_hospitals
        normalized["hospitals"] = _merge_hospitals(base_hospitals, offers_derived)
    elif incoming_hospitals:
        normalized["hospitals"] = incoming_hospitals

    hospitals_for_aggregate = _as_list(normalized.get("hospitals"))
    if hospitals_for_aggregate and ("offers" in normalized or "hospitalOffers" in normalized or "hospitals" in normalized):
        aggregates = _compute_package_price_aggregates(hospitals_for_aggregate)
        for k, v in aggregates.items():
            normalized[k] = v

    if "created_at" in normalized:
        normalized["createdAt"] = normalized.get("created_at")
    if "updated_at" in normalized:
        normalized["updatedAt"] = normalized.get("updated_at")

    return normalized


class PackagesRepo:
    def __init__(self, db=Depends(get_db)):
        self.col: AsyncIOMotorCollection = db["packages"]
        self.doctors: AsyncIOMotorCollection = db["doctors"]
        self.hospitals: AsyncIOMotorCollection = db["hospitals"]

    def _hospital_match_clauses(self, hospital_id: str) -> list[dict[str, object]]:
        clauses: list[dict[str, object]] = [{"_id": hospital_id}]
        if _looks_like_objectid(hospital_id):
            clauses.append({"_id": oid(hospital_id)})
        return clauses

    async def _get_canonical_hospital(self, hospital_id: str | None) -> dict | None:
        if not hospital_id:
            return None
        hospital = await self.hospitals.find_one({"$or": self._hospital_match_clauses(str(hospital_id))})
        return str_id(hospital) if hospital else None

    async def _canonicalize_package_hospitals(self, normalized: dict) -> dict:
        hospitals = _as_list(normalized.get("hospitals"))
        if not hospitals:
            return normalized

        canonicalized: list[dict] = []
        for hospital in hospitals:
            if not isinstance(hospital, dict):
                continue

            item = dict(hospital)
            hospital_id = item.get("hospitalId") or item.get("hospital_id") or item.get("id") or item.get("_id")
            canonical = await self._get_canonical_hospital(str(hospital_id)) if hospital_id else None
            if canonical:
                item["hospitalId"] = str(canonical.get("id") or canonical.get("_id") or hospital_id)
                if canonical.get("name"):
                    item["name"] = canonical.get("name")
                if canonical.get("location"):
                    item["location"] = canonical.get("location")
                elif canonical.get("city"):
                    item["location"] = canonical.get("city")
                if canonical.get("city") and not item.get("city"):
                    item["city"] = canonical.get("city")
            canonicalized.append(item)

        normalized["hospitals"] = canonicalized
        return normalized

    def _package_hospital_ids(self, package_doc: dict) -> list[str]:
        hospital_ids: list[str] = []
        for hospital in _as_list(package_doc.get("hospitals")):
            if not isinstance(hospital, dict):
                continue
            hospital_id = hospital.get("hospitalId") or hospital.get("id") or hospital.get("_id") or hospital.get("hospital_id")
            if hospital_id:
                hospital_ids.append(str(hospital_id))
        return hospital_ids

    def _package_hospital_payload(self, package_doc: dict) -> dict:
        return {
            "id": str(package_doc.get("id") or package_doc.get("_id") or ""),
            "slug": package_doc.get("slug"),
            "name": package_doc.get("name") or package_doc.get("title"),
            "priceMin": _primary_price_min(package_doc),
            "priceMax": _primary_price_max(package_doc),
            "inclusions": _as_list(package_doc.get("inclusions")),
            "exclusions": _as_list(package_doc.get("exclusions")),
        }

    async def _sync_hospital_backlinks(self, package_doc: dict, previous: dict | None = None):
        package_id = str(package_doc.get("id") or package_doc.get("_id") or "")
        if not package_id:
            return

        current_ids = set(self._package_hospital_ids(package_doc))
        previous_ids = set(self._package_hospital_ids(previous or {}))
        payload = self._package_hospital_payload(package_doc)

        for hospital_id in previous_ids - current_ids:
            clauses: list[dict[str, object]] = [{"_id": hospital_id}]
            if _looks_like_objectid(hospital_id):
                object_id_clause: dict[str, object] = {"_id": oid(hospital_id)}
                clauses.append(object_id_clause)
            await self.hospitals.update_many({"$or": clauses}, {"$pull": {"packages": {"id": package_id}}})

        for hospital_id in current_ids:
            clauses: list[dict[str, object]] = [{"_id": hospital_id}]
            if _looks_like_objectid(hospital_id):
                object_id_clause: dict[str, object] = {"_id": oid(hospital_id)}
                clauses.append(object_id_clause)
            await self.hospitals.update_many({"$or": clauses}, {"$pull": {"packages": {"id": package_id}}})
            await self.hospitals.update_many({"$or": clauses}, {"$addToSet": {"packages": payload}})

    async def _ensure_unique_slug(self, base: str) -> str | None:
        if not base:
            return None
        slug = base
        suffix = 2
        while await self.col.find_one({"slug": slug}, {"_id": 1}):
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    async def list_packages(
        self,
        search: str | None = None,
        city: str | None = None,
        hospital_id: str | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        page: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        category: str | None = None,   # optional but useful
    ):
        q: dict = {}

        # ✅ Search: name/slug/title/description
        if search:
            q["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"slug": {"$regex": search, "$options": "i"}},
                {"title": {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
            ]

        # ✅ City (doc has "city": "Delhi")
        if city:
            q["city"] = {"$regex": f"^{city}$", "$options": "i"}

        # ✅ Category
        if category:
            q["category"] = {"$regex": f"^{category}$", "$options": "i"}

        # ✅ Hospital filter: hospitals[].hospitalId
        if hospital_id:
            hospital_clause: dict = {"hospitals.hospitalId": hospital_id}
            if _looks_like_objectid(hospital_id):
                try:
                    hospital_clause = {
                        "$or": [
                            {"hospitals.hospitalId": hospital_id},
                            {"hospitals.hospitalId": oid(hospital_id)},
                        ]
                    }
                except Exception:
                    hospital_clause = {"hospitals.hospitalId": hospital_id}
            _add_and(q, hospital_clause)

        # ✅ Price filtering:
        # Support BOTH:
        # 1) surgery-like: priceRange.min/max
        # 2) checkup-like: price / discountPrice
        if price_min is not None or price_max is not None:
            band: dict = {}
            if price_min is not None:
                band["$gte"] = int(price_min)
            if price_max is not None:
                band["$lte"] = int(price_max)

            q["$and"] = q.get("$and", [])
            q["$and"].append(
                {
                    "$or": [
                        {"priceRange.min": band},
                        {"discountPrice": band},
                        {"price": band},
                    ]
                }
            )

        cur = self.col.find(q).skip((page - 1) * page_size).limit(page_size)

        # ✅ Sorting
        # Note: Mongo sort cannot easily "coalesce" fields.
        # We'll use reasonable defaults that work if fields exist.
        if sort == "price_asc":
            cur = cur.sort(
                [("priceRange.min", 1), ("discountPrice", 1), ("price", 1), ("_id", 1)])
        elif sort == "price_desc":
            cur = cur.sort(
                [("priceRange.min", -1), ("discountPrice", -1), ("price", -1), ("_id", -1)])
        elif sort == "popular":
            cur = cur.sort([("popularity", -1), ("_id", -1)])
        elif sort == "value":
            cur = cur.sort([("valueForMoney", -1), ("_id", -1)])
        else:
            cur = cur.sort([("updated_at", -1), ("updatedAt", -1), ("_id", -1)])

        items = []
        async for p in cur:
            p = str_id(p)

            hospitals_preview = _as_list(p.get("hospitals"))

            items.append(
                {
                    # ✅ stable id: prefer str_id-generated "id", else fallback to "_id"
                    "id": p.get("id") or p.get("_id"),
                    "slug": p.get("slug"),
                    "name": p.get("name") or p.get("title"),
                    "title": p.get("title"),
                    "category": p.get("category"),
                    "icon": p.get("icon"),
                    "city": p.get("city"),

                    "description": p.get("description"),
                    "duration": p.get("duration"),

                    "popularity": p.get("popularity", 0),
                    "valueForMoney": p.get("valueForMoney"),

                    # ✅ unified price fields for frontend cards
                    "priceRange": p.get("priceRange"),
                    "price_min": _primary_price_min(p),
                    "price_max": _primary_price_max(p),
                    "price": p.get("price"),
                    "discountPrice": p.get("discountPrice"),

                    # ✅ arrays must be arrays
                    "hospitals": hospitals_preview,
                    "available_at_count": len(_as_list(p.get("hospitals"))),
                    "insurancePartners": _as_list(p.get("insurancePartners")),
                    "includes": _as_list(p.get("includes")),
                    "inclusions": _as_list(p.get("inclusions")),
                    "exclusions": _as_list(p.get("exclusions")),
                }
            )

        total = await self.col.count_documents(q)
        return items, total

    async def get_package_detail(self, package_id_or_slug: str):
        """
        Supports both:
          - /packages/{_id} where _id="pkg_001"
          - /packages/{slug} where slug="knee-replacement-surgery"
        """
        pid = normalize_id(package_id_or_slug)

        p = await self.col.find_one({"_id": pid})
        if not p:
            p = await self.col.find_one({"slug": package_id_or_slug})
        if not p:
            return None

        p = str_id(p)

        return {
            "package": {
                "id": p.get("id") or p.get("_id"),
                "slug": p.get("slug"),
                "name": p.get("name") or p.get("title"),
                "title": p.get("title"),
                "category": p.get("category"),
                "icon": p.get("icon"),
                "description": p.get("description"),
                "duration": p.get("duration"),
                "city": p.get("city"),

                "priceRange": p.get("priceRange"),
                "price_min": _primary_price_min(p),
                "price_max": _primary_price_max(p),
                "price": p.get("price"),
                "discountPrice": p.get("discountPrice"),

                # ✅ arrays always arrays
                "includes": _as_list(p.get("includes")),
                "inclusions": _as_list(p.get("inclusions")),
                "exclusions": _as_list(p.get("exclusions")),
                "faqs": _as_list(p.get("faqs")),
                "insurancePartners": _as_list(p.get("insurancePartners")),
                "doctors": _as_list(p.get("doctors")),
            },
            "hospitals": _as_list(p.get("hospitals")),
            "meta": {
                "available_at_count": len(_as_list(p.get("hospitals"))),
                "updatedAt": p.get("updatedAt"),
                "createdAt": p.get("createdAt"),
            },
        }

    async def compare_offers(self, package_id_or_slug: str, hospital_ids: list[str]):
        p = await self.col.find_one({"_id": normalize_id(package_id_or_slug)})
        if not p:
            p = await self.col.find_one({"slug": package_id_or_slug})
        if not p:
            return None

        p = str_id(p)
        hospitals = _as_list(p.get("hospitals"))
        package_doctors = _as_list(p.get("doctors"))

        allowed_doctor_keys: set[str] = set()
        if package_doctors:
            for package_doctor in package_doctors:
                if isinstance(package_doctor, dict):
                    key = _doctor_key(str_id(package_doctor) if "_id" in package_doctor else package_doctor)
                    if key:
                        allowed_doctor_keys.add(key)
                elif package_doctor:
                    allowed_doctor_keys.add(f"name:{str(package_doctor).strip().lower()}")

        wanted = set([h for h in (hospital_ids or []) if h])
        package_hints = _package_specialty_hints(p)

        def _hospital_id(h: dict) -> str | None:
            return h.get("hospitalId") or h.get("id") or h.get("_id") or h.get("hospital_id")

        selected = []
        package_key = p.get("id") or p.get("_id") or package_id_or_slug

        wanted_indices = set()
        for token in wanted:
            if not isinstance(token, str):
                continue
            if "-hospital-" not in token:
                continue
            prefix, _, suffix = token.rpartition("-hospital-")
            if prefix not in {str(package_key), str(package_id_or_slug)}:
                continue
            if suffix.isdigit():
                wanted_indices.add(int(suffix))

        for idx, h in enumerate(hospitals):
            hid = _hospital_id(h)
            keys = set()
            if hid:
                keys.add(str(hid))
            keys.add(f"{package_key}-hospital-{idx}")
            keys.add(f"{package_id_or_slug}-hospital-{idx}")
            if keys & wanted or idx in wanted_indices:
                selected.append(h)

        selected_ids = [_hospital_id(h) for h in selected if _hospital_id(h)]
        selected_ids = [str(x) for x in selected_ids if x]
        selected_names = [
            (h.get("name") or h.get("hospitalName") or "").strip()
            for h in selected
        ]
        selected_names = [n for n in selected_names if n]
        selected_name_keys = {n.lower(): n for n in selected_names}

        oid_ids = []
        for hid in selected_ids:
            if _looks_like_objectid(hid):
                try:
                    oid_ids.append(oid(hid))
                except Exception:
                    pass

        doctor_map: dict[str, list[dict]] = {hid: [] for hid in selected_ids}
        doctor_name_map: dict[str, list[dict]] = {k: [] for k in selected_name_keys}
        if selected_ids or selected_names:
            match_ids = list(selected_ids)
            match_ids.extend(oid_ids)
            or_clauses = []
            if match_ids:
                or_clauses.extend(
                    [
                        {"affiliatedHospitals.hospitalId": {"$in": match_ids}},
                        {"affiliatedHospitals.id": {"$in": match_ids}},
                    ]
                )
            if selected_names:
                for name in selected_names:
                    pat = re.escape(name)
                    or_clauses.append({"affiliatedHospitals.name": {"$regex": pat, "$options": "i"}})
                    or_clauses.append({"hospital": {"$regex": pat, "$options": "i"}})
            q = {"$or": or_clauses} if or_clauses else {"_id": {"$exists": False}}
            cur = self.doctors.find(q)
            docs = await cur.to_list(length=None)
            for d in docs:
                d = str_id(d)
                affiliations = _as_list(d.get("affiliatedHospitals"))
                doctor_hospital_ids = []
                doctor_hospital_names = []
                for a in affiliations:
                    a_id = a.get("hospitalId") or a.get("id") or a.get("hospital_id")
                    if a_id:
                        doctor_hospital_ids.append(str(a_id))
                    a_name = (a.get("name") or "").strip()
                    if a_name:
                        doctor_hospital_names.append(a_name.lower())
                hospital_name = (d.get("hospital") or "").strip().lower()
                if hospital_name:
                    doctor_hospital_names.append(hospital_name)

                doctor_payload = {
                    "id": d.get("id") or d.get("_id"),
                    "slug": d.get("slug"),
                    "name": d.get("name"),
                    "specialty": d.get("specialty") or d.get("specialty_label"),
                    "experienceYears": d.get("experience") or d.get("experience_years"),
                    "rating": d.get("rating"),
                    "image": d.get("image"),
                }

                for hid in doctor_hospital_ids:
                    if hid in doctor_map:
                        doctor_map[hid].append(doctor_payload)
                for name_key in doctor_hospital_names:
                    if name_key in doctor_name_map:
                        doctor_name_map[name_key].append(doctor_payload)

        comparisons = []
        for h in selected:
            hid = _hospital_id(h)
            if not hid:
                continue
            price_range = h.get("priceRange") or {}
            name_key = (h.get("name") or h.get("hospitalName") or "").strip().lower()
            name_doctors = doctor_name_map.get(name_key, []) if name_key else []
            id_doctors = doctor_map.get(str(hid), [])
            resolved_doctors = id_doctors or name_doctors
            if allowed_doctor_keys:
                resolved_doctors = [doctor for doctor in resolved_doctors if _doctor_key(doctor) in allowed_doctor_keys]
            else:
                hinted_doctors = [doctor for doctor in resolved_doctors if _doctor_matches_package_hints(doctor, package_hints)]
                if hinted_doctors:
                    resolved_doctors = hinted_doctors
            comparisons.append({
                "id": hid,
                "hospitalId": str(hid),
                "name": h.get("hospitalName") or h.get("name"),
                "location": h.get("location") or h.get("city"),
                "priceMin": h.get("priceMin") or h.get("price_min") or price_range.get("min"),
                "priceMax": h.get("priceMax") or h.get("price_max") or price_range.get("max"),
                "roomType": h.get("roomType") or h.get("room_type"),
                "costBreakdown": h.get("costBreakdown") or h.get("cost_breakdown") or {},
                "inclusions": _as_list(h.get("inclusions")),
                "exclusions": _as_list(h.get("exclusions")),
                "doctors": _dedupe_doctors(resolved_doctors),
            })

        return {
            "package": {
                "id": p.get("id") or p.get("_id"),
                "slug": p.get("slug"),
                "name": p.get("name") or p.get("title"),
            },
            "hospital_ids": hospital_ids,
            "hospitals": comparisons,
        }

    async def admin_list(self, page: int = 1, page_size: int = 20, search: str | None = None):
        query = {}
        if search:
            query = {
                "$or": [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"slug": {"$regex": search, "$options": "i"}},
                    {"title": {"$regex": search, "$options": "i"}},
                    {"description": {"$regex": search, "$options": "i"}},
                ]
            }
        cur = (
            self.col.find(query)
            .skip((page - 1) * page_size)
            .limit(page_size)
            .sort([("updated_at", -1), ("updatedAt", -1), ("_id", -1)])
        )
        items = [str_id(x) async for x in cur]
        total = await self.col.count_documents(query)
        return items, total

    async def create(self, doc: dict):
        """
        NOTE:
        Your schema uses string _id like "pkg_001".
        So make sure the caller sets doc["_id"] before insert,
        and DON'T overwrite it with ObjectId.
        """
        normalized = _normalize_package_write_doc(doc)
        normalized = await self._canonicalize_package_hospitals(normalized)
        raw_slug = (normalized.get("slug") or "").strip()
        base = _slugify(raw_slug) if raw_slug else _slug_base(normalized)
        if base:
            normalized["slug"] = await self._ensure_unique_slug(base)
        res = await self.col.insert_one(normalized)
        # do not overwrite doc["_id"] with inserted_id because it may be string
        created = await self.col.find_one({"_id": normalized.get("_id")}) or normalized
        await self._sync_hospital_backlinks(str_id(created))
        return created

    async def update(self, package_id: str, doc: dict):
        pid = normalize_id(package_id)
        existing = await self.col.find_one({"_id": pid})
        normalized = _normalize_package_write_doc(doc, existing=existing)
        normalized = await self._canonicalize_package_hospitals(normalized)
        await self.col.update_one({"_id": pid}, {"$set": normalized}, upsert=False)
        updated = await self.col.find_one({"_id": pid})
        if updated:
            await self._sync_hospital_backlinks(str_id(updated), previous=str_id(existing) if existing else None)
        return updated

    async def delete(self, package_id: str) -> bool:
        pid = normalize_id(package_id)
        res = await self.col.delete_one({"_id": pid})
        return res.deleted_count == 1
