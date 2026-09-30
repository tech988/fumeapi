import json
import time
from typing import Any, Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.db import get_db


def _looks_like_objectid(s: str) -> bool:
    return isinstance(s, str) and len(s) == 24 and all(c in "0123456789abcdefABCDEF" for c in s)


def _basename(p: str) -> str:
    p = (p or "").split("?")[0].strip()
    if not p:
        return ""
    return p.split("/")[-1]


class ImageUrlMiddleware(BaseHTTPMiddleware):
    """
    Global middleware:
    - For every JSON response, replaces any key named 'image' with a FULL URL:
        https://<host>/api/images/<id>
      Supports:
        - image is 24-hex string
        - image is '/file.png' legacy path (lookup in images.files by filename)
    """

    def __init__(
        self,
        app,
        bucket_name: str = "images",
        key_name: str = "image",
        url_path_prefix: str = "/api/images/",
        cache_ttl_seconds: int = 600,
        max_body_bytes: int = 6_000_000,
    ):
        super().__init__(app)
        self.bucket_name = bucket_name
        self.key_name = key_name
        self.url_path_prefix = url_path_prefix
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_body_bytes = max_body_bytes
        # filename -> (fid, expires_at)
        self._cache: Dict[str, Tuple[str, float]] = {}

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        ctype = (response.headers.get("content-type") or "").lower()
        if "application/json" not in ctype:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
            if len(body) > self.max_body_bytes:
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        if not body:
            return response

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # ✅ Full base url from current request (includes scheme + host)
        # Example: "http://127.0.0.1:8000"
        base_url = str(request.base_url).rstrip("/")

        payload = await self._replace_key_everywhere(payload, base_url)

        headers = dict(response.headers)
        headers.pop("content-length", None)

        return Response(
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
        )

    async def _file_id_for_filename(self, filename: str) -> Optional[str]:
        now = time.time()
        cached = self._cache.get(filename)
        if cached and cached[1] > now:
            return cached[0]

        db = get_db()
        files_col = db[f"{self.bucket_name}.files"]
        row = await files_col.find_one({"filename": filename}, {"_id": 1})
        if not row:
            return None

        fid = str(row["_id"])
        self._cache[filename] = (fid, now + self.cache_ttl_seconds)
        return fid

    async def _resolve_image_to_full_url(self, value: Any, base_url: str) -> Optional[str]:
        # already absolute url -> keep
        if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
            return value

        # objectid string -> full url
        if isinstance(value, str) and _looks_like_objectid(value):
            return f"{base_url}{self.url_path_prefix}{value}"

        # legacy '/file.png' -> lookup by filename -> full url
        if isinstance(value, str) and value.startswith("/"):
            name = _basename(value)
            if not name:
                return None
            fid = await self._file_id_for_filename(name)
            if fid:
                return f"{base_url}{self.url_path_prefix}{fid}"

        return None

    async def _replace_key_everywhere(self, obj: Any, base_url: str) -> Any:
        if isinstance(obj, dict):
            if self.key_name in obj:
                new_url = await self._resolve_image_to_full_url(obj.get(self.key_name), base_url)
                if new_url:
                    obj[self.key_name] = new_url

            for k, v in list(obj.items()):
                if isinstance(v, (dict, list)):
                    obj[k] = await self._replace_key_everywhere(v, base_url)
            return obj

        if isinstance(obj, list):
            return [await self._replace_key_everywhere(x, base_url) if isinstance(x, (dict, list)) else x for x in obj]

        return obj
