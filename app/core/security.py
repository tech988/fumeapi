import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt

from app.core.config import settings

_BCRYPT_MAX_BYTES = 72


def _normalize_password(password: str) -> str:
    """
    bcrypt only supports up to 72 bytes. For longer passwords,
    pre-hash using SHA-256 to a fixed-length string.
    """
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) <= _BCRYPT_MAX_BYTES:
        return password
    # Pre-hash -> hex string length 64 chars
    return hashlib.sha256(pw_bytes).hexdigest()


def hash_password(password: str) -> str:
    normalized = _normalize_password(password).encode("utf-8")
    return bcrypt.hashpw(normalized, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    normalized = _normalize_password(password).encode("utf-8")
    return bcrypt.checkpw(normalized, password_hash.encode("utf-8"))


def _now():
    return datetime.now(timezone.utc)


def create_access_token(sub: str, role: str) -> str:
    exp = _now() + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    payload = {"sub": sub, "role": role, "type": "access", "exp": exp}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def create_refresh_token(sub: str, role: str) -> str:
    exp = _now() + timedelta(days=settings.REFRESH_TOKEN_DAYS)
    payload = {"sub": sub, "role": role, "type": "refresh", "exp": exp}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
