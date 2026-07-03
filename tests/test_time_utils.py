from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.time_utils import (
    ensure_aware_datetime,
    get_last_24h_window,
    is_in_last_24h,
)


def test_last_24h_window():
    now_dt = datetime(2026, 6, 30, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    start_dt, end_dt = get_last_24h_window(now_dt)
    assert end_dt > start_dt
    assert is_in_last_24h(now_dt, now_dt) is True


def test_is_in_last_24h_accepts_naive_created_at():
    now_dt = datetime(2026, 6, 30, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    created_at = datetime(2026, 6, 30, 1, 30)

    assert is_in_last_24h(created_at, now_dt) is True


def test_ensure_aware_datetime_adds_default_tz():
    dt = datetime(2026, 6, 30, 1, 30)
    normalized = ensure_aware_datetime(dt)

    assert normalized.tzinfo is not None
