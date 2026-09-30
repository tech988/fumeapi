from fastapi import APIRouter, Depends
from app.repos.insurance import InsuranceRepo
from app.core.errors import http_error

router = APIRouter(prefix="/api", tags=["Insurance"])

@router.get("/insurance-partners")
async def list_partners(repo: InsuranceRepo = Depends(InsuranceRepo)):
    return {"data": await repo.list_partners()}

@router.post("/insurance/leads")
async def create_lead(payload: dict, repo: InsuranceRepo = Depends(InsuranceRepo)):
    created = await repo.create_lead(payload)
    if created is None:
        http_error(404, "PARTNER_NOT_FOUND", "Partner not found")
    return created
