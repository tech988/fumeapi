from abc import ABC, abstractmethod

class PaymentProvider(ABC):
    @abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool: ...
    @abstractmethod
    def parse_event(self, raw_body: bytes) -> dict: ...
