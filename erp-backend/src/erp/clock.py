"""The only place that reads the clock. "Today" is always the Africa/Cairo calendar date.

Nothing else in the code may call datetime.now() or date.today().
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_cairo(now: datetime | None = None) -> date:
    return (now or now_utc()).astimezone(CAIRO).date()
