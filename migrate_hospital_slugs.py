import argparse
import os
import re
from pymongo import MongoClient


def get_mongo():
    mongo_uri = os.environ["MONGO_URI"]
    db_name = os.getenv("MONGO_DB", "hb")
    client = MongoClient(mongo_uri)
    return client, client[db_name]


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def build_base(doc: dict) -> str:
    name = doc.get("name") or ""
    location = doc.get("location") or ""
    if name and location:
        return slugify(f"{name}-{location}")
    if name:
        return slugify(name)
    return ""


def ensure_unique_slug(col, base: str) -> str | None:
    if not base:
        return None
    slug = base
    suffix = 2
    while col.find_one({"slug": slug}, {"_id": 1}):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def main():
    parser = argparse.ArgumentParser(description="Backfill missing hospital slugs")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    client, db = get_mongo()
    col = db["hospitals"]

    query = {"$or": [{"slug": {"$exists": False}}, {"slug": None}, {"slug": ""}]}
    total = col.count_documents(query)

    if total == 0:
        print("No hospitals missing slugs. Nothing to migrate.")
        client.close()
        return

    print(f"Found {total} hospitals without slugs")

    if args.dry_run:
        sample = list(col.find(query, {"_id": 1, "name": 1, "location": 1}).limit(10))
        print("Sample candidates:")
        for doc in sample:
            base = build_base(doc)
            preview = ensure_unique_slug(col, base) if base else None
            print(f"- {doc.get('_id')} -> {preview}")
        print("Dry run complete")
        client.close()
        return

    updated = 0
    cursor = col.find(query)
    for doc in cursor:
        base = build_base(doc)
        slug = ensure_unique_slug(col, base)
        if not slug:
            continue
        col.update_one({"_id": doc.get("_id")}, {"$set": {"slug": slug}})
        updated += 1

    print("Hospital slug backfill complete")
    print(f"- updated: {updated}")
    client.close()


if __name__ == "__main__":
    main()
