from fastapi import APIRouter, Depends

from app.repos.consultations import ConsultationsRepo

router = APIRouter(prefix="/api", tags=["Consultation"])


@router.post("/consultations")
async def create_consultation(payload: dict, repo: ConsultationsRepo = Depends(ConsultationsRepo)):
    return await repo.create_request(payload)
