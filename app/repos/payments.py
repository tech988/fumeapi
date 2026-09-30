from datetime import datetime, timezone
from fastapi import Depends
from app.core.db import get_db
from app.utils.bson import oid, str_id
from app.core.errors import http_error
from app.core.config import settings
from app.services.payment_providers.razorpay import RazorpayProvider

class PaymentsRepo:
    def __init__(self, db=Depends(get_db)):
        self.payments = db["payments"]
        self.bookings = db["bookings"]

    def _booking_owner_query(self, user_id: str) -> dict:
        key = str(user_id)
        return {
            "$or": [
                {"user_id": key},
                {"patient_id": key},
            ]
        }

    async def create_order(self, user_id: str, payload: dict):
        booking_id = payload.get("booking_id")
        amount_raw = payload.get("amount")
        currency = payload.get("currency") or "INR"
        provider = payload.get("provider") or "razorpay"

        if not booking_id or amount_raw is None:
            http_error(400, "VALIDATION_ERROR", "booking_id and amount are required")

        booking_id = str(booking_id)

        if provider != "razorpay":
            http_error(400, "PROVIDER_NOT_SUPPORTED", "Only razorpay is supported")

        b = await self.bookings.find_one({"_id": oid(booking_id), **self._booking_owner_query(user_id)})
        if not b:
            http_error(404, "BOOKING_NOT_FOUND", "Booking not found")

        if b.get("payment_status") == "paid":
            http_error(409, "ALREADY_PAID", "Booking is already paid")

        existing_payment = await self.payments.find_one(
            {
                "booking_id": booking_id,
                "user_id": user_id,
                "provider": provider,
                "status": {"$in": ["created", "attempted", "pending"]},
                "gateway.order_id": {"$exists": True, "$ne": None},
            },
            sort=[("created_at", -1), ("_id", -1)],
        )
        if existing_payment:
            gateway = existing_payment.get("gateway") or {}
            await self.bookings.update_one(
                {"_id": oid(booking_id)},
                {"$set": {"payment_status": "pending"}},
            )
            return {
                "payment": {
                    "id": str(existing_payment.get("_id")),
                    "booking_id": booking_id,
                    "provider": provider,
                    "amount": existing_payment.get("amount") or amount_raw,
                    "currency": existing_payment.get("currency") or currency,
                    "status": existing_payment.get("status") or "created",
                },
                "gateway": {
                    "order_id": gateway.get("order_id"),
                    "amount": gateway.get("amount") or existing_payment.get("amount"),
                    "currency": gateway.get("currency") or existing_payment.get("currency") or currency,
                    "receipt": gateway.get("receipt"),
                    "status": gateway.get("status") or existing_payment.get("status") or "created",
                    "key_id": settings.RAZORPAY_KEY_ID,
                },
            }

        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            http_error(500, "RAZORPAY_NOT_CONFIGURED", "Razorpay credentials are missing")

        if isinstance(amount_raw, str) and amount_raw.isdigit():
            amount_int = int(amount_raw)
        elif isinstance(amount_raw, int):
            amount_int = amount_raw
        else:
            amount_int = -1
        if amount_int <= 0:
            http_error(400, "VALIDATION_ERROR", "amount must be a positive integer")

        rp = RazorpayProvider()
        receipt = f"booking_{booking_id}_{int(datetime.now(timezone.utc).timestamp())}"
        order = rp.create_order(
            amount=amount_int,
            currency=currency,
            receipt=receipt,
            notes={"booking_id": booking_id, "user_id": user_id},
        )

        payment = {
            "booking_id": booking_id,
            "user_id": user_id,
            "provider": provider,
            "amount": amount_int,
            "currency": currency,
            "status": order.get("status") or "created",
            "gateway": {
                "order_id": order.get("id"),
                "receipt": order.get("receipt"),
                "status": order.get("status"),
                "amount": order.get("amount"),
                "currency": order.get("currency"),
            },
            "created_at": datetime.now(timezone.utc),
        }
        res = await self.payments.insert_one(payment)
        payment["_id"] = res.inserted_id
        payment = str_id(payment)

        await self.bookings.update_one(
            {"_id": oid(booking_id)},
            {"$set": {"payment_status": "pending"}},
        )

        return {
            "payment": {
                "id": payment["id"],
                "booking_id": booking_id,
                "provider": provider,
                "amount": payment["amount"],
                "currency": currency,
                "status": payment["status"],
            },
            "gateway": {
                "order_id": order.get("id"),
                "amount": order.get("amount"),
                "currency": order.get("currency"),
                "receipt": order.get("receipt"),
                "status": order.get("status"),
                "key_id": settings.RAZORPAY_KEY_ID,
            },
        }

    async def handle_webhook(self, provider: str, event: dict):
        event_id = event.get("event") or event.get("id")
        if event_id:
            existing = await self.payments.find_one({"webhook_event_id": event_id})
            if existing:
                return

        payload = event.get("payload") or {}
        payment_entity = (payload.get("payment") or {}).get("entity") or {}
        order_entity = (payload.get("order") or {}).get("entity") or {}
        invoice_entity = (payload.get("invoice") or {}).get("entity") or {}
        notes = payment_entity.get("notes") or order_entity.get("notes") or {}

        order_id = payment_entity.get("order_id") or order_entity.get("id") or invoice_entity.get("order_id")
        payment_id = payment_entity.get("id")
        status = payment_entity.get("status") or order_entity.get("status")
        event_type = event.get("event")

        update = {
            "provider": provider,
            "webhook_event_id": event_id,
            "last_event": event_type,
            "raw": event,
            "updated_at": datetime.now(timezone.utc),
        }
        if order_id:
            update["gateway.order_id"] = order_id
        if payment_id:
            update["gateway.payment_id"] = payment_id
        if status:
            update["status"] = status

        target = None
        if order_id:
            target = {"gateway.order_id": order_id}
        elif payment_id:
            target = {"gateway.payment_id": payment_id}

        booking_id = None
        if target:
            existing = await self.payments.find_one(target)
            if existing:
                booking_id = existing.get("booking_id")
                await self.payments.update_one(
                    {"_id": existing["_id"]},
                    {"$set": update, "$push": {"events": event}},
                )
            else:
                doc = {
                    **update,
                    "booking_id": notes.get("booking_id"),
                    "created_at": datetime.now(timezone.utc),
                    "events": [event],
                }
                await self.payments.insert_one(doc)
        else:
            await self.payments.insert_one({
                **update,
                "booking_id": notes.get("booking_id"),
                "created_at": datetime.now(timezone.utc),
                "events": [event],
            })

        if booking_id or notes.get("booking_id"):
            booking_id = booking_id or notes.get("booking_id")
            booking_id = str(booking_id)
            paid_events = {"payment.captured", "order.paid"}
            failed_events = {"payment.failed", "order.payment_failed"}
            if event_type in paid_events or status in {"captured", "paid"}:
                await self.bookings.update_one(
                    {"_id": oid(booking_id)},
                    {"$set": {"payment_status": "paid"}},
                )
            elif event_type in failed_events or status in {"failed"}:
                await self.bookings.update_one(
                    {"_id": oid(booking_id)},
                    {"$set": {"payment_status": "failed"}},
                )

    async def verify_client_payment(self, user_id: str, payload: dict):
        order_id = payload.get("razorpay_order_id")
        payment_id = payload.get("razorpay_payment_id")
        signature = payload.get("razorpay_signature")
        booking_id = payload.get("booking_id")

        if not all([order_id, payment_id, signature, booking_id]):
            http_error(400, "VALIDATION_ERROR", "razorpay_order_id, razorpay_payment_id, razorpay_signature, booking_id are required")

        rp = RazorpayProvider()
        if not rp.verify_payment_signature(str(order_id), str(payment_id), str(signature)):
            http_error(400, "INVALID_SIGNATURE", "Invalid Razorpay signature")

        booking = await self.bookings.find_one({"_id": oid(str(booking_id)), **self._booking_owner_query(user_id)})
        if not booking:
            http_error(404, "BOOKING_NOT_FOUND", "Booking not found")

        res = await self.payments.update_one(
            {"gateway.order_id": str(order_id), "booking_id": str(booking_id)},
            {
                "$set": {
                    "gateway.payment_id": str(payment_id),
                    "gateway.signature": str(signature),
                    "status": "captured",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if res.matched_count == 0:
            await self.payments.insert_one({
                "booking_id": str(booking_id),
                "user_id": user_id,
                "provider": "razorpay",
                "status": "captured",
                "gateway": {
                    "order_id": str(order_id),
                    "payment_id": str(payment_id),
                    "signature": str(signature),
                },
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })

        await self.bookings.update_one(
            {"_id": oid(str(booking_id))},
            {"$set": {"payment_status": "paid"}},
        )

        return {"ok": True}
