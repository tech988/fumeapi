import csv
import mimetypes
import os
import re
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bson import ObjectId
from gridfs import GridFSBucket
from pymongo import MongoClient, UpdateOne

SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_hospitals.tsv")


def get_mongo():
    mongo_uri = os.environ["MONGO_URI"]
    db_name = os.getenv("MONGO_DB", "hb")
    client = MongoClient(mongo_uri)
    return client, client[db_name]


def get_bucket(db):
    return GridFSBucket(db, bucket_name="images")


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


def normalize_specialty(name: str) -> str:
    key = (name or "").strip().lower()
    mapping = {
        "ent": "ENT",
        "icu": "ICU",
        "ccu": "CCU",
        "nicu": "NICU",
        "picu": "PICU",
        "opd": "OPD",
        "ot": "OT",
    }
    if key in mapping:
        return mapping[key]
    key = key.replace("_", " ").replace("-", " ")
    return key.title()


def normalize_specialties(raw: str) -> list[str]:
    parts = [p.strip() for p in (raw or "").split("|") if p.strip()]
    return [normalize_specialty(p) for p in parts]


def normalize_facilities(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split("|") if p.strip()]


def parse_photo_urls(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split("|") if p.strip()]


def infer_type(name: str) -> str:
    label = (name or "").lower()
    if "clinic" in label:
        return "Clinic"
    if "centre" in label or "center" in label:
        return "Medical Centre"
    if "institute" in label:
        return "Institute"
    if "hospital" in label:
        return "Hospital"
    return "Hospital"


def build_address(row: dict) -> str:
    line1 = row.get("address_line1") or ""
    line2 = row.get("address_line2") or ""
    area = row.get("area") or ""
    city = row.get("city") or ""
    state = row.get("state") or ""
    pincode = row.get("pincode") or ""

    parts = [p for p in [line1, line2, area, city, state] if p]
    address = ", ".join(parts)
    if pincode:
        address = f"{address} - {pincode}" if address else pincode
    return address


def guess_extension(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    if ext:
        return ext
    if content_type:
        return mimetypes.guess_extension(content_type) or ""
    return ""


def fetch_image(url: str) -> tuple[bytes, str | None]:
    req = Request(url, headers={"User-Agent": "hb-seed/1.0"})
    with urlopen(req, timeout=30) as resp:
        content_type = resp.headers.get("Content-Type")
        return resp.read(), content_type


def get_or_upload_image(
    db,
    bucket: GridFSBucket,
    url: str,
    filename: str,
) -> str | None:
    existing = db["images.files"].find_one({"filename": filename}, {"_id": 1})
    if existing:
        return str(existing["_id"])

    try:
        blob, content_type = fetch_image(url)
    except Exception:
        return None

    if not blob:
        return None

    metadata = {"sourceUrl": url}
    if content_type:
        metadata["contentType"] = content_type

    file_id = bucket.upload_from_stream(filename, blob, metadata=metadata)
    return str(file_id)


def build_doc(row: dict, index: int, image_ids: Iterable[str]) -> dict:
    slug = slugify(f"{row.get('name', '')}-{row.get('city', '')}")
    image_ids = [x for x in image_ids if x]

    doc = {
        "_id": ObjectId(),
        "slug": slug,
        "name": row.get("name"),
        "type": infer_type(row.get("name")),
        "location": row.get("city"),
        "address": build_address(row),
        "phone": row.get("contact_phone"),
        "email": row.get("contact_email"),
        "specialties": normalize_specialties(row.get("specialties")),
        "facilities": normalize_facilities(row.get("facilities")),
        "area": row.get("area"),
        "city": row.get("city"),
        "state": row.get("state"),
        "pincode": row.get("pincode"),
    }

    if image_ids:
        doc["image"] = image_ids[0]
        doc["gallery"] = image_ids

    return doc


def main():
    rows = read_tsv(SEED_FILE)
    client, db = get_mongo()
    bucket = get_bucket(db)

    ops: list[UpdateOne] = []
    for i, row in enumerate(rows, 1):
        slug = slugify(f"{row.get('name', '')}-{row.get('city', '')}")
        photo_urls = parse_photo_urls(row.get("photos"))

        image_ids = []
        for idx, url in enumerate(photo_urls, 1):
            content_type = mimetypes.guess_type(url)[0]
            ext = guess_extension(url, content_type)
            filename = f"{slug}-{idx}{ext}" if ext else f"{slug}-{idx}"
            file_id = get_or_upload_image(db, bucket, url, filename)
            if file_id:
                image_ids.append(file_id)

        doc = build_doc(row, i, image_ids)
        now = datetime.now(timezone.utc)

        set_doc = {k: v for k, v in doc.items() if k not in {"_id"}}
        set_doc["updatedAt"] = now

        ops.append(
            UpdateOne(
                {"slug": slug},
                {
                    "$set": set_doc,
                    "$setOnInsert": {"_id": doc["_id"], "createdAt": now, "seededAt": now},
                },
                upsert=True,
            )
        )

    if ops:
        res = db["hospitals"].bulk_write(ops, ordered=False)
        print("Seed complete")
        print(f"- total: {len(ops)}")
        print(f"- upserted: {res.upserted_count}")
        print(f"- modified: {res.modified_count}")

    client.close()


if __name__ == "__main__":
    main()
