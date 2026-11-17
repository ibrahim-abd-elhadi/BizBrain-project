"""GET /sales: daily sales totals changed since a watermark (US1; research R-07 to R-09).

How nothing is ever missed (research R-07):
- the first page of a poll (no cursor) closes past days, runs its query, and only then reads
  W = now_utc(), so every row it returns committed, and was stamped, before W;
- every later page carries that same W inside the signed cursor and never reads the clock;
- request transactions are limited to ERP_DB_TRANSACTION_TIMEOUT_SECONDS (T), so any row a poll
  misses has updated_at > W - T - d, and the Brain's next poll from W - 120 s includes it.
"""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime
from sqlalchemy import select, tuple_

from erp.canonical import cursor as cursors
from erp.canonical.auth import ReadAccess
from erp.canonical.errors import validation_error
from erp.canonical.schemas import DailySalesTotal, SalesPage
from erp.clock import now_utc
from erp.db import SessionDep
from erp.models import DailySales
from erp.services.day_close import close_past_days

router = APIRouter()


@router.get("/sales", response_model=SalesPage, dependencies=[ReadAccess])
def get_sales(
    session: SessionDep,
    from_: Annotated[date, Query(alias="from", description="Inclusive Cairo business date")],
    to: Annotated[date, Query(description="Inclusive Cairo business date")],
    updated_since: Annotated[AwareDatetime | None, Query(description="Exclusive")] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SalesPage:
    if from_ > to:
        raise validation_error("from", "must not be after `to`")

    filters = {"f": from_.isoformat(), "t": to.isoformat(), "u": updated_since}
    last_key: tuple[datetime, str, date] | None = None
    if cursor is None:
        close_past_days(session)  # only a poll's first page closes days (research R-07, 4)
        watermark: datetime | None = None
    else:
        try:
            payload = cursors.decode("sales", cursor, filters)
            watermark = datetime.fromisoformat(payload["w"])
            last_key = (
                datetime.fromisoformat(payload["a"]),
                str(payload["p"]),
                date.fromisoformat(payload["d"]),
            )
        except (cursors.InvalidCursor, KeyError, TypeError, ValueError):
            raise validation_error(
                "cursor", "invalid, tampered with, or issued for other filters"
            ) from None

    query = select(DailySales).where(DailySales.business_date.between(from_, to))
    if updated_since is not None:
        query = query.where(DailySales.updated_at > updated_since)
    if last_key is not None:
        query = query.where(
            tuple_(DailySales.updated_at, DailySales.product_id, DailySales.business_date)
            > tuple_(*last_key)
        )
    query = query.order_by(
        DailySales.updated_at, DailySales.product_id, DailySales.business_date
    ).limit(limit + 1)
    rows = list(session.scalars(query))

    if watermark is None:
        watermark = now_utc()  # just after the first page's query: later than all its rows

    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if more:
        last = rows[-1]
        next_cursor = cursors.encode(
            "sales",
            {
                **filters,
                "w": watermark,
                "a": last.updated_at,
                "p": last.product_id,
                "d": last.business_date,
            },
        )
    return SalesPage(
        items=[
            DailySalesTotal(
                product_id=row.product_id,
                business_date=row.business_date,
                units_sold=row.units_sold,
                units_returned=row.units_returned,
                net_units=row.net_units,
                day_status=row.day_status,  # type: ignore[arg-type]
                updated_at=row.updated_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
        high_watermark=watermark,
    )
