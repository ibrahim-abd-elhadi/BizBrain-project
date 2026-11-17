"""Helpers that build closed-day sales series and expected values for the Brain's tests."""

import math
import statistics
from datetime import date, timedelta

from sqlalchemy.orm import Session


def add_days(
    session: Session,
    product_id: str,
    values: list[int],
    last_day: date,
    status_last: str = "closed",
) -> None:
    """Store `values` as net units (sold = value, returned = 0) for consecutive days ending at
    `last_day`, all closed except optionally the last one."""
    from datetime import UTC, datetime

    from brain.models import SalesDaily

    first = last_day - timedelta(days=len(values) - 1)
    for i, value in enumerate(values):
        day = first + timedelta(days=i)
        status = status_last if day == last_day else "closed"
        session.merge(
            SalesDaily(
                product_id=product_id,
                business_date=day,
                units_sold=max(value, 0),
                units_returned=max(-value, 0),
                net_units=value,
                day_status=status,
                erp_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                changed_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    session.commit()


def mean_sd(values: list[float]) -> tuple[float, float]:
    """Mean and sample sd, with sd = 0 counted as 1 (the ERP's and the Brain's rule)."""
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return statistics.mean(values), (sd or 1.0)


def spike_target(values: list[int], z: float = 4.0) -> int:
    mean, sd = mean_sd(values)
    return math.ceil(mean + z * sd)


def load_seed_into_db(session: Session, today: date) -> None:
    """The 1,800 seeded totals straight into sales_daily, re-dated so day 90 is yesterday."""
    from datetime import UTC, datetime

    from sqlalchemy.dialects.postgresql import insert

    from brain.models import SalesDaily

    from fakes import load_seed_rows

    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        {
            "product_id": r["product_id"],
            "business_date": date.fromisoformat(r["business_date"]),
            "units_sold": r["units_sold"],
            "units_returned": r["units_returned"],
            "net_units": r["net_units"],
            "day_status": "closed",
            "erp_updated_at": stamp,
            "changed_at": stamp,
        }
        for r in load_seed_rows(today, stamp)
    ]
    session.execute(insert(SalesDaily).values(rows))
    session.commit()


def seed_date(today: date, day_index: int) -> date:
    """The date of seed day `day_index` (1 = oldest, 90 = yesterday)."""
    return today - timedelta(days=91 - day_index)
