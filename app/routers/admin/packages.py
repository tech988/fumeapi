from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, UploadFile, File
from app.core.deps import require_roles
from app.repos.packages import PackagesRepo
from app.core.pagination import calc_has_more
from app.core.errors import http_error
from app.utils.csv_import import parse_csv_bytes

router = APIRouter(prefix="/api/admin/packages", tags=["Admin"])


@router.get("")
async def list_admin_packages(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: PackagesRepo = Depends(PackagesRepo),
):
    data, total = await repo.admin_list(page=page, page_size=page_size, search=search)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}


@router.post("")
async def create_package(payload: dict, _admin=Depends(require_roles("admin")), repo: PackagesRepo = Depends(PackagesRepo)):
    payload["created_at"] = datetime.now(timezone.utc)
    payload["updated_at"] = datetime.now(timezone.utc)
    doc = await repo.create(payload)
    return {"package": {"id": str(doc["_id"]), **{k: v for k, v in doc.items() if k != "_id"}}}


@router.put("/{id}")
async def update_package(id: str, payload: dict, _admin=Depends(require_roles("admin")), repo: PackagesRepo = Depends(PackagesRepo)):
    payload["updated_at"] = datetime.now(timezone.utc)
    doc = await repo.update(id, payload)
    if not doc:
        http_error(404, "PACKAGE_NOT_FOUND", "Package not found")
        return
    assert doc is not None
    return {"package": {"id": str(doc["_id"]), **{k: v for k, v in doc.items() if k != "_id"}}}


@router.post("/import")
async def import_packages(file: UploadFile = File(...), _admin=Depends(require_roles("admin")), repo: PackagesRepo = Depends(PackagesRepo)):
    data = await file.read()
    rows = parse_csv_bytes(data)
    inserted = 0
    for r in rows:
        # Note: CSV imports for nested `offers` should be expanded in your real template.
        r["created_at"] = datetime.now(timezone.utc)
        r["updated_at"] = datetime.now(timezone.utc)
        await repo.create(r)
        inserted += 1
    return {"message": "Imported", "inserted": inserted}


@router.delete("/{id}")
async def delete_package(id: str, _admin=Depends(require_roles("admin")), repo: PackagesRepo = Depends(PackagesRepo)):
    ok = await repo.delete(id)
    if not ok:
        http_error(404, "PACKAGE_NOT_FOUND", "Package not found")
    return {"ok": True}
