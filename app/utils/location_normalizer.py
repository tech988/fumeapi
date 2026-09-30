import re


def _clean_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _norm_key(value: str | None) -> str:
    text = _clean_text(value).lower()
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


CITY_ALIASES: dict[str, str] = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "calcutta": "Kolkata",
    "kolkata": "Kolkata",
    "madras": "Chennai",
    "chennai": "Chennai",
    "trivandrum": "Thiruvananthapuram",
    "thiruvananthapuram": "Thiruvananthapuram",
    "new delhi": "Delhi",
    "delhi": "Delhi",
    "noida": "Noida",
    "greater noida": "Greater Noida",
    "pune": "Pune",
    "hyderabad": "Hyderabad",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "lucknow": "Lucknow",
    "chandigarh": "Chandigarh",
}


STATE_ALIASES: dict[str, str] = {
    "delhi": "Delhi",
    "nct of delhi": "Delhi",
    "karnataka": "Karnataka",
    "haryana": "Haryana",
    "maharashtra": "Maharashtra",
    "west bengal": "West Bengal",
    "tamil nadu": "Tamil Nadu",
    "kerala": "Kerala",
    "telangana": "Telangana",
    "uttar pradesh": "Uttar Pradesh",
    "rajasthan": "Rajasthan",
    "gujarat": "Gujarat",
    "chandigarh": "Chandigarh",
}


CITY_TO_STATE: dict[str, str] = {
    "Delhi": "Delhi",
    "Bengaluru": "Karnataka",
    "Gurugram": "Haryana",
    "Mumbai": "Maharashtra",
    "Kolkata": "West Bengal",
    "Chennai": "Tamil Nadu",
    "Thiruvananthapuram": "Kerala",
    "Noida": "Uttar Pradesh",
    "Greater Noida": "Uttar Pradesh",
    "Pune": "Maharashtra",
    "Hyderabad": "Telangana",
    "Ahmedabad": "Gujarat",
    "Jaipur": "Rajasthan",
    "Lucknow": "Uttar Pradesh",
    "Chandigarh": "Chandigarh",
}


def canonical_city(value: str | None) -> str | None:
    key = _norm_key(value)
    if not key:
        return None
    if key in CITY_ALIASES:
        return CITY_ALIASES[key]

    parts = [p.strip() for p in re.split(r"[,/|]", _clean_text(value)) if p.strip()]
    if parts:
        part_key = _norm_key(parts[0])
        if part_key in CITY_ALIASES:
            return CITY_ALIASES[part_key]
        if part_key:
            return _title_case(part_key)

    return _title_case(key)


def canonical_state(value: str | None) -> str | None:
    key = _norm_key(value)
    if not key:
        return None
    if key in STATE_ALIASES:
        return STATE_ALIASES[key]
    return _title_case(key)


def normalize_india_location(
    city: str | None = None,
    state: str | None = None,
    location: str | None = None,
    address: str | None = None,
    headquarters: str | None = None,
    country: str | None = None,
) -> dict:
    candidate_city = city or location or headquarters or address
    out_city = canonical_city(candidate_city)
    out_state = canonical_state(state)
    if not out_state and out_city:
        out_state = CITY_TO_STATE.get(out_city)

    out_country = _clean_text(country)
    if out_city and not out_country:
        out_country = "India"
    elif out_country:
        out_country = _title_case(_norm_key(out_country))

    result = {
        "city": out_city,
        "state": out_state,
        "country": out_country or None,
    }
    return result
