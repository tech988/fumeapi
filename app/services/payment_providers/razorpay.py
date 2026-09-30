import hmac
import hashlib
import json

from app.core.config import settings
from app.services.payment_providers.base import PaymentProvider

try:
    import razorpay
    _razorpay_import_error: Exception | None = None
except Exception as exc:
    razorpay = None
    _razorpay_import_error = exc

class RazorpayProvider(PaymentProvider):
    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID or ""
        self.key_secret = settings.RAZORPAY_KEY_SECRET or ""
        self._client = None
        if self.key_id and self.key_secret:
            if razorpay is None:
                raise RuntimeError(
                    f"razorpay SDK is unavailable: {_razorpay_import_error}"
                )
            self._client = razorpay.Client(auth=(self.key_id, self.key_secret))  # type: ignore[attr-defined]

    def is_configured(self) -> bool:
        return bool(self.key_id and self.key_secret)

    def create_order(self, amount: int, currency: str, receipt: str, notes: dict | None = None) -> dict:
        if not self._client:
            raise RuntimeError("Razorpay client not configured")
        payload = {
            "amount": int(amount),
            "currency": currency,
            "receipt": receipt,
        }
        if notes:
            payload["notes"] = notes
        return self._client.order.create(data=payload)

    def verify_payment_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        if not self.key_secret:
            return False
        message = f"{order_id}|{payment_id}".encode("utf-8")
        digest = hmac.new(self.key_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, signature)

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        secret = settings.RAZORPAY_WEBHOOK_SECRET or ""
        sig = headers.get("x-razorpay-signature") or headers.get("X-Razorpay-Signature")
        if not secret or not sig:
            return False
        digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, sig)

    def parse_event(self, raw_body: bytes) -> dict:
        return json.loads(raw_body.decode("utf-8"))
