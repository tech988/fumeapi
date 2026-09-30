# Health Bridge API (FastAPI + MongoDB)

This is a full scaffold based on your endpoint list + contracts:
- Auth (register/login/logout/me) with JWT access + refresh
- Public: doctors/hospitals/packages/insurance partners/lookups
- Booking flow + payments order + webhook
- Admin CRUD + import endpoints + admin settings

## Run locally


```bash
python -m venv .venv
source .venv/bin/activate  # windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Swagger:
- http://localhost:8000/docs

## Mongo collections
- users
- auth_tokens
- doctors
- hospitals
- packages
- insurance_partners
- insurance_leads
- bookings
- payments
- lookups_cities, lookups_specialties, lookups_languages
- settings

## Notes
- Import endpoints accept CSV via multipart: field name `file`.
- This repo keeps schemas light for speed; tighten Pydantic models as you iterate.

## Deploy to Vercel

`vercel.json` routes every path to `api/index.py`, which exposes the FastAPI `app`.
Python version is pinned in `.python-version`.

Set these environment variables in the Vercel project: `MONGO_URI`, `MONGO_DB`,
`JWT_SECRET`, and optionally `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.

Seed/migration scripts read `MONGO_URI` (and `MONGO_DB`) from the environment.
