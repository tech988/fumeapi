from fastapi import Depends

from app.core.db import get_db
from app.core.errors import http_error
from app.utils.location_normalizer import normalize_india_location


class FiltersRepo:
    def __init__(self, db=Depends(get_db)):
        self.db = db
        self._entity_collections = {
            "doctors": "doctors",
            "hospitals": "hospitals",
            "insurance_partners": "insurance_partners",
        }

    def _collection_name(self, entity: str) -> str:
        name = self._entity_collections.get(entity)
        if not name:
            http_error(400, "INVALID_ENTITY", "entity must be doctors, hospitals, or insurance_partners")
        assert name
        return name

    async def location_facets(self, entity: str):
        col_name = self._collection_name(entity)
        col = self.db[col_name]

        projection = {
            "city": 1,
            "state": 1,
            "location": 1,
            "address": 1,
            "headquarters": 1,
            "country": 1,
        }

        counts: dict[str, int] = {}
        cur = col.find({}, projection)
        async for row in cur:
            normalized = normalize_india_location(
                city=row.get("city"),
                state=row.get("state"),
                location=row.get("location"),
                address=row.get("address"),
                headquarters=row.get("headquarters"),
                country=row.get("country"),
            )
            city = normalized.get("city")
            if not city:
                continue
            counts[city] = counts.get(city, 0) + 1

        data = [{"city": city, "count": count} for city, count in counts.items() if count > 0]
        data.sort(key=lambda x: x["city"].lower())
        return data

    async def locations_master(self):
        seen: dict[tuple[str, str], bool] = {}
        entities = ["doctors", "hospitals", "insurance_partners"]

        for entity in entities:
            col = self.db[self._collection_name(entity)]
            cur = col.find({}, {"city": 1, "state": 1, "location": 1, "address": 1, "headquarters": 1, "country": 1})
            async for row in cur:
                normalized = normalize_india_location(
                    city=row.get("city"),
                    state=row.get("state"),
                    location=row.get("location"),
                    address=row.get("address"),
                    headquarters=row.get("headquarters"),
                    country=row.get("country"),
                )
                city = normalized.get("city")
                if not city:
                    continue
                state = normalized.get("state") or ""
                seen[(city, state)] = True

        data = [{"city": city, "state": state or None} for city, state in seen.keys()]
        data.sort(key=lambda x: (x["city"].lower(), (x["state"] or "").lower()))
        return data
