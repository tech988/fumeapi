from typing import Optional
from bson import ObjectId
from app.core.db import get_db
from app.utils.bson import oid


def _looks_like_objectid(s: str) -> bool:
    return isinstance(s, str) and len(s) == 24 and all(c in "0123456789abcdefABCDEF" for c in s)


def _basename(p: str) -> str:
    # "/a/b/c.png?x=1" -> "c.png"
    p = (p or "").split("?")[0].strip()
    if not p:
        return ""
    return p.split("/")[-1]


class ImageResolver:
    """
    Resolves DB 'image' field into a stable image_url.
    Supports:
      - image is ObjectId or ObjectId string
      - image is "/filename.png" legacy public path
    """

    def __init__(self, db, bucket_name: str = "images"):
        self.db = db
        self.files_col = db[f"{bucket_name}.files"]

    async def resolve_file_id(self, image_value) -> Optional[str]:
        # If already ObjectId
        if isinstance(image_value, ObjectId):
            return str(image_value)

        # If already ObjectId string
        if isinstance(image_value, str) and _looks_like_objectid(image_value):
            return str(oid(image_value))

        # If legacy "/file.png"
        if isinstance(image_value, str) and image_value.startswith("/"):
            name = _basename(image_value)
            if not name:
                return None
            row = await self.files_col.find_one({"filename": name}, {"_id": 1})
            return str(row["_id"]) if row else None

        return None

    async def to_url(self, image_value, api_base: str = "") -> Optional[str]:
        """
        Returns URL like: /api/images/<id> (or with api_base prefix)
        """
        fid = await self.resolve_file_id(image_value)
        if not fid:
            return None
        return f"{api_base}/api/images/{fid}".rstrip("/")
