from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def now_in_timezone(tz_name: str = "Asia/Shanghai") -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def get_last_24h_window(now_dt: datetime) -> tuple[datetime, datetime]:
    return now_dt - timedelta(hours=24), now_dt


def ensure_aware_datetime(dt: datetime, default_tz=timezone.utc) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=default_tz)
    return dt


def is_in_last_24h(created_at: datetime, now_dt: datetime) -> bool:
    now_dt = ensure_aware_datetime(now_dt)
    created_at = ensure_aware_datetime(created_at)
    start, end = get_last_24h_window(now_dt)
    return start <= created_at <= end


def report_date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")
