# app/core/errors.py
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def http_error(status_code: int, code: str, message: str):
    raise APIError(status_code, code, message)


async def api_error_handler(request: Request, exc: APIError):
    # <-- this ensures top-level {"error": ...} (no "detail")
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
