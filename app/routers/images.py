# app/routes/images.py
import io
from bson import ObjectId
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.core.db import get_gridfs_bucket
from app.core.deps import get_current_user
from app.core.pagination import calc_has_more
from app.repos.images import ImagesRepo

router = APIRouter(prefix="/api/images", tags=["images"])

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_MB = 10  # change if you want
MAX_BYTES = MAX_MB * 1024 * 1024


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="file is required")

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type: {file.content_type}. Allowed: {sorted(ALLOWED_MIME)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File too large. Max {MAX_MB}MB")

    bucket = get_gridfs_bucket()

    def _put():
        return bucket.upload_from_stream(
            file.filename or "image",
            io.BytesIO(data),
            metadata={
                "contentType": file.content_type,
                "originalName": file.filename,
                "size": len(data),
            },
        )

    file_id = await run_in_threadpool(_put)

    return {
        "file_id": str(file_id),
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(data),
        "view_url": f"/api/images/{str(file_id)}",
    }


@router.post("/upload-auth")
async def upload_image_auth(
    file: UploadFile = File(...),
    entity_type: str | None = Form(None),
    entity_id: str | None = Form(None),
    user=Depends(get_current_user),
):
    if not file:
        raise HTTPException(status_code=400, detail="file is required")

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type: {file.content_type}. Allowed: {sorted(ALLOWED_MIME)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File too large. Max {MAX_MB}MB")

    bucket = get_gridfs_bucket()

    def _put():
        return bucket.upload_from_stream(
            file.filename or "image",
            io.BytesIO(data),
            metadata={
                "contentType": file.content_type,
                "originalName": file.filename,
                "size": len(data),
                "owner_user_id": str(user["_id"]),
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )

    file_id = await run_in_threadpool(_put)

    return {
        "file_id": str(file_id),
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(data),
        "view_url": f"/api/images/{str(file_id)}",
    }


@router.get("/mine")
async def list_my_images(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    repo: ImagesRepo = Depends(ImagesRepo),
):
    data, total = await repo.list_for_user(user_id=str(user["_id"]), page=page, page_size=page_size)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}


@router.get("/{file_id}")
async def view_image(file_id: str):
    try:
        oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file_id")

    bucket = get_gridfs_bucket()

    def _read():
        try:
            g = bucket.open_download_stream(oid)
        except Exception:
            return None

        content_type = (g.metadata or {}).get(
            "contentType", "application/octet-stream")
        filename = getattr(g, "filename", "file")
        blob = g.read()
        return blob, content_type, filename

    result = await run_in_threadpool(_read)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")

    blob, content_type, filename = result

    return StreamingResponse(
        io.BytesIO(blob),
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/{file_id}")
async def delete_image(file_id: str):
    try:
        oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file_id")

    bucket = get_gridfs_bucket()

    def _del():
        bucket.delete(oid)
        return True

    try:
        await run_in_threadpool(_del)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    return {"deleted": True, "file_id": file_id}


@router.delete("/{file_id}/owned")
async def delete_my_image(
    file_id: str,
    user=Depends(get_current_user),
    repo: ImagesRepo = Depends(ImagesRepo),
):
    try:
        oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file_id")

    meta = await repo.get_meta(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")

    owner = (meta.get("metadata") or {}).get("owner_user_id")
    if owner != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not allowed")

    bucket = get_gridfs_bucket()

    def _del():
        bucket.delete(oid)
        return True

    try:
        await run_in_threadpool(_del)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    return {"deleted": True, "file_id": file_id}
