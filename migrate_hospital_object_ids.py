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
    parser = argparse.ArgumentParser(description="Migrate hospital string _id to ObjectId")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    client, db = get_mongo()

    hospitals = list(db["hospitals"].find({"_id": {"$type": "string"}}))
    if not hospitals:
        print("No string _id hospitals found. Nothing to migrate.")
        client.close()
        return

    id_map: dict[str, ObjectId] = {}
    for h in hospitals:
        old_id = h.get("_id")
        if not isinstance(old_id, str):
            continue
        new_id = ObjectId()
        id_map[old_id] = new_id
        if not args.dry_run:
            h["_id"] = new_id
            db["hospitals"].insert_one(h)

    for old_id, new_id in id_map.items():
        if not args.dry_run:
            db["packages"].update_many(
                {"hospitals.hospitalId": old_id},
                {"$set": {"hospitals.$[h].hospitalId": new_id}},
                array_filters=[{"h.hospitalId": old_id}],
            )
            db["doctors"].update_many(
                {"affiliatedHospitals.id": old_id},
                {"$set": {"affiliatedHospitals.$[h].id": new_id}},
                array_filters=[{"h.id": old_id}],
            )
            db["doctors"].update_many(
                {"affiliatedHospitals.hospitalId": old_id},
                {"$set": {"affiliatedHospitals.$[h].hospitalId": new_id}},
                array_filters=[{"h.hospitalId": old_id}],
            )

    if not args.dry_run:
        db["hospitals"].delete_many({"_id": {"$in": list(id_map.keys())}})

    if args.dry_run:
        print("Dry run complete")
        print(f"- would migrate: {len(id_map)}")
    else:
        print("Hospital _id migration complete")
        print(f"- migrated: {len(id_map)}")
    client.close()


if __name__ == "__main__":
    main()
