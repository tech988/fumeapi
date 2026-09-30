from fastapi import APIRouter, Depends, Query

from app.repos.filters import FiltersRepo


router = APIRouter(prefix="/api", tags=["Filters"])


@router.get("/filters/locations")
async def locations_facets(
    entity: str = Query(..., description="doctors|hospitals|insurance_partners"),
    repo: FiltersRepo = Depends(FiltersRepo),
):
    data = await repo.location_facets(entity=entity)
    return {
        "data": data,
        "meta": {
            "entity": entity,
            "sorted": "alpha",
            "merged": "city",
        },
    }


@router.get("/locations/master")
async def locations_master(repo: FiltersRepo = Depends(FiltersRepo)):
    return {"data": await repo.locations_master()}
