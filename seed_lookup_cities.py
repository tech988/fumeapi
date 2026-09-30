import os
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

from app.utils.india_city_catalog import INDIA_CITY_CATALOG


def get_mongo():
    mongo_uri = os.environ["MONGO_URI"]
    db_name = os.getenv("MONGO_DB", "hb")
    client = MongoClient(mongo_uri)
    return client, client[db_name]


def main():
    client, db = get_mongo()
    try:
        now = datetime.now(timezone.utc)
        ops: list[UpdateOne] = []
        for city in INDIA_CITY_CATALOG:
            code = city["code"]
            ops.append(
                UpdateOne(
                    {"code": code},
                    {
                        "$set": {
                            "label": city["label"],
                            "state": city.get("state"),
                            "country": city.get("country") or "India",
                            "active": True,
                            "updated_at": now,
                        },
                        "$setOnInsert": {"created_at": now},
                    },
                    upsert=True,
                )
            )

        if not ops:
            print("No city entries to seed")
            return

        res = db["lookups_cities"].bulk_write(ops, ordered=False)
        print("City lookup seed complete")
        print(f"- total: {len(ops)}")
        print(f"- upserted: {res.upserted_count}")
        print(f"- modified: {res.modified_count}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
