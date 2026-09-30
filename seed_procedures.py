import csv
import os
import re
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_procedures.tsv")


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


def build_cost_breakdown(row: dict) -> dict:
    return {
        "surgery_paise": parse_int(row.get("cost_surgery_paise")),
        "hospital_stay_paise": parse_int(row.get("cost_hospital_stay_paise")),
        "medications_paise": parse_int(row.get("cost_medications_paise")),
        "tests_diagnostics_paise": parse_int(row.get("cost_tests_diagnostics_paise")),
        "other_charges_paise": parse_int(row.get("cost_other_charges_paise")),
    }


def compact_cost_breakdown(costs: dict) -> dict:
    return {k: v for k, v in costs.items() if v is not None}


def build_hospitals(row: dict, lookup: dict, price_min: int | None, price_max: int | None) -> list[dict]:
    items = []
    for raw_name in parse_list(row.get("hospitals")):
        key = normalize_name(raw_name)
        info = lookup.get(key)

        entry = {
            "hospitalId": info.get("id") if info else None,
            "name": info.get("name") if info else raw_name,
            "location": info.get("location") if info else None,
            "price": price_min,
            "priceRange": {"min": price_min, "max": price_max} if price_min is not None or price_max is not None else None,
        }
        items.append({k: v for k, v in entry.items() if v is not None})
    return items


def main():
    rows = read_tsv(SEED_FILE)
    client, db = get_mongo()
    lookup = build_hospital_lookup(db)

    ops: list[UpdateOne] = []
    for i, row in enumerate(rows, 1):
        name = row.get("procedure_name") or ""
        slug = slugify(name)

        price_min = parse_int(row.get("price_min"))
        price_max = parse_int(row.get("price_max"))
        duration_days = parse_int(row.get("duration_days"))

        doc = {
            "_id": f"pkg_seed_{i:03d}",
            "slug": slug,
            "name": name,
            "title": name,
            "category": "procedure",
            "description": row.get("notes"),
            "duration": f"{duration_days} days" if duration_days else None,
            "priceRange": {"min": price_min, "max": price_max} if price_min is not None or price_max is not None else None,
            "inclusions": parse_list(row.get("inclusions")),
            "exclusions": parse_list(row.get("exclusions")),
        }

        cost_breakdown = compact_cost_breakdown(build_cost_breakdown(row))
        if cost_breakdown:
            doc["costBreakdownPaise"] = cost_breakdown

        hospitals = build_hospitals(row, lookup, price_min, price_max)
        if hospitals:
            doc["hospitals"] = hospitals

        now = datetime.now(timezone.utc)
        set_doc = {k: v for k, v in doc.items() if k not in {"_id"}
                   and v is not None}
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
        res = db["packages"].bulk_write(ops, ordered=False)
        print("Seed complete")
        print(f"- total: {len(ops)}")
        print(f"- upserted: {res.upserted_count}")
        print(f"- modified: {res.modified_count}")

    client.close()


if __name__ == "__main__":
    main()
