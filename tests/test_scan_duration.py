from __future__ import annotations

from datetime import datetime, timezone

from mypicsdb3.utils import duration_seconds, format_duration


def test_duration_seconds_accepts_sqlite_text_and_mysql_datetimes() -> None:
    assert duration_seconds(
        "2026-08-05 12:00:00.000000",
        "2026-08-05 12:04:18.000000",
    ) == 258
    assert duration_seconds(
        datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 5, 13, 12, 5, tzinfo=timezone.utc),
    ) == 4325


def test_duration_seconds_ignores_incomplete_or_invalid_values() -> None:
    assert duration_seconds("", "2026-08-05 12:00:00") is None
    assert duration_seconds("not-a-date", "2026-08-05 12:00:00") is None
    assert duration_seconds(
        "2026-08-05 12:01:00", "2026-08-05 12:00:00"
    ) == 0


def test_format_duration_uses_compact_hours_minutes_and_seconds() -> None:
    assert format_duration(38) == "38 sec"
    assert format_duration(258) == "4 min 18 sec"
    assert format_duration(4325) == "1 h 12 min 5 sec"
    assert format_duration(3600) == "1 h"
