from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from app.core.deps import require_roles
from app.repos.insurance import InsuranceRepo
from app.core.pagination import calc_has_more
from app.core.errors import http_error

router = APIRouter(prefix="/api/admin", tags=["Admin"])

@router.get("/insurance-partners")
async def admin_list_partners(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    data, total = await repo.admin_list_partners(page, page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.post("/insurance-partners")
async def create_partner(payload: dict, _admin=Depends(require_roles("admin")), repo: InsuranceRepo = Depends(InsuranceRepo)):
    payload["created_at"] = datetime.now(timezone.utc)
    payload["updated_at"] = datetime.now(timezone.utc)
    doc = await repo.create_partner(payload)
    return {"partner": {"id": str(doc["_id"]), **{k:v for k,v in payload.items() if k != "_id"}}}

@router.put("/insurance-partners/{id}")
async def update_partner(id: str, payload: dict, _admin=Depends(require_roles("admin")), repo: InsuranceRepo = Depends(InsuranceRepo)):
    payload["updated_at"] = datetime.now(timezone.utc)
    doc = await repo.update_partner(id, payload)
    return {"partner": {"id": str(doc["_id"]), **{k:v for k,v in doc.items() if k != "_id"}}}


@router.delete("/insurance-partners/{id}")
async def delete_partner(id: str, _admin=Depends(require_roles("admin")), repo: InsuranceRepo = Depends(InsuranceRepo)):
    ok = await repo.delete_partner(id)
    if not ok:
        http_error(404, "PARTNER_NOT_FOUND", "Partner not found")
    return {"ok": True}

@router.get("/insurance-leads")
async def admin_list_leads(
    partner_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    data, total = await repo.admin_list_leads(partner_id, status, date_from, date_to, page, page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.put("/insurance-leads/{id}")
async def admin_update_lead(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    doc = await repo.admin_update_lead(id, payload)
    return {"lead": {"id": str(doc["_id"]), **{k:v for k,v in doc.items() if k != "_id"}}}


@router.patch("/insurance-leads/{id}")
async def admin_patch_lead(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    doc = await repo.admin_update_lead(id, payload)
    return {"lead": {"id": str(doc["_id"]), **{k:v for k,v in doc.items() if k != "_id"}}}


@router.delete("/insurance-leads/{id}")
async def admin_delete_lead(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    ok = await repo.delete_lead(id)
    if not ok:
        http_error(404, "LEAD_NOT_FOUND", "Lead not found")
    return {"ok": True}
