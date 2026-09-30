from fastapi import APIRouter, Depends

from app.core.db import get_db
from app.core.deps import require_roles


router = APIRouter(prefix="/api/admin", tags=["Admin"])


@router.get("/dashboard")
async def get_dashboard_stats(
    _admin=Depends(require_roles("admin")),
    db=Depends(get_db),
):
    users_col = db["users"]
    bookings_col = db["bookings"]
    doctors_col = db["doctors"]
    hospitals_col = db["hospitals"]
    packages_col = db["packages"]
    patients_col = db["patients"]
    insurance_col = db["insurance_plans"]
    leads_col = db["insurance_leads"]

    total_users = await users_col.count_documents({})
    total_bookings = await bookings_col.count_documents({})
    total_doctors = await doctors_col.count_documents({})
    total_hospitals = await hospitals_col.count_documents({})
    total_packages = await packages_col.count_documents({})
    total_patients = await patients_col.count_documents({})
    total_insurance_plans = await insurance_col.count_documents({})
    total_insurance_leads = await leads_col.count_documents({})

    # booking status breakdown (best-effort)
    booking_status = {}
    for st in ("pending", "confirmed", "completed", "cancelled"):
        booking_status[st] = await bookings_col.count_documents({"status": st})

    return {
        "totals": {
            "users": total_users,
            "patients": total_patients,
            "bookings": total_bookings,
            "doctors": total_doctors,
            "hospitals": total_hospitals,
            "packages": total_packages,
            "insurance_plans": total_insurance_plans,
            "insurance_leads": total_insurance_leads,
        },
        "bookings": {"by_status": booking_status},
    }
