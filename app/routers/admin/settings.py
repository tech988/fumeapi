from fastapi import APIRouter, Depends
from app.core.deps import require_roles
from app.repos.settings import SettingsRepo

router = APIRouter(prefix="/api/admin/settings", tags=["Admin"])

@router.get("")
async def get_settings(_admin=Depends(require_roles("admin")), repo: SettingsRepo = Depends(SettingsRepo)):
    return await repo.get()

@router.put("")
async def update_settings(payload: dict, _admin=Depends(require_roles("admin")), repo: SettingsRepo = Depends(SettingsRepo)):
    return await repo.update(payload)
