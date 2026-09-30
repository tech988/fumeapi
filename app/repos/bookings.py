from datetime import datetime, timezone
import secrets
import string
from zoneinfo import ZoneInfo
from fastapi import Depends
from pymongo.errors import DuplicateKeyError
from app.core.db import get_db
from app.core.errors import http_error
from app.utils.bson import oid, str_id
from app.utils.phone import normalize_indian_phone

class BookingsRepo:
    def __init__(self, db=Depends(get_db)):
        self.col = db["bookings"]
        self.doctors = db["doctors"]
        self.users = db["users"]
        self.patients = db["patients"]

    def _fallback_booking_ref(self, booking_id: str | None) -> str:
        token = ""
        if booking_id:
            token = "".join(ch for ch in str(booking_id).upper() if ch.isalnum())
        if len(token) >= 5:
            token = token[-5:]
        else:
            token = token.rjust(5, "0")
        return f"HBK-{token}"

    def _resolve_booking_ref(self, booking: dict) -> str:
        if not booking:
            return self._fallback_booking_ref(None)
        value = booking.get("booking_ref")
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
        booking_id = booking.get("id") or booking.get("_id")
        return self._fallback_booking_ref(str(booking_id) if booking_id else None)

    async def _generate_booking_ref(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(30):
            suffix = "".join(secrets.choice(alphabet) for _ in range(5))
            ref = f"HBK-{suffix}"
            existing = await self.col.find_one({"booking_ref": ref}, {"_id": 1})
            if not existing:
                return ref
        http_error(500, "BOOKING_REF_FAILED", "Unable to generate booking reference")
        return ""

    def _normalize_slot_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value)
        if not s:
            return s

        if s.endswith("Z"):
            return s

        if len(s) >= 6 and s[-6] in {"+", "-"} and s[-3] == ":":
            return s

        if "T" in s and "/" in s and len(s) >= 19 and s[10] == "T":
            base = s[:19]
            tz = s[19:]
            try:
                dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
                offset = dt.replace(tzinfo=ZoneInfo(tz)).utcoffset()
                if offset is None:
                    return s
                total_minutes = int(offset.total_seconds() // 60)
                sign = "+" if total_minutes >= 0 else "-"
                total_minutes = abs(total_minutes)
                hours = total_minutes // 60
                minutes = total_minutes % 60
                return f"{base}{sign}{hours:02d}:{minutes:02d}"
            except Exception:
                return s

        return s

    def _normalize_booking_slots(self, booking: dict) -> dict:
        if not booking:
            return booking
        booking["slot_start"] = self._normalize_slot_value(booking.get("slot_start"))
        booking["slot_end"] = self._normalize_slot_value(booking.get("slot_end"))
        booking["booking_ref"] = self._resolve_booking_ref(booking)
        return booking

    def _patient_booking_query(self, patient_id: str, user_id: str | None = None) -> dict:
        keys = {str(patient_id)}
        if user_id:
            keys.add(str(user_id))
        return {
            "$or": [
                {"user_id": {"$in": list(keys)}},
                {"patient_id": {"$in": list(keys)}},
            ]
        }

    def _booking_create_response(self, booking: dict, message: str, reused_existing_booking: bool = False) -> dict:
        booking_id = booking.get("id") or booking.get("_id")
        created_at = booking.get("created_at")
        created_at_iso = None
        if isinstance(created_at, datetime):
            created_at_iso = created_at.astimezone().isoformat()

        payment_status = booking.get("payment_status")
        redirect_to_payment = payment_status in {"unpaid", "pending", "failed"}

        return {
            "booking": {
                "id": str(booking_id) if booking_id else None,
                "booking_ref": booking.get("booking_ref"),
                "user_id": booking.get("user_id"),
                "doctor_id": booking.get("doctor_id"),
                "consultation_type": booking.get("consultation_type"),
                "slot_start": booking.get("slot_start"),
                "slot_end": booking.get("slot_end"),
                "status": booking.get("status"),
                "payment_status": payment_status,
                "created_at": created_at_iso,
            },
            "message": message,
            "next_actions": {
                "redirect_to_payment": redirect_to_payment,
                "payment_url": None,
            },
            "meta": {
                "reused_existing_booking": reused_existing_booking,
            },
        }

    async def _resolve_patient_summary(self, booking: dict) -> dict:
        patient: dict = {}
        raw_patient = booking.get("patient")
        if isinstance(raw_patient, dict):
            patient = raw_patient
        name = str(patient.get("full_name") or patient.get("name") or booking.get("patient_name") or "").strip()
        email = str(patient.get("email") or booking.get("patient_email") or "").strip()
        phone = str(patient.get("phone") or booking.get("patient_phone") or "").strip()

        user_id = str(booking.get("user_id") or booking.get("patient_id") or "").strip()
        patient_profile: dict = {}
        user: dict = {}

        if user_id:
            patient_profile = await self.patients.find_one({"user_id": user_id}) or {}
            try:
                user = await self.users.find_one({"_id": oid(user_id)}) or {}
            except Exception:
                user = {}

        lookup_email = email.lower().strip() if email else ""
        lookup_phone = phone.strip() if phone else ""
        if not patient_profile and (lookup_email or lookup_phone):
            patient_profile = await self.patients.find_one(
                {
                    "$or": [
                        *([{"email": lookup_email}] if lookup_email else []),
                        *([{"phone": lookup_phone}] if lookup_phone else []),
                        *([{"mobile": lookup_phone}] if lookup_phone else []),
                    ]
                }
            ) or {}

        if not user and (lookup_email or lookup_phone):
            user = await self.users.find_one(
                {
                    "$or": [
                        *([{"email": lookup_email}] if lookup_email else []),
                        *([{"phone": lookup_phone}] if lookup_phone else []),
                    ]
                }
            ) or {}

        if not name:
            name = str(
                patient_profile.get("full_name")
                or user.get("full_name")
                or user.get("name")
                or ""
            ).strip()
        if not email:
            email = str(patient_profile.get("email") or user.get("email") or "").strip()
        if not phone:
            phone = str(patient_profile.get("phone") or user.get("phone") or "").strip()

        return {
            "name": name,
            "email": email,
            "phone": phone,
        }

    async def create_booking(self, user_id: str, payload: dict):
        doctor_id = payload.get("doctor_id")
        slot_start = self._normalize_slot_value(payload.get("slot_start"))
        slot_end = self._normalize_slot_value(payload.get("slot_end"))
        consultation_type = payload.get("consultation_type")

        if not all([doctor_id, slot_start, slot_end, consultation_type]):
            http_error(400, "VALIDATION_ERROR", "doctor_id, slot_start, slot_end, consultation_type are required")

        assert doctor_id
        assert slot_start
        assert slot_end
        assert consultation_type

        patient_phone = normalize_indian_phone(payload.get("patient_phone"))
        if payload.get("patient_phone") and not patient_phone:
            http_error(400, "INVALID_PHONE", "Please enter a valid 10-digit phone number")

        patient_payload: dict = {}
        raw_patient_payload = payload.get("patient")
        if isinstance(raw_patient_payload, dict):
            patient_payload = dict(raw_patient_payload)
        patient_name = str(payload.get("patient_name") or patient_payload.get("full_name") or patient_payload.get("name") or "").strip()
        patient_email = str(payload.get("patient_email") or patient_payload.get("email") or "").strip()
        patient_update: dict = dict(patient_payload)
        if patient_name:
            patient_update["full_name"] = patient_name
            patient_update["name"] = patient_name
        if patient_email:
            patient_update["email"] = patient_email
        if patient_phone:
            patient_update["phone"] = patient_phone

        doctor_id = str(doctor_id)
        slot_start = str(slot_start)
        slot_end = str(slot_end)

        doc = await self.doctors.find_one({"_id": oid(doctor_id)})
        if not doc:
            http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")

        conflict = await self.col.find_one({
            "doctor_id": doctor_id,
            "slot_start": slot_start,
            "status": {"$in": ["pending", "confirmed"]}
        })
        if conflict:
            conflict_user_id = str(conflict.get("user_id") or conflict.get("patient_id") or "")
            conflict_payment_status = str(conflict.get("payment_status") or "")
            reusable_payment_states = {"unpaid", "pending", "failed"}
            if conflict_user_id == str(user_id) and conflict_payment_status in reusable_payment_states:
                conflict_view = self._normalize_booking_slots(str_id(conflict))
                return self._booking_create_response(
                    booking=conflict_view,
                    message="Booking already exists for this slot.",
                    reused_existing_booking=True,
                )
            http_error(409, "SLOT_CONFLICT", "This slot is already booked")

        booking = None
        for _ in range(3):
            booking = {
                "user_id": user_id,
                "patient_id": user_id,
                "doctor_id": doctor_id,
                "doctor_user_id": doc.get("user_id"),
                "doctor_name": doc.get("name"),
                "specialty_label": doc.get("specialty_label"),
                "consultation_type": consultation_type,
                "slot_start": slot_start,
                "slot_end": slot_end,
                "status": "pending",
                "payment_status": "unpaid",
                "booking_ref": await self._generate_booking_ref(),
                "patient": patient_update,
                "meta": payload.get("meta", {}),
                "created_at": datetime.now(timezone.utc),
            }
            try:
                res = await self.col.insert_one(booking)
                break
            except DuplicateKeyError:
                continue
        else:
            http_error(500, "BOOKING_REF_FAILED", "Unable to create booking reference")
            return {}

        assert booking is not None
        booking["_id"] = res.inserted_id
        booking_id = str(booking["_id"])
        booking = str_id(booking)
        booking = self._normalize_booking_slots(booking)
        booking["id"] = booking_id
        return self._booking_create_response(
            booking=booking,
            message="Booking created.",
            reused_existing_booking=False,
        )

    async def list_booked_slot_starts(self, doctor_id: str, date: str):
        q = {
            "doctor_id": doctor_id,
            "status": {"$in": ["pending", "confirmed"]},
            "slot_start": {"$regex": f"^{date}"},
        }
        cur = self.col.find(q, {"slot_start": 1})
        slots = []
        async for b in cur:
            slot_start = self._normalize_slot_value(b.get("slot_start"))
            if slot_start:
                slots.append(slot_start)
        return slots

    async def list_for_user(
        self,
        user_id: str,
        role: str,
        status: str | None,
        date_from: str | None,
        date_to: str | None,
        doctor_id: str | None,
        page: int,
        page_size: int,
    ):
        q = {}
        if role == "patient":
            q = self._patient_booking_query(user_id)
        elif role == "doctor":
            if doctor_id:
                q["doctor_id"] = doctor_id
            else:
                q["doctor_user_id"] = user_id
        else:
            http_error(403, "FORBIDDEN", "Admins should use admin endpoints")

        if status:
            q["status"] = status

        cur = self.col.find(q).skip((page-1)*page_size).limit(page_size).sort([("created_at", -1), ("_id", -1)])
        items = []
        async for b in cur:
            b = str_id(b)
            booking_id = b.get("id") or b.get("_id")
            items.append({
                "id": booking_id,
                "booking_ref": self._resolve_booking_ref(b),
                "doctor_name": b.get("doctor_name"),
                "specialty_label": b.get("specialty_label"),
                "consultation_type": b.get("consultation_type"),
                "slot_start": self._normalize_slot_value(b.get("slot_start")),
                "slot_end": self._normalize_slot_value(b.get("slot_end")),
                "status": b.get("status"),
                "payment_status": b.get("payment_status"),
                "hospital_name": b.get("hospital_name"),
                "city": b.get("city"),
            })
        total = await self.col.count_documents(q)
        return items, total

    async def get_booking_for_user(self, booking_id: str, user_id: str, role: str):
        b = await self.col.find_one({"_id": oid(booking_id)})
        if not b:
            return None
        patient_keys = {str(b.get("user_id") or ""), str(b.get("patient_id") or "")}
        if role == "patient" and str(user_id) not in patient_keys:
            return None
        if role == "doctor" and b.get("doctor_user_id") != user_id:
            return None
        return self._normalize_booking_slots(str_id(b))

    async def cancel_booking(self, booking_id: str, user_id: str) -> bool:
        res = await self.col.update_one(
            {"_id": oid(booking_id), **self._patient_booking_query(user_id)},
            {"$set": {"status": "cancelled"}},
        )
        return res.modified_count == 1

    async def reschedule_booking(self, booking_id: str, user_id: str, slot_start: str, slot_end: str):
        normalized_slot_start = self._normalize_slot_value(slot_start)
        normalized_slot_end = self._normalize_slot_value(slot_end)
        if normalized_slot_start is None or normalized_slot_end is None:
            http_error(400, "VALIDATION_ERROR", "slot_start and slot_end are required")
        assert normalized_slot_start is not None
        assert normalized_slot_end is not None
        slot_start = normalized_slot_start
        slot_end = normalized_slot_end
        booking = await self.col.find_one({"_id": oid(booking_id), **self._patient_booking_query(user_id)})
        if not booking:
            return None

        conflict = await self.col.find_one({
            "_id": {"$ne": oid(booking_id)},
            "doctor_id": booking.get("doctor_id"),
            "slot_start": slot_start,
            "status": {"$in": ["pending", "confirmed"]},
        })
        if conflict:
            http_error(409, "SLOT_CONFLICT", "This slot is already booked")

        await self.col.update_one(
            {"_id": oid(booking_id), **self._patient_booking_query(user_id)},
            {"$set": {"slot_start": slot_start, "slot_end": slot_end, "status": "pending"}},
        )
        b = await self.col.find_one({"_id": oid(booking_id)})
        return self._normalize_booking_slots(str_id(b)) if b else None

    async def doctor_update_status(self, booking_id: str, doctor_id: str, status: str):
        await self.col.update_one({"_id": oid(booking_id), "doctor_id": doctor_id}, {"$set": {"status": status}})
        b = await self.col.find_one({"_id": oid(booking_id)})
        return self._normalize_booking_slots(str_id(b)) if b else None

    async def admin_list(self, status: str | None, doctor_id: str | None, date_from: str | None, date_to: str | None, page: int, page_size: int):
        q = {}
        if status:
            q["status"] = status
        if doctor_id:
            q["doctor_id"] = doctor_id

        cur = self.col.find(q).skip((page-1)*page_size).limit(page_size).sort([("created_at", -1), ("_id", -1)])
        items = []
        async for b in cur:
            b = str_id(b)
            booking_id = b.get("id") or b.get("_id")
            patient_summary = await self._resolve_patient_summary(b)
            items.append({
                "id": booking_id,
                "booking_ref": self._resolve_booking_ref(b),
                "patient_name": patient_summary["name"],
                "patient_phone": patient_summary["phone"],
                "patient_email": patient_summary["email"],
                "doctor_name": b.get("doctor_name"),
                "specialty_label": b.get("specialty_label"),
                "consultation_type": b.get("consultation_type"),
                "slot_start": self._normalize_slot_value(b.get("slot_start")),
                "slot_end": self._normalize_slot_value(b.get("slot_end")),
                "status": b.get("status"),
                "payment_status": b.get("payment_status"),
            })
        total = await self.col.count_documents(q)
        return items, total

    async def admin_list_doctor_bookings(
        self,
        doctor_id: str,
        q: str | None,
        status: str | None,
        date_from: str | None,
        date_to: str | None,
        date_range: str | None,
        page: int,
        page_size: int,
    ):
        query: dict = {"doctor_id": doctor_id}
        if status:
            query["status"] = status
        if q:
            query["$or"] = [
                {"patient.full_name": {"$regex": q, "$options": "i"}},
                {"patient.email": {"$regex": q, "$options": "i"}},
                {"patient.phone": {"$regex": q, "$options": "i"}},
                {"doctor_name": {"$regex": q, "$options": "i"}},
                {"specialty_label": {"$regex": q, "$options": "i"}},
            ]

        if date_range in {"today", "upcoming", "past"}:
            today = datetime.now(timezone.utc).date().isoformat()
            if date_range == "today":
                query["slot_start"] = {"$regex": f"^{today}"}
            elif date_range == "upcoming":
                query["slot_start"] = {"$gte": f"{today}T00:00:00"}
            elif date_range == "past":
                query["slot_start"] = {"$lt": f"{today}T00:00:00"}
        else:
            if date_from or date_to:
                band: dict = {}
                if date_from:
                    band["$gte"] = f"{date_from}T00:00:00"
                if date_to:
                    band["$lte"] = f"{date_to}T23:59:59"
                query["slot_start"] = band

        cur = self.col.find(query).skip((page-1)*page_size).limit(page_size).sort([("created_at", -1), ("_id", -1)])
        items = []
        async for b in cur:
            b = str_id(b)
            booking_id = b.get("id") or b.get("_id")
            patient_summary = await self._resolve_patient_summary(b)
            items.append({
                "id": booking_id,
                "booking_ref": self._resolve_booking_ref(b),
                "patient_name": patient_summary["name"],
                "patient_phone": patient_summary["phone"],
                "patient_email": patient_summary["email"],
                "doctor_name": b.get("doctor_name"),
                "specialty_label": b.get("specialty_label"),
                "consultation_type": b.get("consultation_type"),
                "slot_start": self._normalize_slot_value(b.get("slot_start")),
                "slot_end": self._normalize_slot_value(b.get("slot_end")),
                "status": b.get("status"),
                "payment_status": b.get("payment_status"),
            })
        total = await self.col.count_documents(query)
        return items, total

    async def admin_list_patient_bookings(
        self,
        patient_id: str,
        user_id: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ):
        query = self._patient_booking_query(patient_id=patient_id, user_id=user_id)
        if status:
            query["status"] = status

        cur = self.col.find(query).skip((page - 1) * page_size).limit(page_size).sort([
            ("slot_start", -1),
            ("created_at", -1),
            ("_id", -1),
        ])

        items = []
        async for b in cur:
            b = self._normalize_booking_slots(str_id(b))
            booking_id = b.get("id") or b.get("_id")
            patient_payload = b.get("patient") or {}
            items.append({
                "id": booking_id,
                "booking_ref": self._resolve_booking_ref(b),
                "user_id": b.get("user_id"),
                "patient_id": b.get("patient_id") or patient_id,
                "patient_name": patient_payload.get("full_name"),
                "patient_phone": patient_payload.get("phone"),
                "patient_email": patient_payload.get("email"),
                "doctor_id": b.get("doctor_id"),
                "doctor_name": b.get("doctor_name"),
                "specialty_label": b.get("specialty_label"),
                "consultation_type": b.get("consultation_type"),
                "slot_start": b.get("slot_start"),
                "slot_end": b.get("slot_end"),
                "status": b.get("status"),
                "payment_status": b.get("payment_status"),
                "created_at": b.get("created_at"),
            })

        total = await self.col.count_documents(query)
        return items, total

    async def admin_update_booking(self, booking_id: str, payload: dict):
        allowed = {}
        if "status" in payload:
            allowed["status"] = payload["status"]
        if "internal_notes" in payload:
            allowed["internal_notes"] = payload["internal_notes"]
        await self.col.update_one({"_id": oid(booking_id)}, {"$set": allowed})
        b = await self.col.find_one({"_id": oid(booking_id)})
        return {"booking": self._normalize_booking_slots(str_id(b)) if b else None}
