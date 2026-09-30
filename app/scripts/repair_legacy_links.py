import argparse
import asyncio
from collections import Counter

from app.core.db import close_mongo, connect_mongo, get_db
from app.repos.bookings import BookingsRepo
from app.repos.doctors import DoctorsRepo
from app.repos.packages import PackagesRepo
from app.utils.bson import str_id


async def rebuild_hospital_backlinks(*, apply_changes: bool):
    db = get_db()
    doctors_repo = DoctorsRepo(db)
    packages_repo = PackagesRepo(db)
    hospitals = db["hospitals"]

    doctor_count = await db["doctors"].count_documents({})
    package_count = await db["packages"].count_documents({})

    if apply_changes:
        await hospitals.update_many({}, {"$set": {"doctors": [], "packages": []}})

        async for doctor in db["doctors"].find({}):
            await doctors_repo._sync_hospital_backlinks(str_id(doctor))

        async for package in db["packages"].find({}):
            await packages_repo._sync_hospital_backlinks(str_id(package))

    return {
        "doctor_records_scanned": doctor_count,
        "package_records_scanned": package_count,
        "mode": "apply" if apply_changes else "dry-run",
    }


async def backfill_booking_patient_summaries(*, apply_changes: bool):
    db = get_db()
    bookings_repo = BookingsRepo(db)
    bookings = db["bookings"]

    updated = 0
    scanned = 0

    async for booking in bookings.find({}):
        scanned += 1
        booking_view = str_id(booking)
        patient_summary = await bookings_repo._resolve_patient_summary(booking_view)

        patient_payload = booking.get("patient") if isinstance(booking.get("patient"), dict) else {}
        next_patient = dict(patient_payload)
        changed = False

        if patient_summary["name"] and next_patient.get("full_name") != patient_summary["name"]:
            next_patient["full_name"] = patient_summary["name"]
            next_patient["name"] = patient_summary["name"]
            changed = True

        if patient_summary["email"] and next_patient.get("email") != patient_summary["email"]:
            next_patient["email"] = patient_summary["email"]
            changed = True

        if patient_summary["phone"] and next_patient.get("phone") != patient_summary["phone"]:
            next_patient["phone"] = patient_summary["phone"]
            changed = True

        if changed and apply_changes:
            await bookings.update_one({"_id": booking["_id"]}, {"$set": {"patient": next_patient}})

        if changed:
            updated += 1

    return {
        "bookings_scanned": scanned,
        "bookings_needing_patient_backfill": updated,
        "mode": "apply" if apply_changes else "dry-run",
    }


async def detect_suspicious_package_pricing():
    db = get_db()
    packages = db["packages"]
    suspicious = []

    async for package in packages.find({}):
        package_view = str_id(package)
        hospitals = package_view.get("hospitals") if isinstance(package_view.get("hospitals"), list) else []
        if len(hospitals) < 2:
            continue

        price_pairs = []
        missing_prices = 0
        for hospital in hospitals:
            if not isinstance(hospital, dict):
                continue
            min_price = hospital.get("priceMin") or hospital.get("price_min") or hospital.get("price")
            max_price = hospital.get("priceMax") or hospital.get("price_max") or min_price
            if not min_price and not max_price:
                missing_prices += 1
                continue
            price_pairs.append((str(min_price), str(max_price)))

        if missing_prices > 0 or len(set(price_pairs)) <= 1:
            suspicious.append(
                {
                    "id": package_view.get("id") or package_view.get("_id"),
                    "slug": package_view.get("slug"),
                    "name": package_view.get("name") or package_view.get("title"),
                    "hospital_count": len(hospitals),
                    "priced_hospital_count": len(price_pairs),
                    "missing_price_count": missing_prices,
                }
            )

    return suspicious


async def detect_sparse_package_doctor_links():
    db = get_db()
    packages = db["packages"]
    specialty_counter: Counter[str] = Counter()

    async for package in packages.find({}):
        package_view = str_id(package)
        package_doctors = package_view.get("doctors") if isinstance(package_view.get("doctors"), list) else []
        if package_doctors:
            continue
        category = str(package_view.get("category") or "uncategorized").strip() or "uncategorized"
        specialty_counter[category] += 1

    return dict(specialty_counter)


async def main(apply_changes: bool):
    await connect_mongo()
    try:
        backlink_summary = await rebuild_hospital_backlinks(apply_changes=apply_changes)
        booking_summary = await backfill_booking_patient_summaries(apply_changes=apply_changes)
        suspicious_pricing = await detect_suspicious_package_pricing()
        sparse_links = await detect_sparse_package_doctor_links()

        print("Legacy repair summary")
        print(backlink_summary)
        print(booking_summary)
        print(f"Suspicious package pricing rows: {len(suspicious_pricing)}")
        for row in suspicious_pricing[:20]:
            print(row)
        print("Packages without explicit doctor links by category:")
        print(sparse_links)
    finally:
        await close_mongo()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repair and inspect legacy doctor/hospital/package/patient links")
    parser.add_argument("--apply", action="store_true", help="Write the repaired backlink and booking patient data")
    args = parser.parse_args()
    asyncio.run(main(apply_changes=args.apply))
