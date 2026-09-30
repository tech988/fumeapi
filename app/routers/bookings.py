from fastapi import APIRouter, Depends, Query, Body
from app.core.deps import require_roles, get_current_user
from app.repos.bookings import BookingsRepo
from app.repos.doctors import DoctorsRepo
from app.core.errors import http_error
from app.core.pagination import calc_has_more

router = APIRouter(prefix="/api", tags=["Booking"])

@router.post("/bookings")
async def create_booking(payload: dict, user=Depends(require_roles("patient")), repo: BookingsRepo = Depends(BookingsRepo)):
    created = await repo.create_booking(user_id=str(user["_id"]), payload=payload)
    return created

@router.get("/bookings")
async def list_bookings(
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    doctor_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    repo: BookingsRepo = Depends(BookingsRepo),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
):
    doctor_id_for_role = doctor_id
    if user["role"] == "doctor" and not doctor_id_for_role:
        doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
        if doctor:
            doctor_id_for_role = doctor.get("id") or doctor.get("_id")
    data, total = await repo.list_for_user(
        user_id=str(user["_id"]),
        role=user["role"],
        status=status,
        date_from=date_from,
        date_to=date_to,
        doctor_id=doctor_id_for_role,
        page=page,
        page_size=page_size,
    )
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/user/bookings")
async def list_user_bookings(
    doctor_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(require_roles("patient")),
    repo: BookingsRepo = Depends(BookingsRepo),
):
    data, total = await repo.list_for_user(
        user_id=str(user["_id"]),
        role=user["role"],
        status=status,
        date_from=date_from,
        date_to=date_to,
        doctor_id=doctor_id,
        page=page,
        page_size=page_size,
    )
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/doctor/bookings")
async def list_doctor_bookings(
    doctor_id: str = Query(..., min_length=1),
    q: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    date_range: str | None = Query(None, description="today|upcoming|past"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(require_roles("doctor")),
    repo: BookingsRepo = Depends(BookingsRepo),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
):
    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if doctor:
        linked_id = doctor.get("id") or doctor.get("_id")
        if linked_id and str(linked_id) != doctor_id:
            http_error(403, "FORBIDDEN", "doctor_id does not match your account")
    data, total = await repo.admin_list_doctor_bookings(
        doctor_id=doctor_id,
        q=q,
        status=status,
        date_from=date_from,
        date_to=date_to,
        date_range=date_range,
        page=page,
        page_size=page_size,
    )
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/bookings/{id}")
async def get_booking(id: str, user=Depends(get_current_user), repo: BookingsRepo = Depends(BookingsRepo)):
    doc = await repo.get_booking_for_user(booking_id=id, user_id=str(user["_id"]), role=user["role"])
    if not doc:
        http_error(404, "BOOKING_NOT_FOUND", "Booking not found")
    return doc

@router.patch("/bookings/{id}/cancel")
async def cancel_booking(id: str, user=Depends(require_roles("patient")), repo: BookingsRepo = Depends(BookingsRepo)):
    ok = await repo.cancel_booking(booking_id=id, user_id=str(user["_id"]))
    if not ok:
        http_error(404, "BOOKING_NOT_FOUND", "Booking not found or not yours")
    return {"message": "Booking cancelled."}

@router.patch("/bookings/{id}/reschedule")
async def reschedule_booking(
    id: str,
    payload: dict = Body(...),
    user=Depends(require_roles("patient")),
    repo: BookingsRepo = Depends(BookingsRepo),
):
    slot_start = payload.get("slot_start")
    slot_end = payload.get("slot_end")
    if not slot_start or not slot_end:
        http_error(400, "VALIDATION_ERROR", "slot_start and slot_end are required")
    updated = await repo.reschedule_booking(
        booking_id=id,
        user_id=str(user["_id"]),
        slot_start=str(slot_start),
        slot_end=str(slot_end),
    )
    if not updated:
        http_error(404, "BOOKING_NOT_FOUND", "Booking not found or not yours")
    return {"booking": updated}

@router.patch("/doctor/bookings/{id}/confirm")
async def doctor_confirm_booking(
    id: str,
    user=Depends(require_roles("doctor")),
    repo: BookingsRepo = Depends(BookingsRepo),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
):
    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if not doctor:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doctor
    doctor_id = doctor.get("id") or doctor.get("_id")
    updated = await repo.doctor_update_status(booking_id=id, doctor_id=doctor_id, status="confirmed")
    if not updated:
        http_error(404, "BOOKING_NOT_FOUND", "Booking not found")
    return {"booking": updated}

@router.patch("/doctor/bookings/{id}/complete")
async def doctor_complete_booking(
    id: str,
    user=Depends(require_roles("doctor")),
    repo: BookingsRepo = Depends(BookingsRepo),
    doctors: DoctorsRepo = Depends(DoctorsRepo),
):
    doctor = await doctors.get_doctor_by_user_id(str(user["_id"]))
    if not doctor:
        http_error(404, "DOCTOR_NOT_FOUND", "Doctor not found")
    assert doctor
    doctor_id = doctor.get("id") or doctor.get("_id")
    updated = await repo.doctor_update_status(booking_id=id, doctor_id=doctor_id, status="completed")
    if not updated:
        http_error(404, "BOOKING_NOT_FOUND", "Booking not found")
    return {"booking": updated}
