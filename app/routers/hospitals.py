from fastapi import APIRouter, Depends, Query
from app.repos.hospitals import HospitalsRepo
from app.repos.doctors import DoctorsRepo
from app.core.errors import http_error
from app.core.pagination import calc_has_more

router = APIRouter(prefix="/api/hospitals", tags=["Hospitals"])

@router.get("")
async def list_hospitals(
    search: str | None = None,
    city_id: str | None = None,
    specialty_ids: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    sort: str | None = None,
    repo: HospitalsRepo = Depends(HospitalsRepo),
):
    sp_list = [x.strip() for x in (specialty_ids or "").split(",") if x.strip()]
    data, total = await repo.list_hospitals(search=search, city_id=city_id, specialty_ids=sp_list, page=page, page_size=page_size, sort=sort)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/search")
async def search_hospitals(
    q: str = Query(..., min_length=1),
    city_id: str | None = None,
    specialty_ids: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    sort: str | None = None,
    repo: HospitalsRepo = Depends(HospitalsRepo),
):
    sp_list = [x.strip() for x in (specialty_ids or "").split(",") if x.strip()]
    data, total = await repo.list_hospitals(search=q, city_id=city_id, specialty_ids=sp_list, page=page, page_size=page_size, sort=sort)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.get("/{id}")
async def hospital_detail(
    id: str,
    repo: HospitalsRepo = Depends(HospitalsRepo),
    doctors_repo: DoctorsRepo = Depends(DoctorsRepo),
):
    doc = await repo.get_hospital_detail(id)
    if not doc:
        http_error(404, "HOSPITAL_NOT_FOUND", "Hospital not found")

    hospital_id = doc.get("_id") if isinstance(doc, dict) else None
    if hospital_id:
        doctors, _total = await doctors_repo.list_doctors(
            hospital_id=hospital_id,
            page=1,
            page_size=10,
        )
    else:
        doctors = []

    doctor_items = []
    for d in doctors:
        doctor_items.append({
            "id": d.get("id"),
            "slug": d.get("slug"),
            "name": d.get("name"),
            "specialty": d.get("specialty_label") or d.get("specialty"),
            "qualification": d.get("qualification"),
            "degrees": d.get("degrees") if isinstance(d.get("degrees"), list) else [],
            "experience": d.get("experience_years"),
            "image": d.get("image"),
        })

    hospital_payload = dict(doc or {})
    hospital_payload["id"] = hospital_payload.pop("_id", None)
    hospital_payload["doctors"] = doctor_items

    return {"hospital": hospital_payload}
