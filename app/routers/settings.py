from fastapi import APIRouter, Depends

from app.repos.settings import SettingsRepo


router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("")
async def get_public_settings(repo: SettingsRepo = Depends(SettingsRepo)):
    return await repo.get()
