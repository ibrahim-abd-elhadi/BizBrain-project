"""Closing past days (research R-14).

A day closes at 00:00 Africa/Cairo. Nothing runs at midnight: instead every read or write of daily
totals calls close_past_days first, and so does start-up. Closing is idempotent and bumps
updated_at, so a later poll for changes sees the day close.
"""

from sqlalchemy import update
from sqlalchemy.orm import Session

from erp.clock import now_utc, today_cairo
from erp.models import DailySales


def close_past_days(session: Session) -> int:
    """Marks every open total dated before today (Cairo) as closed. Returns how many it closed."""
    result = session.execute(
        update(DailySales)
        .where(DailySales.day_status == "open", DailySales.business_date < today_cairo())
        .values(day_status="closed", updated_at=now_utc())
    )
    session.flush()
    return result.rowcount or 0
