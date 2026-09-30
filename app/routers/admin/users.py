from fastapi import APIRouter, Depends, Query
from app.core.deps import require_roles
from app.repos.users import UsersRepo
from app.core.pagination import calc_has_more

router = APIRouter(prefix="/api/admin/users", tags=["Admin"])

@router.get("")
async def list_users(
    role: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(require_roles("admin")),
    repo: UsersRepo = Depends(UsersRepo),
):
    data, total = await repo.list_users(role, status, page, page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}

@router.patch("/{id}")
async def update_user(
    id: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: UsersRepo = Depends(UsersRepo),
):
    u = await repo.update_user(id, payload)
    return {"user": {"id": str(u["_id"]), "role": u.get("role"), "status": u.get("status"), "full_name": u.get("full_name"), "email": u.get("email"), "phone": u.get("phone")}}
