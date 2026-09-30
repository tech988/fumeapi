from datetime import datetime, timezone

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from app.middleware.image_url_middleware import ImageUrlMiddleware

from app.core.config import settings
from app.core.db import connect_mongo, close_mongo, get_db
from app.core.security import hash_password
from app.core.errors import APIError, api_error_handler
from app.core.json_response import BSONJSONResponse

from app.routers.auth import router as auth_router
from app.routers.doctors import router as doctors_router
from app.routers.hospitals import router as hospitals_router
from app.routers.packages import router as packages_router
from app.routers.bookings import router as bookings_router
from app.routers.consultations import router as consultations_router
from app.routers.doctor_profile import router as doctor_profile_router
from app.routers.lookups import router as lookups_router
from app.routers.insurance import router as insurance_router
from app.routers.insurance_plans import router as insurance_plans_router
from app.routers.payments import router as payments_router
from app.routers.patients import router as patients_router
from app.routers.users import router as users_router
from app.routers.images import router as images_router
from app.routers.content import router as content_router
from app.routers.settings import router as settings_router
from app.routers.filters import router as filters_router
from app.routers.provider_applications import router as provider_applications_router

from app.routers.admin.doctors import router as admin_doctors_router
from app.routers.admin.hospitals import router as admin_hospitals_router
from app.routers.admin.packages import router as admin_packages_router
from app.routers.admin.bookings import router as admin_bookings_router
from app.routers.admin.consultations import router as admin_consultations_router
from app.routers.admin.users import router as admin_users_router
from app.routers.admin.settings import router as admin_settings_router
from app.routers.admin.insurance import router as admin_insurance_router
from app.routers.admin.dashboard import router as admin_dashboard_router
from app.routers.admin.content import router as admin_content_router

app = FastAPI(title=settings.APP_NAME, default_response_class=BSONJSONResponse)

app.add_exception_handler(APIError, api_error_handler)

# ✅ CORS FIX (must be before include_router)
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "https://hb-frontend-one.vercel.app",
    "https://www.hb-frontend-one.vercel.app",
    "https://hb-frontend-pi.vercel.app",
    "https://www.hb-frontend-pi.vercel.app",
    "https://healthbridge.adtractive.co",
    "https://www.healthbridge.adtractive.co"]

app.add_middleware(ImageUrlMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,      # set False if you never use cookies/auth
    allow_methods=["*"],         # includes OPTIONS preflight
    allow_headers=["*"],         # Authorization, Content-Type, etc.
)


@app.on_event("startup")
async def on_startup():
    await connect_mongo()

    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        db = get_db()
        users = db["users"]
        existing = await users.find_one({"email": settings.ADMIN_EMAIL.lower()})
        if not existing:
            await users.insert_one({
                "full_name": "Admin",
                "email": settings.ADMIN_EMAIL.lower(),
                "phone": None,
                "password_hash": hash_password(settings.ADMIN_PASSWORD),
                "role": "admin",
                "status": "active",
                "created_at": datetime.now(timezone.utc),
                "source": "bootstrap",
            })

    db = get_db()
    await db["doctors"].create_index("affiliatedHospitals.hospitalId")
    await db["doctors"].create_index("affiliatedHospitals.id")
    await db["packages"].create_index("hospitals.hospitalId")
    await db["bookings"].create_index("booking_ref", unique=True, sparse=True)
    await db["doctors"].create_index("city")
    await db["hospitals"].create_index("city")
    await db["insurance_partners"].create_index("city")
    await db["lookups_cities"].create_index("code", unique=True)


@app.on_event("shutdown")
async def on_shutdown():
    await close_mongo()


@app.get("/api/health", tags=["System"])
async def health():
    return {"ok": True, "service": settings.APP_NAME}

app.include_router(auth_router)
app.include_router(doctors_router)
app.include_router(hospitals_router)
app.include_router(packages_router)
app.include_router(bookings_router)
app.include_router(consultations_router)
app.include_router(doctor_profile_router)
app.include_router(lookups_router)
app.include_router(insurance_router)
app.include_router(insurance_plans_router)
app.include_router(payments_router)
app.include_router(patients_router)
app.include_router(users_router)
app.include_router(images_router)
app.include_router(content_router)
app.include_router(settings_router)
app.include_router(filters_router)
app.include_router(provider_applications_router)

app.include_router(admin_doctors_router)
app.include_router(admin_hospitals_router)
app.include_router(admin_packages_router)
app.include_router(admin_bookings_router)
app.include_router(admin_consultations_router)
app.include_router(admin_users_router)
app.include_router(admin_settings_router)
app.include_router(admin_insurance_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_content_router)
