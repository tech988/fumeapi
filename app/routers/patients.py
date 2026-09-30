from fastapi import APIRouter, Depends, Query

from app.core.deps import require_roles
from app.core.errors import http_error
from app.core.pagination import calc_has_more
from app.repos.bookings import BookingsRepo
from app.repos.patients import PatientsRepo


router = APIRouter(prefix="/api", tags=["Patients"])


@router.get("/patients")
async def list_patients(
    q: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: PatientsRepo = Depends(PatientsRepo),
):
    items, total = await repo.list_patients(q=q, status=status, page=page, page_size=page_size)
    return {
        "data": items,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": calc_has_more(total, page, page_size),
        },
    }


@router.get("/patients/{id}")
async def get_patient(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: PatientsRepo = Depends(PatientsRepo),
):
    doc = await repo.get_patient(id)
    if not doc:
        http_error(404, "PATIENT_NOT_FOUND", "Patient not found")
    return {"data": doc}


@router.get("/patients/{id}/bookings")
async def list_patient_bookings(
    id: str,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    patients_repo: PatientsRepo = Depends(PatientsRepo),
    bookings_repo: BookingsRepo = Depends(BookingsRepo),
):
    patient = await patients_repo.get_patient(id)
    if not patient:
        http_error(404, "PATIENT_NOT_FOUND", "Patient not found")
    assert patient is not None

    data, total = await bookings_repo.admin_list_patient_bookings(
        patient_id=id,
        user_id=patient.get("user_id"),
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        "data": data,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": calc_has_more(total, page, page_size),
        },
    }


@router.get("/patient/me")
async def get_patient_me(
    user=Depends(require_roles("patient")),
    repo: PatientsRepo = Depends(PatientsRepo),
):
    doc = await repo.get_by_user_id(str(user["_id"]))
    if not doc:
        http_error(404, "PATIENT_NOT_FOUND", "Patient not found")
    return {"data": doc}


@router.patch("/patient/me")
async def update_patient_me(
    payload: dict,
    user=Depends(require_roles("patient")),
    repo: PatientsRepo = Depends(PatientsRepo),
):
    patch = dict(payload or {})
    for k in ("_id", "id", "user_id", "created_at", "updated_at"):
        patch.pop(k, None)
    updated = await repo.update_by_user_id(str(user["_id"]), patch)
    if not updated:
        http_error(404, "PATIENT_NOT_FOUND", "Patient not found")
    return {"data": updated}


@router.post("/patients")
async def create_patient(
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: PatientsRepo = Depends(PatientsRepo),
):
    created = await repo.create_patient(payload)
    return created


@router.put("/patients/{id}")
async def update_patient(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: PatientsRepo = Depends(PatientsRepo),
):
    updated = await repo.update_patient(id, payload)
    if not updated:
        http_error(404, "PATIENT_NOT_FOUND", "Patient not found")
    return updated


@router.delete("/patients/{id}")
async def delete_patient(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: PatientsRepo = Depends(PatientsRepo),
):
    ok = await repo.delete_patient(id)
    if not ok:
        http_error(404, "PATIENT_NOT_FOUND", "Patient not found")
    return {"ok": True}
