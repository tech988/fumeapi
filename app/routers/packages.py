from fastapi import APIRouter, Depends, Query
from app.repos.packages import PackagesRepo
from app.core.errors import http_error
from app.core.pagination import calc_has_more

router = APIRouter(prefix="/api/packages", tags=["Packages"])


@router.get("")
async def list_packages(
    search: str | None = None,
    city_id: str | None = None,
    hospital_id: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str | None = None,
    category: str | None = None,
    repo: PackagesRepo = Depends(PackagesRepo),
):
    data, total = await repo.list_packages(search, city_id, hospital_id, price_min, price_max, page, page_size, sort, category)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}


@router.get("/search")
async def search_packages(
    q: str = Query(..., min_length=1),
    city_id: str | None = None,
    hospital_id: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str | None = None,
    category: str | None = None,
    repo: PackagesRepo = Depends(PackagesRepo),
):
    data, total = await repo.list_packages(q, city_id, hospital_id, price_min, price_max, page, page_size, sort, category)
    return {"data": data, "meta": {"total": total, "page": page, "page_size": page_size, "has_more": calc_has_more(total, page, page_size)}}


@router.get("/{id}")
async def package_detail(id: str, repo: PackagesRepo = Depends(PackagesRepo)):
    res = await repo.get_package_detail(id)
    if not res:
        http_error(404, "PACKAGE_NOT_FOUND", "Package not found")
    return res


@router.get("/{id}/compare")
async def package_compare(
    id: str,
    hospital_ids: str = Query(...,
                              description="comma separated 2-4 hospital ids"),
    repo: PackagesRepo = Depends(PackagesRepo),
):
    hospitals = [x.strip() for x in hospital_ids.split(",") if x.strip()]
    if len(hospitals) < 2:
        http_error(400, "COMPARE_MIN_2",
                   "Need at least 2 hospitals to compare")
    if len(hospitals) > 4:
        http_error(400, "COMPARE_MAX_4", "Max 4 hospitals can be compared")
    res = await repo.compare_offers(package_id_or_slug=id, hospital_ids=hospitals)
    if not res:
        http_error(404, "PACKAGE_NOT_FOUND", "Package not found")
    return res
