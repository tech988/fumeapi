from typing import Any
from bson import ObjectId


def oid(s: str) -> ObjectId:
    return ObjectId(s)


def str_id(v: Any) -> Any:
    """
    Deep convert ObjectId -> str inside dict/list.
    Safe to call on any payload.
    """
    if v is None:
        return None

    if isinstance(v, ObjectId):
        return str(v)

    if isinstance(v, dict):
        return {k: str_id(val) for k, val in v.items()}

    if isinstance(v, list):
        return [str_id(x) for x in v]

    return v
