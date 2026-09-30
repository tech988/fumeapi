import json
from typing import Any
from fastapi.responses import JSONResponse

try:
    from bson import ObjectId
    from bson.decimal128 import Decimal128
except Exception:
    ObjectId = None  # type: ignore
    Decimal128 = None  # type: ignore


def _convert_bson(obj: Any):
    # ObjectId -> str
    if ObjectId is not None and isinstance(obj, ObjectId):
        return str(obj)

    # Decimal128 -> float/string (choose one)
    if Decimal128 is not None and isinstance(obj, Decimal128):
        return float(obj.to_decimal())

    # datetime is JSON-serializable by FastAPI usually, but keep if needed

    if isinstance(obj, dict):
        return {k: _convert_bson(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_convert_bson(x) for x in obj]

    return obj


class BSONJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        safe = _convert_bson(content)
        return json.dumps(safe, ensure_ascii=False).encode("utf-8")
