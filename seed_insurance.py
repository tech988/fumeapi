import csv
import os
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_insurance.tsv")


def get_mongo():
    mongo_uri = os.environ["MONGO_URI"]
    db_name = os.getenv("MONGO_DB", "hb")
    client = MongoClient(mongo_uri)
    return client, client[db_name]


def read_tsv(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return [
            {k.strip(): (v.strip() if isinstance(v, str) else v)
             for k, v in row.items()}
            for row in reader
        ]


def null_if_publicly_listed(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered in {"not publicly listed", "not listed", "n/a", "na"}:
        return None
    return value


def build_doc(row: dict) -> dict:
    return {
        "name": row.get("name"),
        "logo_url": row.get("logo_url"),
        "summary": row.get("summary"),
        "contact_email": null_if_publicly_listed(row.get("contact_email")),
        "contact_phone": null_if_publicly_listed(row.get("contact_phone")),
    }


def main():
    rows = read_tsv(SEED_FILE)
    client, db = get_mongo()

    ops: list[UpdateOne] = []
    for row in rows:
        name = row.get("name")
        if not name:
            continue

        doc = build_doc(row)
        now = datetime.now(timezone.utc)

        set_doc = {k: v for k, v in doc.items() if v is not None}
        set_doc["updated_at"] = now

        ops.append(
            UpdateOne(
                {"name": name},
                {
                    "$set": set_doc,
                    "$setOnInsert": {"created_at": now, "seeded_at": now},
                },
                upsert=True,
            )
        )

    if ops:
        res = db["insurance_partners"].bulk_write(ops, ordered=False)
        print("Seed complete")
        print(f"- total: {len(ops)}")
        print(f"- upserted: {res.upserted_count}")
        print(f"- modified: {res.modified_count}")

    client.close()


if __name__ == "__main__":
    main()
