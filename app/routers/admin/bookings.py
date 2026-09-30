from fastapi import APIRouter, Depends, Query
from app.core.deps import require_roles
from app.repos.bookings import BookingsRepo
from app.core.pagination import calc_has_more

router = APIRouter(prefix="/api/admin/bookings", tags=["Admin"])

@router.get("")
async def admin_list_bookings(
    status: str | None = None,
    doctor_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: BookingsRepo = Depends(BookingsRepo),
):
    data, total = await repo.admin_list(status, doctor_id, date_from, date_to, page, page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/doctor")
async def admin_list_doctor_bookings(
    doctor_id: str = Query(..., min_length=1),
    q: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    date_range: str | None = Query(None, description="today|upcoming|past"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: BookingsRepo = Depends(BookingsRepo),
):
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

@router.patch("/{id}")
async def admin_update_booking(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: BookingsRepo = Depends(BookingsRepo),
):
    return await repo.admin_update_booking(id, payload)

@router.post("/{id}/resend-confirmation")
async def resend_confirmation(
    id: str,
    _admin=Depends(require_roles("admin")),
):
    return {"message": "Confirmation resend queued."}
