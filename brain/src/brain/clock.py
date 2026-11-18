"""The only place that reads the clock. "Today" is always the Africa/Cairo calendar date.

Nothing else in the Brain may call datetime.now() or date.today().
"""

import time
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_cairo(now: datetime | None = None) -> date:
    return (now or now_utc()).astimezone(CAIRO).date()


def monotonic() -> float:
    """Seconds on a clock that never goes back: the assistant's deadlines and caches (feature 005).
    Call it as `clock.monotonic()`, so tests can move it without sleeping."""
    return time.monotonic()
