from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def now_in_timezone(tz_name: str = "Asia/Shanghai") -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def get_last_24h_window(now_dt: datetime) -> tuple[datetime, datetime]:
    return now_dt - timedelta(hours=24), now_dt


def is_in_last_24h(created_at: datetime, now_dt: datetime) -> bool:
    start, end = get_last_24h_window(now_dt)
    return start <= created_at <= end


def report_date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")
