import argparse
import os
from bson import ObjectId
from pymongo import MongoClient


def get_mongo():
    mongo_uri = os.environ["MONGO_URI"]
    db_name = os.getenv("MONGO_DB", "hb")
    client = MongoClient(mongo_uri)
    return client, client[db_name]


def main():
    parser = argparse.ArgumentParser(description="Migrate doctor string _id to ObjectId")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    client, db = get_mongo()

    doctors = list(db["doctors"].find({"_id": {"$type": "string"}}))
    if not doctors:
        print("No string _id doctors found. Nothing to migrate.")
        client.close()
        return

    id_map: dict[str, ObjectId] = {}
    for d in doctors:
        old_id = d.get("_id")
        if not isinstance(old_id, str):
            continue
        new_id = ObjectId()
        id_map[old_id] = new_id
        if not args.dry_run:
            d["_id"] = new_id
            db["doctors"].insert_one(d)

    if args.dry_run:
        print("Dry run complete")
        print(f"- would migrate: {len(id_map)}")
        sample = list(id_map.items())[:10]
        if sample:
            print("Sample mappings:")
            for old_id, new_id in sample:
                print(f"- {old_id} -> {new_id}")
        client.close()
        return

    updated_bookings = 0
    updated_slots = 0
    updated_weekly = 0

    for old_id, new_id in id_map.items():
        new_id_str = str(new_id)

        res = db["bookings"].update_many(
            {"doctor_id": old_id},
            {"$set": {"doctor_id": new_id_str}},
        )
        updated_bookings += res.modified_count

        res = db["availability_slots"].update_many(
            {"doctor_id": old_id},
            {"$set": {"doctor_id": new_id_str}},
        )
        updated_slots += res.modified_count

        res = db["availability_weekly"].update_many(
            {"doctor_id": old_id},
            {"$set": {"doctor_id": new_id_str}},
        )
        updated_weekly += res.modified_count

    db["doctors"].delete_many({"_id": {"$in": list(id_map.keys())}})

    print("Doctor _id migration complete")
    print(f"- migrated: {len(id_map)}")
    print(f"- bookings updated: {updated_bookings}")
    print(f"- availability_slots updated: {updated_slots}")
    print(f"- availability_weekly updated: {updated_weekly}")
    client.close()


if __name__ == "__main__":
    main()
