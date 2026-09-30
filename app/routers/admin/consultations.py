from fastapi import APIRouter, Depends, Query

from app.core.deps import require_roles
from app.core.errors import http_error
from app.core.pagination import calc_has_more
from app.repos.consultations import ConsultationsRepo

router = APIRouter(prefix="/api/admin/consultations", tags=["Admin"])


@router.get("")
async def admin_list_consultations(
    status: str | None = None,
    consultation_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: ConsultationsRepo = Depends(ConsultationsRepo),
):
    data, total = await repo.admin_list(status, consultation_type, date_from, date_to, page, page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}


@router.get("/{id}")
async def admin_get_consultation(
    id: str,
    _admin=Depends(require_roles("admin")),
    repo: ConsultationsRepo = Depends(ConsultationsRepo),
):
    doc = await repo.admin_get(id)
    if not doc:
        http_error(404, "CONSULTATION_NOT_FOUND", "Consultation not found")
    return {"consultation": doc}
