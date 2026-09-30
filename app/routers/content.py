from fastapi import APIRouter, Depends

from app.core.errors import http_error
from app.repos.content import ContentRepo

router = APIRouter(prefix="/api/content", tags=["Content"])


@router.get("/{key}")
async def get_content(key: str, repo: ContentRepo = Depends(ContentRepo)):
    doc = await repo.get_public(key)
    if not doc:
        http_error(404, "CONTENT_NOT_FOUND", "Content not found")
    return {"content": doc}
