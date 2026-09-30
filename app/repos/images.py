from fastapi import Depends

from app.core.db import get_db
from app.utils.bson import oid


class ImagesRepo:
    def __init__(self, db=Depends(get_db)):
        self.files = db["images.files"]

    async def get_meta(self, file_id: str):
        return await self.files.find_one({"_id": oid(file_id)})

    async def list_for_user(self, user_id: str, page: int, page_size: int):
        q = {"metadata.owner_user_id": user_id}
        cur = (
            self.files.find(q)
            .skip((page - 1) * page_size)
            .limit(page_size)
            .sort([("uploadDate", -1), ("_id", -1)])
        )
        items = []
        async for f in cur:
            file_id = str(f.get("_id"))
            metadata = f.get("metadata") or {}
            items.append({
                "file_id": file_id,
                "filename": f.get("filename"),
                "content_type": metadata.get("contentType"),
                "size": metadata.get("size") or f.get("length"),
                "upload_date": f.get("uploadDate").isoformat() if f.get("uploadDate") else None,
                "view_url": f"/api/images/{file_id}",
                "entity_type": metadata.get("entity_type"),
                "entity_id": metadata.get("entity_id"),
            })
        total = await self.files.count_documents(q)
        return items, total
