from fastapi import APIRouter, Depends, Request
from app.core.deps import require_roles
from app.repos.payments import PaymentsRepo
from app.services.payment_providers.razorpay import RazorpayProvider
from app.core.errors import http_error

router = APIRouter(prefix="/api/payments", tags=["Payments"])

@router.post("/order")
async def create_order(payload: dict, user=Depends(require_roles("patient")), repo: PaymentsRepo = Depends(PaymentsRepo)):
    return await repo.create_order(user_id=str(user["_id"]), payload=payload)

@router.post("/verify/razorpay")
async def verify_razorpay_payment(payload: dict, user=Depends(require_roles("patient")), repo: PaymentsRepo = Depends(PaymentsRepo)):
    return await repo.verify_client_payment(user_id=str(user["_id"]), payload=payload)

@router.post("/webhook/{provider}")
async def payment_webhook(provider: str, request: Request, repo: PaymentsRepo = Depends(PaymentsRepo)):
    raw = await request.body()
    headers = dict(request.headers)

    if provider == "razorpay":
        rp = RazorpayProvider()
        if not rp.verify_webhook(raw, headers):
            http_error(400, "INVALID_SIGNATURE", "Invalid webhook signature")
        event = rp.parse_event(raw)
        await repo.handle_webhook(provider="razorpay", event=event)
        return {"ok": True}

    http_error(404, "PROVIDER_NOT_FOUND", "Unknown provider")
