"""Per-product daily series from the sales copy (FR-013, research R-06).

- `y` is the forecast target `y_units = max(net_units, 0)`; `net` keeps the signed net units for
  the anomaly checks.
- Only closed days, from the product's first sales row to the newest closed day; a closed day
  with no row counts as 0. Today's open row is never in a series (D-26, D-28).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brain.models import SalesDaily


@dataclass(frozen=True)
class Series:
    product_id: str
    start: date
    end: date
    y: np.ndarray
    net: np.ndarray

    def __len__(self) -> int:
        return len(self.y)

    def index_of(self, day: date) -> int:
        return (day - self.start).days

    def date_at(self, index: int) -> date:
        return self.start + timedelta(days=index)


def build_series(rows: Iterable[tuple[str, date, int, str]], end: date) -> dict[str, Series]:
    """rows: (product_id, business_date, net_units, day_status)."""
    first: dict[str, date] = {}
    closed: dict[str, dict[date, int]] = {}
    for product_id, day, net, status in rows:
        if day > end:
            continue
        first[product_id] = min(first.get(product_id, day), day)
        if status == "closed":
            closed.setdefault(product_id, {})[day] = net
    out: dict[str, Series] = {}
    for product_id in sorted(first):
        start = first[product_id]
        length = (end - start).days + 1
        net = np.zeros(length, dtype=float)
        for day, value in closed.get(product_id, {}).items():
            net[(day - start).days] = value
        out[product_id] = Series(product_id, start, end, np.maximum(net, 0.0), net)
    return out


def newest_closed_day(session: Session, today: date) -> date | None:
    return session.scalar(
        select(func.max(SalesDaily.business_date)).where(
            SalesDaily.day_status == "closed", SalesDaily.business_date < today
        )
    )


def load_series(session: Session, today: date) -> tuple[date | None, dict[str, Series]]:
    end = newest_closed_day(session, today)
    if end is None:
        return None, {}
    rows = session.execute(
        select(
            SalesDaily.product_id,
            SalesDaily.business_date,
            SalesDaily.net_units,
            SalesDaily.day_status,
        ).where(SalesDaily.business_date <= end)
    ).all()
    return end, build_series(((r[0], r[1], r[2], r[3]) for r in rows), end)
