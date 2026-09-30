import csv
import os
import re
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient, UpdateOne

SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_doctors.tsv")


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


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def normalize_name(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("–", "-").replace("—", "-")
    value = value.replace("'", "").replace("’", "").replace("`", "")
    value = re.sub(r"\s+", " ", value)
    return value


def title_specialty(value: str) -> str:
    value = (value or "").strip().lower()
    mapping = {
        "ent": "ENT",
        "icu": "ICU",
        "ccu": "CCU",
        "nicu": "NICU",
        "picu": "PICU",
        "opd": "OPD",
    }
    if value in mapping:
        return mapping[value]
    return value.replace("_", " ").replace("-", " ").title()


def parse_list(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split("|") if p.strip()]


def parse_int(raw: str) -> int | None:
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def build_hospital_lookup(db) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for h in db["hospitals"].find({}, {"_id": 1, "name": 1, "location": 1}):
        key = normalize_name(h.get("name"))
        if key:
            lookup[key] = {
                "id": h.get("_id"),
                "name": h.get("name"),
                "location": h.get("location"),
            }
    return lookup


def build_affiliations(raw: str, lookup: dict) -> list[dict]:
    items = []
    for name in parse_list(raw):
        key = normalize_name(name)
        info = lookup.get(key)
        items.append(
            {
                "id": info.get("id") if info else None,
                "name": info.get("name") if info else name,
                "location": info.get("location") if info else None,
            }
        )
    return [{k: v for k, v in x.items() if v is not None} for x in items]


def build_consultation_types(in_person: int | None, video: int | None, phone: int | None) -> list[dict]:
    items = []
    if in_person is not None:
        items.append(
            {"type": "in-person", "available": True, "fee": in_person})
    if video is not None:
        items.append({"type": "video", "available": True, "fee": video})
    if phone is not None:
        items.append({"type": "phone", "available": True, "fee": phone})
    return items


def main():
    rows = read_tsv(SEED_FILE)
    client, db = get_mongo()
    hospital_lookup = build_hospital_lookup(db)

    ops: list[UpdateOne] = []
    for i, row in enumerate(rows, 1):
        name = row.get("name") or ""
        slug = slugify(name)

        experience = parse_int(row.get("experience_years") or "")
        in_person = parse_int(row.get("fee_in_person") or "")
        video = parse_int(row.get("fee_video") or "")
        phone = parse_int(row.get("fee_phone") or "")

        affiliations = build_affiliations(
            row.get("hospitals") or "", hospital_lookup)
        location = affiliations[0].get("location") if affiliations else None

        doc = {
            "_id": ObjectId(),
            "slug": slug,
            "name": name,
            "specialty": title_specialty(row.get("specialty") or ""),
            "experience": experience,
            "languages": parse_list(row.get("languages") or ""),
            "consultationFee": in_person,
            "consultationTypes": build_consultation_types(in_person, video, phone),
            "affiliatedHospitals": affiliations,
            "location": location,
            "verified": True,
        }

        now = datetime.now(timezone.utc)
        set_doc = {k: v for k, v in doc.items() if k not in {"_id"}
                   and v is not None}
        set_doc["updated_at"] = now

        ops.append(
            UpdateOne(
                {"slug": slug},
                {
                    "$set": set_doc,
                    "$setOnInsert": {"_id": doc["_id"], "created_at": now, "seeded_at": now},
                },
                upsert=True,
            )
        )

    if ops:
        res = db["doctors"].bulk_write(ops, ordered=False)
        print("Seed complete")
        print(f"- total: {len(ops)}")
        print(f"- upserted: {res.upserted_count}")
        print(f"- modified: {res.modified_count}")

    client.close()


if __name__ == "__main__":
    main()
