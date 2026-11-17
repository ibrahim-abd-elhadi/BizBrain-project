from datetime import UTC, date, datetime

from erp.clock import now_utc, today_cairo


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_late_evening_utc_is_already_tomorrow_in_cairo() -> None:
    assert today_cairo(utc("2026-11-17T23:30:00")) == date(2026, 11, 18)


def test_cairo_is_utc_plus_3_in_summer() -> None:
    assert today_cairo(utc("2026-07-15T21:30:00")) == date(2026, 7, 16)


def test_cairo_is_utc_plus_2_in_winter() -> None:
    assert today_cairo(utc("2026-11-15T21:30:00")) == date(2026, 11, 15)


def test_clocks_go_back_on_2026_10_29_at_21_00_utc() -> None:
    # 20:30 UTC = 23:30 Cairo (UTC+3)
    assert today_cairo(utc("2026-10-29T20:30:00")) == date(2026, 10, 29)
    # 21:30 UTC = 23:30 Cairo again, now UTC+2
    assert today_cairo(utc("2026-10-29T21:30:00")) == date(2026, 10, 29)
    # 22:30 UTC = 00:30 Cairo (UTC+2)
    assert today_cairo(utc("2026-10-29T22:30:00")) == date(2026, 10, 30)


def test_now_utc_is_timezone_aware() -> None:
    assert now_utc().tzinfo is not None
    assert now_utc().utcoffset().total_seconds() == 0
