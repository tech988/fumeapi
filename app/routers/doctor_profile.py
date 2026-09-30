from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.core.errors import http_error
from app.core.deps import require_roles
from app.repos.doctors import DoctorsRepo
from app.repos.availability import AvailabilityRepo
from app.services.slot_service import build_slots_for_date

router = APIRouter(prefix="/api/doctor", tags=["Doctors"])


@router.get("/me")
async def get_doctor_me(
    user=Depends(require_roles("doctor")),
    repo: DoctorsRepo = Depends(DoctorsRepo),
):
    doc = await repo.get_doctor_by_user_id(str(user["_id"]))
    if not doc:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doc
    return {"data": doc}


@router.patch("/me")
async def update_doctor_me(
    payload: dict,
    user=Depends(require_roles("doctor")),
    repo: DoctorsRepo = Depends(DoctorsRepo),
):
    doc = await repo.get_doctor_by_user_id(str(user["_id"]))
    if not doc:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")

    patch = dict(payload or {})
    for k in ("_id", "id", "user_id", "created_at", "updated_at"):
        patch.pop(k, None)

    assert doc
    doctor_ref = doc.get("id") or doc.get("_id")
    updated = await repo.update(doctor_ref, patch)
    return {"data": updated}


@router.get("/availability")
async def get_my_availability(
    date: str = Query(..., description="YYYY-MM-DD"),
    user=Depends(require_roles("doctor")),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
    availability: AvailabilityRepo = Depends(AvailabilityRepo),
):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        http_error(400, "INVALID_DATE", "date must be YYYY-MM-DD")

    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if not doctor:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doctor

    doctor_id = doctor.get("id") or doctor.get("_id")
    payload = await availability.get_slots(doctor_id=str(doctor_id), date=date)
    return payload or {"doctor_id": str(doctor_id), "date": date, "timezone": None, "slots": []}


@router.post("/availability")
async def upsert_my_availability(
    payload: dict,
    user=Depends(require_roles("doctor")),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
    availability: AvailabilityRepo = Depends(AvailabilityRepo),
):
    date = payload.get("date")
    slots = payload.get("slots")
    timezone_label = payload.get("timezone")

    if not date:
        http_error(400, "VALIDATION_ERROR", "date is required")
    try:
        datetime.strptime(str(date), "%Y-%m-%d")
    except ValueError:
        http_error(400, "INVALID_DATE", "date must be YYYY-MM-DD")

    slots_value = slots
    if not isinstance(slots_value, list):
        http_error(400, "VALIDATION_ERROR", "slots must be a list")
    assert isinstance(slots_value, list)
    slots_list: list[dict] = slots_value
    for s in slots_list:
        if not isinstance(s, dict) or not s.get("slot_start") or not s.get("slot_end"):
            http_error(400, "VALIDATION_ERROR", "each slot must include slot_start and slot_end")

    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if not doctor:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doctor

    doctor_id = doctor.get("id") or doctor.get("_id")
    saved = await availability.upsert_slots(str(doctor_id), str(date), timezone_label, slots_list)
    return {"data": saved}


@router.get("/availability/weekly")
async def get_my_weekly_availability(
    user=Depends(require_roles("doctor")),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
    availability: AvailabilityRepo = Depends(AvailabilityRepo),
):
    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if not doctor:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doctor

    doctor_id = doctor.get("id") or doctor.get("_id")
    data = await availability.get_weekly(str(doctor_id))
    return {"data": data or {"doctor_id": str(doctor_id), "timezone": None, "days": []}}


@router.post("/availability/weekly")
async def upsert_my_weekly_availability(
    payload: dict,
    user=Depends(require_roles("doctor")),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
    availability: AvailabilityRepo = Depends(AvailabilityRepo),
):
    days = payload.get("days")
    timezone_label = payload.get("timezone")

    if not isinstance(days, list):
        http_error(400, "VALIDATION_ERROR", "days must be a list")
    assert isinstance(days, list)

    normalized_days = []
    for d in days:
        if not isinstance(d, dict):
            http_error(400, "VALIDATION_ERROR", "each day must be an object")
        weekday = d.get("weekday")
        if not isinstance(weekday, int) or weekday < 0 or weekday > 6:
            http_error(400, "VALIDATION_ERROR", "weekday must be 0-6 (Mon-Sun)")
        slots = d.get("slots")
        if not isinstance(slots, list):
            http_error(400, "VALIDATION_ERROR", "slots must be a list")
        assert isinstance(slots, list)

        normalized_slots = []
        for s in slots:
            if not isinstance(s, dict):
                http_error(400, "VALIDATION_ERROR", "each slot must be an object")
            start = s.get("start") or s.get("slot_start")
            end = s.get("end") or s.get("slot_end")
            if not start or not end:
                http_error(400, "VALIDATION_ERROR", "each slot must include start/end")
            normalized_slots.append({"start": str(start), "end": str(end)})

        normalized_days.append({"weekday": weekday, "slots": normalized_slots})

    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if not doctor:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doctor

    doctor_id = doctor.get("id") or doctor.get("_id")
    saved = await availability.upsert_weekly(str(doctor_id), timezone_label, normalized_days)
    return {"data": saved}


@router.post("/availability/weekly/apply")
async def apply_weekly_for_next_days(
    payload: dict,
    user=Depends(require_roles("doctor")),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
    availability: AvailabilityRepo = Depends(AvailabilityRepo),
):
    days_count = payload.get("days") or 7
    try:
        days_count = int(days_count)
    except Exception:
        http_error(400, "VALIDATION_ERROR", "days must be an integer")
    if days_count < 1 or days_count > 30:
        http_error(400, "VALIDATION_ERROR", "days must be between 1 and 30")

    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if not doctor:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doctor

    doctor_id = doctor.get("id") or doctor.get("_id")
    weekly = await availability.get_weekly(str(doctor_id))
    if not weekly:
        http_error(400, "WEEKLY_NOT_SET", "Weekly availability not set")
    assert weekly

    tz = weekly.get("timezone") or "+05:30"
    days = weekly.get("days") or []

    by_weekday = {d.get("weekday"): d.get("slots") or [] for d in days if isinstance(d, dict)}

    today = datetime.now(timezone.utc).date()
    written = 0
    for i in range(days_count):
        day = today + timedelta(days=i)
        weekday = day.weekday()
        slots = by_weekday.get(weekday) or []
        if not slots:
            continue
        date_str = day.isoformat()
        built = build_slots_for_date(date=date_str, timezone=tz, slots=slots)
        await availability.upsert_slots(str(doctor_id), date_str, tz, built)
        written += 1

    return {"message": "Availability applied.", "days_written": written}
