import os

from pymongo import MongoClient

from app.utils.location_normalizer import normalize_india_location


def get_mongo():
    mongo_uri = os.environ["MONGO_URI"]
    db_name = os.getenv("MONGO_DB", "hb")
    client = MongoClient(mongo_uri)
    return client, client[db_name]


def backfill_collection(db, collection_name: str, fields: dict[str, str]):
    col = db[collection_name]
    total = 0
    updated = 0
    unresolved = 0

    projection = {
        "city": 1,
        "state": 1,
        "country": 1,
        fields.get("location", "location"): 1,
        fields.get("address", "address"): 1,
        fields.get("headquarters", "headquarters"): 1,
    }

    for doc in col.find({}, projection):
        total += 1
        normalized = normalize_india_location(
            city=doc.get("city"),
            state=doc.get("state"),
            location=doc.get(fields.get("location", "location")),
            address=doc.get(fields.get("address", "address")),
            headquarters=doc.get(fields.get("headquarters", "headquarters")),
            country=doc.get("country"),
        )

        patch = {}
        if normalized.get("city"):
            patch["city"] = normalized["city"]
        if normalized.get("state"):
            patch["state"] = normalized["state"]
        if normalized.get("country"):
            patch["country"] = normalized["country"]

        if not patch.get("city"):
            unresolved += 1
            continue

        col.update_one({"_id": doc["_id"]}, {"$set": patch})
        updated += 1

    return {"total": total, "updated": updated, "unresolved": unresolved}


def main():
    client, db = get_mongo()
    try:
        summary = {
            "doctors": backfill_collection(
                db,
                "doctors",
                {"location": "location", "address": "address", "headquarters": "headquarters"},
            ),
            "hospitals": backfill_collection(
                db,
                "hospitals",
                {"location": "location", "address": "address", "headquarters": "headquarters"},
            ),
            "insurance_partners": backfill_collection(
                db,
                "insurance_partners",
                {"location": "location", "address": "address", "headquarters": "headquarters"},
            ),
        }

        print("India location backfill complete")
        for name, stats in summary.items():
            print(f"- {name}: total={stats['total']} updated={stats['updated']} unresolved={stats['unresolved']}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
