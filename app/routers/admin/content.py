from fastapi import APIRouter, Depends

from app.core.deps import require_roles
from app.core.errors import http_error
from app.repos.content import ContentRepo

router = APIRouter(prefix="/api/admin/content", tags=["Admin"])


@router.get("/{key}")
async def admin_get_content(
    key: str,
    _admin=Depends(require_roles("admin")),
    repo: ContentRepo = Depends(ContentRepo),
):
    doc = await repo.get_admin(key)
    if not doc:
        http_error(404, "CONTENT_NOT_FOUND", "Content not found")
    return {"content": doc}


@router.put("/{key}")
async def admin_update_content(
    key: str,
    payload: dict,
    _admin=Depends(require_roles("admin")),
    repo: ContentRepo = Depends(ContentRepo),
):
    doc = await repo.update(key, payload)
    return {"content": doc}
