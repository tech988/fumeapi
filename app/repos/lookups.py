from fastapi import Depends
from app.core.db import get_db
from app.utils.india_city_catalog import INDIA_CITY_CATALOG

class LookupsRepo:
    def __init__(self, db=Depends(get_db)):
        self.cities_col = db["lookups_cities"]
        self.spec_col = db["lookups_specialties"]
        self.lang_col = db["lookups_languages"]

    async def cities(self):
        cur = self.cities_col.find({"active": {"$ne": False}}).sort("label", 1)
        rows = [
            {
                "id": str(d["_id"]),
                "code": d.get("code"),
                "label": d.get("label"),
                "state": d.get("state"),
                "country": d.get("country") or "India",
            }
            async for d in cur
            if d.get("label")
        ]
        if rows:
            return rows

        return [
            {
                "id": f"city-{item['code']}",
                "code": item["code"],
                "label": item["label"],
                "state": item.get("state"),
                "country": item.get("country") or "India",
            }
            for item in INDIA_CITY_CATALOG
        ]

    async def cities_master(self):
        data = await self.cities()
        return [{"code": x.get("code"), "label": x.get("label"), "state": x.get("state"), "country": x.get("country")} for x in data]

    async def specialties(self):
        cur = self.spec_col.find({}).sort("label", 1)
        return [{"id": str(d["_id"]), "code": d.get("code"), "label": d.get("label")} async for d in cur]

    async def languages(self):
        cur = self.lang_col.find({}).sort("label", 1)
        return [{"id": str(d["_id"]), "code": d.get("code"), "label": d.get("label")} async for d in cur]
