from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.time_utils import get_last_24h_window, is_in_last_24h


def test_last_24h_window():
    now_dt = datetime(2026, 6, 30, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    start_dt, end_dt = get_last_24h_window(now_dt)
    assert end_dt > start_dt
    assert is_in_last_24h(now_dt, now_dt) is True
