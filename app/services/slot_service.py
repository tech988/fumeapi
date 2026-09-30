from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.errors import http_error


def normalize_timezone(date: str, timezone: str | None) -> str:
    if not timezone:
        return "+05:30"

    tz = str(timezone)
    if tz.startswith("+") or tz.startswith("-"):
        return tz

    if "/" in tz:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            offset = dt.replace(tzinfo=ZoneInfo(tz)).utcoffset()
            if offset is None:
                return tz
            total_minutes = int(offset.total_seconds() // 60)
            sign = "+" if total_minutes >= 0 else "-"
            total_minutes = abs(total_minutes)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            return f"{sign}{hours:02d}:{minutes:02d}"
        except Exception:
            return tz

    return tz


def build_slots_for_date(*, date: str, timezone: str, slots: list[dict]):
    built = []
    for s in slots:
        start = s.get("start") or s.get("slot_start")
        end = s.get("end") or s.get("slot_end")
        if not start or not end:
            continue

        start_str = str(start)
        end_str = str(end)

        if "T" not in start_str and "T" not in end_str:
            if len(start_str) == 5:
                start_str = f"{start_str}:00"
            if len(end_str) == 5:
                end_str = f"{end_str}:00"

            try:
                start_dt = datetime.strptime(f"{date}T{start_str}", "%Y-%m-%dT%H:%M:%S")
                end_dt = datetime.strptime(f"{date}T{end_str}", "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue

            while start_dt + timedelta(hours=1) <= end_dt:
                slot_start = start_dt.strftime("%Y-%m-%dT%H:%M:%S") + timezone
                slot_end = (start_dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S") + timezone
                built.append({"slot_start": slot_start, "slot_end": slot_end})
                start_dt = start_dt + timedelta(hours=1)
            continue

        if "T" not in start_str:
            if len(start_str) == 5:
                start_str = f"{start_str}:00"
            start_str = f"{date}T{start_str}{timezone}"

        if "T" not in end_str:
            if len(end_str) == 5:
                end_str = f"{end_str}:00"
            end_str = f"{date}T{end_str}{timezone}"

        built.append({"slot_start": start_str, "slot_end": end_str})

    return built

async def get_slots_for_doctor(*, doctor_id: str, date: str, timezone: str | None):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        http_error(400, "INVALID_DATE", "date must be YYYY-MM-DD")

    tz = normalize_timezone(date, timezone)
    return {
        "doctor_id": doctor_id,
        "date": date,
        "timezone": tz,
        "slots": [],
    }
