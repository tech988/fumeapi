import argparse
import os
from pymongo import MongoClient


FIELD_MAP = {
    "consultation_fee": "consultationFee",
    "consultation_types": "consultationTypes",
    "created_at": "createdAt",
    "updated_at": "updatedAt",
    "seeded_at": "seededAt",
    "sub_specialty": "subSpecialty",
    "review_count": "reviewCount",
    "affiliated_hospitals": "affiliatedHospitals",
}


def get_mongo():
    mongo_uri = os.environ["MONGO_URI"]
    db_name = os.getenv("MONGO_DB", "hb")
    client = MongoClient(mongo_uri)
    return client, client[db_name]


def build_query():
    return {"$or": [{k: {"$exists": True}} for k in FIELD_MAP.keys()]}


def main():
    parser = argparse.ArgumentParser(description="Migrate doctor fields to camelCase")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    client, db = get_mongo()
    query = build_query()

    total = db["doctors"].count_documents(query)
    if total == 0:
        print("No doctor documents with snake_case fields found.")
        client.close()
        return

    print(f"Found {total} doctor documents to migrate")

    if args.dry_run:
        sample = list(db["doctors"].find(query, {"_id": 1}).limit(10))
        ids = [str(d.get("_id")) for d in sample]
        print("Sample IDs:")
        for _id in ids:
            print(f"- {_id}")
        print("Dry run complete")
        client.close()
        return

    updated = 0
    cursor = db["doctors"].find(query)
    for doc in cursor:
        set_doc = {}
        unset_doc = {}
        for src, dest in FIELD_MAP.items():
            if src in doc and dest not in doc:
                set_doc[dest] = doc.get(src)
            if src in doc:
                unset_doc[src] = ""

        if not set_doc and not unset_doc:
            continue

        update = {}
        if set_doc:
            update["$set"] = set_doc
        if unset_doc:
            update["$unset"] = unset_doc

        db["doctors"].update_one({"_id": doc.get("_id")}, update)
        updated += 1

    print("Doctor field migration complete")
    print(f"- updated: {updated}")
    client.close()


if __name__ == "__main__":
    main()
