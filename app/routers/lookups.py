from fastapi import APIRouter, Depends
from app.repos.lookups import LookupsRepo

router = APIRouter(prefix="/api/lookups", tags=["Lookups"])

@router.get("/cities")
async def cities(repo: LookupsRepo = Depends(LookupsRepo)):
    return {"data": await repo.cities()}


@router.get("/cities/master")
async def cities_master(repo: LookupsRepo = Depends(LookupsRepo)):
    return {"data": await repo.cities_master(), "meta": {"source": "lookup_catalog", "scope": "india"}}

@router.get("/specialties")
async def specialties(repo: LookupsRepo = Depends(LookupsRepo)):
    return {"data": await repo.specialties()}

@router.get("/languages")
async def languages(repo: LookupsRepo = Depends(LookupsRepo)):
    return {"data": await repo.languages()}
