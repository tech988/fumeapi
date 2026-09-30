from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, UploadFile, File
from app.core.deps import require_roles
from app.repos.hospitals import HospitalsRepo
from app.core.pagination import calc_has_more
from app.core.errors import http_error
from app.utils.csv_import import parse_csv_bytes

router = APIRouter(prefix="/api/admin/hospitals", tags=["Admin"])

@router.get("")
async def list_admin_hospitals(
    search: str | None = None,
    city_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: HospitalsRepo = Depends(HospitalsRepo),
):
    data, total = await repo.admin_list(search=search, city_id=city_id, page=page, page_size=page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.post("")
async def create_hospital(payload: dict, _admin=Depends(require_roles("admin")), repo: HospitalsRepo = Depends(HospitalsRepo)):
    payload["created_at"] = datetime.now(timezone.utc)
    payload["updated_at"] = datetime.now(timezone.utc)
    doc = await repo.create(payload)
    return {"hospital": {"id": str(doc["_id"]), **{k:v for k,v in doc.items() if k != "_id"}}}

@router.put("/{id}")
async def update_hospital(id: str, payload: dict, _admin=Depends(require_roles("admin")), repo: HospitalsRepo = Depends(HospitalsRepo)):
    payload["updated_at"] = datetime.now(timezone.utc)
    doc = await repo.update(id, payload)
    if not doc:
        http_error(404, "HOSPITAL_NOT_FOUND", "Hospital not found")
        return
    assert doc is not None
    return {"hospital": {"id": str(doc["_id"]), **{k:v for k,v in doc.items() if k != "_id"}}}

@router.post("/import")
async def import_hospitals(file: UploadFile = File(...), _admin=Depends(require_roles("admin")), repo: HospitalsRepo = Depends(HospitalsRepo)):
    data = await file.read()
    rows = parse_csv_bytes(data)
    inserted = 0
    for r in rows:
        r["created_at"] = datetime.now(timezone.utc)
        r["updated_at"] = datetime.now(timezone.utc)
        await repo.create(r)
        inserted += 1
    return {"message": "Imported", "inserted": inserted}


@router.delete("/{id}")
async def delete_hospital(id: str, _admin=Depends(require_roles("admin")), repo: HospitalsRepo = Depends(HospitalsRepo)):
    ok = await repo.delete(id)
    if not ok:
        http_error(404, "HOSPITAL_NOT_FOUND", "Hospital not found")
    return {"ok": True}
