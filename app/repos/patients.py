from datetime import date, datetime, timezone

from fastapi import Depends

from app.core.db import get_db
from app.utils.bson import oid, str_id


class PatientsRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["patients"]
        self.users = db["users"]
        self.bookings = db["bookings"]

    def _parse_date(self, value) -> date | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                try:
                    return datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    return None
        return None

    def _parse_datetime(self, value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                try:
                    dt = datetime.strptime(text, "%Y-%m-%d")
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    return None
        return None

    def _coalesce_payload_value(self, payload: dict, *keys: str):
        for key in keys:
            if key in payload:
                return payload.get(key)
        return None

    def _normalize_gender(self, value) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None

    def _normalize_date_of_birth(self, value) -> str | None:
        parsed = self._parse_date(value)
        if parsed is None:
            if isinstance(value, str):
                text = value.strip()
                return text or None
            return None
        return parsed.isoformat()

    def _normalize_shared_profile_fields(self, payload: dict) -> dict:
        if not payload:
            return {}

        patch: dict = {}

        full_name = self._coalesce_payload_value(payload, "full_name", "name")
        if full_name is not None:
            patch["full_name"] = str(full_name).strip() or None

        email = self._coalesce_payload_value(payload, "email")
        if email is not None:
            patch["email"] = str(email).lower().strip() or None

        phone = self._coalesce_payload_value(payload, "phone", "mobile")
        if phone is not None:
            patch["phone"] = str(phone).strip() or None

        status = self._coalesce_payload_value(payload, "status")
        if status is not None:
            patch["status"] = str(status).lower().strip() or None

        image = self._coalesce_payload_value(payload, "image")
        if image is not None:
            patch["image"] = image

        gender = self._coalesce_payload_value(payload, "gender")
        if gender is not None:
            patch["gender"] = self._normalize_gender(gender)

        date_of_birth = self._coalesce_payload_value(payload, "date_of_birth", "dateOfBirth")
        if date_of_birth is not None:
            patch["date_of_birth"] = self._normalize_date_of_birth(date_of_birth)

        blood_group = self._coalesce_payload_value(payload, "blood_group", "bloodGroup")
        if blood_group is not None:
            patch["blood_group"] = str(blood_group).strip().upper() or None

        return patch

    def _age_years(self, dob: date) -> int | None:
        if not dob:
            return None
        today = datetime.now(timezone.utc).date()
        years = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            years -= 1
        return years

    def _patient_id(self, patient: dict | None) -> str | None:
        if not patient:
            return None
        value = patient.get("id") or patient.get("_id")
        if not value:
            return None
        return str(value)

    def _patient_lookup_keys(self, patient: dict | None) -> set[str]:
        keys: set[str] = set()
        if not patient:
            return keys
        patient_id = self._patient_id(patient)
        user_id = patient.get("user_id")
        if patient_id:
            keys.add(patient_id)
        if user_id:
            keys.add(str(user_id))
        return keys

    def _default_booking_stats(self) -> dict:
        return {
            "total_bookings": 0,
            "upcoming_appointments": 0,
            "last_visit": None,
        }

    async def _get_booking_stats_map(self, patients: list[dict]) -> dict[str, dict]:
        patient_ids = [patient_id for patient in patients if (patient_id := self._patient_id(patient))]
        stats = {patient_id: self._default_booking_stats() for patient_id in patient_ids}
        if not patient_ids:
            return stats

        alias_to_patient_id: dict[str, str] = {}
        match_keys: set[str] = set()
        email_keys: set[str] = set()
        phone_keys: set[str] = set()

        for patient in patients:
            patient_id = self._patient_id(patient)
            if not patient_id:
                continue
            for key in self._patient_lookup_keys(patient):
                alias_to_patient_id[key] = patient_id
                match_keys.add(key)
            email = str(patient.get("email") or "").lower().strip()
            phone = str(patient.get("phone") or patient.get("mobile") or "").strip()
            if email:
                alias_to_patient_id[email] = patient_id
                email_keys.add(email)
            if phone:
                alias_to_patient_id[phone] = patient_id
                phone_keys.add(phone)

        if not match_keys and not email_keys and not phone_keys:
            return stats

        now = datetime.now(timezone.utc)
        cursor = self.bookings.find(
            {
                "$or": [
                    {"user_id": {"$in": list(match_keys)}},
                    {"patient_id": {"$in": list(match_keys)}},
                    {"patient.email": {"$in": list(email_keys)}},
                    {"patient.phone": {"$in": list(phone_keys)}},
                    {"patient_email": {"$in": list(email_keys)}},
                    {"patient_phone": {"$in": list(phone_keys)}},
                ]
            },
            {
                "user_id": 1,
                "patient_id": 1,
                "patient": 1,
                "patient_email": 1,
                "patient_phone": 1,
                "status": 1,
                "slot_start": 1,
            },
        )

        async for booking in cursor:
            matched_patient_ids: set[str] = set()
            for key in (booking.get("patient_id"), booking.get("user_id")):
                if key is None:
                    continue
                patient_id = alias_to_patient_id.get(str(key))
                if patient_id:
                    matched_patient_ids.add(patient_id)

            patient_payload = booking.get("patient") if isinstance(booking.get("patient"), dict) else {}
            for key in (
                patient_payload.get("email"),
                booking.get("patient_email"),
                patient_payload.get("phone"),
                booking.get("patient_phone"),
            ):
                if key is None:
                    continue
                patient_id = alias_to_patient_id.get(str(key).lower().strip() if "@" in str(key) else str(key).strip())
                if patient_id:
                    matched_patient_ids.add(patient_id)

            for patient_id in matched_patient_ids:
                patient_stats = stats.setdefault(patient_id, self._default_booking_stats())
                patient_stats["total_bookings"] += 1

                slot_start_dt = self._parse_datetime(booking.get("slot_start"))
                status = str(booking.get("status") or "").lower().strip()

                if slot_start_dt and status in {"pending", "confirmed"} and slot_start_dt >= now:
                    patient_stats["upcoming_appointments"] += 1

                if slot_start_dt and status != "cancelled" and slot_start_dt <= now:
                    current_last_visit = self._parse_datetime(patient_stats.get("last_visit"))
                    if current_last_visit is None or slot_start_dt > current_last_visit:
                        patient_stats["last_visit"] = slot_start_dt.isoformat()

        return stats

    async def _get_users_by_ids(self, user_ids: list[str]) -> dict[str, dict]:
        if not user_ids:
            return {}
        oids = []
        for user_id in user_ids:
            try:
                oids.append(oid(user_id))
            except Exception:
                continue
        if not oids:
            return {}
        cur = self.users.find({"_id": {"$in": oids}})
        out = {}
        async for u in cur:
            out[str(u.get("_id"))] = u
        return out

    def _normalize_user_patch(self, payload: dict) -> dict:
        return self._normalize_shared_profile_fields(payload)

    def _normalize_patient_patch(self, payload: dict) -> dict:
        patch = dict(payload or {})
        for k in ("_id", "id", "user_id", "created_at", "updated_at"):
            patch.pop(k, None)
        shared = self._normalize_shared_profile_fields(payload)
        for key, value in shared.items():
            patch[key] = value
        if "mobile" in patch:
            patch.pop("mobile", None)
        if "name" in patch:
            patch.pop("name", None)
        if "dateOfBirth" in patch:
            patch.pop("dateOfBirth", None)
        return patch

    def _merge_patient_user(self, patient: dict, user: dict | None) -> dict:
        if not patient:
            return patient
        user = user or {}
        merged = dict(patient)
        for field in ("full_name", "email", "phone", "status", "image", "date_of_birth", "gender"):
            if merged.get(field) in (None, ""):
                if field in user:
                    merged[field] = user.get(field)
        dob = self._parse_date(merged.get("date_of_birth"))
        merged["age_years"] = self._age_years(dob) if dob else None
        return merged

    def _serialize_patient(self, patient: dict, booking_stats: dict | None = None) -> dict:
        booking_stats = booking_stats or self._default_booking_stats()
        total_bookings = int(booking_stats.get("total_bookings", 0) or 0)
        upcoming_appointments = int(booking_stats.get("upcoming_appointments", 0) or 0)
        last_visit = booking_stats.get("last_visit")

        serialized = dict(patient)
        serialized["id"] = self._patient_id(serialized)
        serialized["name"] = serialized.get("name") or serialized.get("full_name")
        serialized["mobile"] = serialized.get("mobile") or serialized.get("phone")
        serialized["location"] = serialized.get("location") or serialized.get("city")
        serialized["registered_at"] = serialized.get("registered_at") or serialized.get("created_at")
        serialized["dateOfBirth"] = serialized.get("date_of_birth")
        serialized["bloodGroup"] = serialized.get("bloodGroup") or serialized.get("blood_group")
        active_insurance_count = 1 if serialized.get("insurance_provider") or serialized.get("insuranceProvider") else 0
        serialized["active_insurance_count"] = active_insurance_count
        serialized["activeInsuranceCount"] = active_insurance_count
        serialized["total_bookings"] = total_bookings
        serialized["totalBookings"] = total_bookings
        serialized["booking_count"] = total_bookings
        serialized["upcoming_appointments"] = upcoming_appointments
        serialized["upcomingAppointments"] = upcoming_appointments
        serialized["last_visit"] = serialized.get("last_visit") or last_visit
        return serialized

    async def _enrich_patient(self, doc: dict, user: dict | None = None, booking_stats: dict | None = None):
        if not doc:
            return None
        patient = str_id(doc)
        if user is None:
            user_id = patient.get("user_id")
            if user_id:
                user_map = await self._get_users_by_ids([user_id])
                user = user_map.get(user_id)
        user = str_id(user) if user else None
        merged = self._merge_patient_user(patient, user)
        return self._serialize_patient(merged, booking_stats=booking_stats)

    async def list_patients(self, q: str | None, status: str | None, page: int, page_size: int):
        query: dict = {}
        if status:
            query["status"] = status
        if q:
            query["$or"] = [
                {"full_name": {"$regex": q, "$options": "i"}},
                {"email": {"$regex": q, "$options": "i"}},
                {"phone": {"$regex": q, "$options": "i"}},
                {"city": {"$regex": q, "$options": "i"}},
            ]

        cur = (
            self.col.find(query)
            .skip((page - 1) * page_size)
            .limit(page_size)
            .sort([("updated_at", -1), ("_id", -1)])
        )
        raw_items = [x async for x in cur]
        user_ids = [str(x.get("user_id")) for x in raw_items if x.get("user_id")]
        users_map = await self._get_users_by_ids(user_ids)
        booking_stats_map = await self._get_booking_stats_map(raw_items)
        items = []
        for doc in raw_items:
            patient_id = self._patient_id(doc)
            user_id = str(doc.get("user_id")) if doc.get("user_id") else None
            user = users_map.get(user_id) if user_id else None
            booking_stats = booking_stats_map.get(patient_id, self._default_booking_stats()) if patient_id else self._default_booking_stats()
            merged = await self._enrich_patient(doc, user=user, booking_stats=booking_stats)
            if merged is not None:
                items.append(merged)
        total = await self.col.count_documents(query)
        return items, total

    async def get_patient(self, patient_id: str):
        doc = await self.col.find_one({"_id": oid(patient_id)})
        if not doc:
            return None
        booking_stats_map = await self._get_booking_stats_map([doc])
        return await self._enrich_patient(
            doc,
            booking_stats=booking_stats_map.get(patient_id, self._default_booking_stats()),
        )

    async def get_by_user_id(self, user_id: str):
        doc = await self.col.find_one({"user_id": user_id})
        if not doc:
            return None
        patient_id = self._patient_id(doc)
        booking_stats_map = await self._get_booking_stats_map([doc])
        return await self._enrich_patient(
            doc,
            booking_stats=booking_stats_map.get(patient_id, self._default_booking_stats()) if patient_id else self._default_booking_stats(),
        )

    async def ensure_patient_profile(self, user_id: str, payload: dict):
        existing = await self.col.find_one({"user_id": user_id})
        if existing:
            return await self.update_by_user_id(user_id, payload)
        return await self.create_patient({**payload, "user_id": user_id})

    async def create_patient(self, payload: dict):
        normalized_payload = self._normalize_patient_patch(payload)
        user_id = payload.get("user_id")
        doc = {
            **normalized_payload,
            "user_id": user_id,
            "status": normalized_payload.get("status") or "active",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        res = await self.col.insert_one(doc)
        doc["_id"] = res.inserted_id
        user_patch = self._normalize_user_patch(payload)
        if user_patch and user_id:
            await self.users.update_one(
                {"_id": oid(user_id)},
                {"$set": {**user_patch, "updated_at": datetime.now(timezone.utc)}},
            )
        return await self._enrich_patient(doc)

    async def update_patient(self, patient_id: str, payload: dict):
        existing = await self.col.find_one({"_id": oid(patient_id)})
        if not existing:
            return None
        user_id = str(existing.get("user_id")) if existing.get("user_id") else None
        patient_patch = self._normalize_patient_patch(payload)
        if patient_patch:
            patient_patch["updated_at"] = datetime.now(timezone.utc)
            await self.col.update_one({"_id": oid(patient_id)}, {"$set": patient_patch})
        user_patch = self._normalize_user_patch(payload)
        if user_patch and user_id:
            await self.users.update_one(
                {"_id": oid(user_id)},
                {"$set": {**user_patch, "updated_at": datetime.now(timezone.utc)}},
            )
        doc = await self.col.find_one({"_id": oid(patient_id)})
        booking_stats_map = await self._get_booking_stats_map([doc] if doc else [])
        return await self._enrich_patient(
            doc,
            booking_stats=booking_stats_map.get(patient_id, self._default_booking_stats()),
        ) if doc else None

    async def update_by_user_id(self, user_id: str, payload: dict):
        existing = await self.col.find_one({"user_id": user_id})
        if not existing:
            return None
        patient_patch = self._normalize_patient_patch(payload)
        if patient_patch:
            patient_patch["updated_at"] = datetime.now(timezone.utc)
            await self.col.update_one({"user_id": user_id}, {"$set": patient_patch})
        user_patch = self._normalize_user_patch(payload)
        if user_patch:
            await self.users.update_one(
                {"_id": oid(user_id)},
                {"$set": {**user_patch, "updated_at": datetime.now(timezone.utc)}},
            )
        doc = await self.col.find_one({"user_id": user_id})
        patient_id = self._patient_id(doc) if doc else None
        booking_stats_map = await self._get_booking_stats_map([doc] if doc else [])
        return await self._enrich_patient(
            doc,
            booking_stats=booking_stats_map.get(patient_id, self._default_booking_stats()) if patient_id else self._default_booking_stats(),
        ) if doc else None

    async def delete_patient(self, patient_id: str) -> bool:
        res = await self.col.delete_one({"_id": oid(patient_id)})
        return res.deleted_count == 1
