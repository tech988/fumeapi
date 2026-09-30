from fastapi import APIRouter, Depends, Query

from app.core.deps import require_roles
from app.core.errors import http_error
from app.core.pagination import calc_has_more
from app.repos.insurance import InsuranceRepo
from app.utils.bson import str_id


router = APIRouter(prefix="/api", tags=["Insurance"])


@router.get("/insurance")
async def list_insurance_plans(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    items, total = await repo.list_plans(q=q, page=page, page_size=page_size)
    return {
        "data": items,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": calc_has_more(total, page, page_size),
        },
    }


@router.get("/insurance/public")
async def list_public_insurance_plans(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    items, total = await repo.list_plans(q=q, page=page, page_size=page_size)
    return {
        "data": items,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": calc_has_more(total, page, page_size),
        },
    }


@router.get("/insurance/{id}")
async def get_insurance_plan(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    doc = await repo.get_plan(id)
    if not doc:
        http_error(404, "INSURANCE_NOT_FOUND", "Insurance plan not found")
    return {"data": str_id(doc)}


@router.get("/insurance/public/{id}")
async def get_public_insurance_plan(
    id: str,
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    doc = await repo.get_plan(id)
    if not doc:
        http_error(404, "INSURANCE_NOT_FOUND", "Insurance plan not found")
    return {"data": str_id(doc)}


@router.post("/insurance")
async def create_insurance_plan(
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    created = await repo.create_plan(payload)
    return created


@router.put("/insurance/{id}")
async def update_insurance_plan(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    updated = await repo.update_plan(id, payload)
    if not updated:
        http_error(404, "INSURANCE_NOT_FOUND", "Insurance plan not found")
    return updated


@router.delete("/insurance/{id}")
async def delete_insurance_plan(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: InsuranceRepo = Depends(InsuranceRepo),
):
    ok = await repo.delete_plan(id)
    if not ok:
        http_error(404, "INSURANCE_NOT_FOUND", "Insurance plan not found")
    return {"ok": True}
