from datetime import datetime

from fastapi import APIRouter, Depends, Query
from app.repos.doctors import DoctorsRepo
from app.repos.availability import AvailabilityRepo
from app.services.slot_service import get_slots_for_doctor, build_slots_for_date, normalize_timezone
from app.repos.bookings import BookingsRepo
from app.core.errors import http_error
from app.core.pagination import calc_has_more

router = APIRouter(prefix="/api/doctors", tags=["Doctors"])

@router.get("")
async def list_doctors(
    search: str | None = None,
    specialty_id: str | None = None,
    city_id: str | None = None,
    hospital_id: str | None = None,
    language_ids: str | None = None,
    consultation_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str | None = None,
    repo: DoctorsRepo = Depends(DoctorsRepo),
):
    lang_list = [x.strip() for x in (language_ids or "").split(",") if x.strip()]
    data, total = await repo.list_doctors(
        search=search,
        specialty_id=specialty_id,
        city_id=city_id,
        hospital_id=hospital_id,
        language_ids=lang_list,
        consultation_type=consultation_type,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/search")
async def search_doctors(
    q: str = Query(..., min_length=1),
    specialty_id: str | None = None,
    city_id: str | None = None,
    hospital_id: str | None = None,
    language_ids: str | None = None,
    consultation_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str | None = None,
    repo: DoctorsRepo = Depends(DoctorsRepo),
):
    lang_list = [x.strip() for x in (language_ids or "").split(",") if x.strip()]
    data, total = await repo.list_doctors(
        search=q,
        specialty_id=specialty_id,
        city_id=city_id,
        hospital_id=hospital_id,
        language_ids=lang_list,
        consultation_type=consultation_type,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/{id}")
async def doctor_detail(id: str, repo: DoctorsRepo = Depends(DoctorsRepo)):
    doc = await repo.get_doctor(id)
    if not doc:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    return doc

@router.get("/{id}/slots")
async def doctor_slots(
    id: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    timezone: str | None = None,
    repo: DoctorsRepo = Depends(DoctorsRepo),
    bookings_repo: BookingsRepo = Depends(BookingsRepo),
    availability_repo: AvailabilityRepo = Depends(AvailabilityRepo),
):
    doc = await repo.get_doctor_raw(id)
    if not doc:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doc

    doctor_lookup_id = str(doc.get("_id") or id)
    payload = await availability_repo.get_slots(doctor_id=doctor_lookup_id, date=date)
    if not payload:
        weekly = await availability_repo.get_weekly(doctor_id=doctor_lookup_id)
        if weekly:
            tz = normalize_timezone(date, weekly.get("timezone") or timezone)
            weekday = datetime.strptime(date, "%Y-%m-%d").weekday()
            day_slots = None
            for d in weekly.get("days", []):
                if d.get("weekday") == weekday:
                    day_slots = d.get("slots") or []
                    break
            payload = {
                "doctor_id": doctor_lookup_id,
                "date": date,
                "timezone": tz,
                "slots": build_slots_for_date(date=date, timezone=tz, slots=day_slots or []),
            }
        else:
            payload = await get_slots_for_doctor(doctor_id=doctor_lookup_id, date=date, timezone=timezone)
    booked = await bookings_repo.list_booked_slot_starts(doctor_id=doctor_lookup_id, date=date)
    if booked:
        booked_set = set(booked)
        payload["slots"] = [s for s in payload.get("slots", []) if s.get("slot_start") not in booked_set]
    return payload
