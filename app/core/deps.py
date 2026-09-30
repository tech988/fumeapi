from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from app.core.security import decode_token
from app.core.errors import http_error
from app.repos.users import UsersRepo

bearer = HTTPBearer(auto_error=False)

async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    users: UsersRepo = Depends(UsersRepo),
):
    if not creds:
        http_error(401, "AUTH_REQUIRED", "Authorization token required")

    token = creds.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            http_error(401, "INVALID_TOKEN", "Invalid access token")
    except JWTError:
        http_error(401, "INVALID_TOKEN", "Invalid token")

    user = await users.get_by_id(payload["sub"])
    if not user:
        http_error(401, "USER_NOT_FOUND", "User not found")
    if user.get("status") != "active":
        http_error(423, "USER_DISABLED", "User is disabled")
    return user

def require_roles(*roles: str):
    async def _guard(user=Depends(get_current_user)):
        if user.get("role") not in roles:
            http_error(403, "FORBIDDEN", "Insufficient permissions")
        return user
    return _guard
