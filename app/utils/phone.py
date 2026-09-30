import re


INDIAN_COUNTRY_CODE = "91"
INDIAN_MOBILE_DIGITS = 10


def phone_digits(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


def normalize_indian_phone(value: str | None) -> str | None:
    digits = phone_digits(value)
    if not digits:
        return None

    if len(digits) == 12 and digits.startswith(INDIAN_COUNTRY_CODE):
        digits = digits[2:]

    if len(digits) != INDIAN_MOBILE_DIGITS:
        return None

    if digits[0] not in {"6", "7", "8", "9"}:
        return None

    return f"+{INDIAN_COUNTRY_CODE}{digits}"
