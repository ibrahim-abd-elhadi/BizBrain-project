"""The sales poll (README Section 3.2; FR-005 to FR-008; research R-03).

1. Ask for rows updated since the saved watermark − 120 s (the whole window if none is saved).
2. Follow next_cursor; each page is upserted in its own transaction as absolute totals, and an
   older or equal ERP updated_at never overwrites a newer one.
3. Save the watermark only after the last page, so a poll that fails halfway re-reads the same
   rows next time.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brain.canonical.client import CanonicalClient, SalesRow
from brain.clock import now_utc, today_cairo
from brain.config import Settings, get_settings
from brain.db import worker_session
from brain.jobs.registry import RunContext
from brain.models import PollState, SalesDaily


def _upsert(session: Session, rows: list[SalesRow]) -> int:
    if not rows:
        return 0
    now = now_utc()
    statement = insert(SalesDaily).values(
        [
            {
                "product_id": r.product_id,
                "business_date": r.business_date,
                "units_sold": r.units_sold,
                "units_returned": r.units_returned,
                "net_units": r.net_units,
                "day_status": r.day_status,
                "erp_updated_at": r.updated_at,
                "changed_at": now,
            }
            for r in rows
        ]
    )
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[SalesDaily.product_id, SalesDaily.business_date],
        set_={
            "units_sold": excluded.units_sold,
            "units_returned": excluded.units_returned,
            "net_units": excluded.net_units,
            "day_status": excluded.day_status,
            "erp_updated_at": excluded.erp_updated_at,
            "changed_at": excluded.changed_at,
        },
        where=excluded.erp_updated_at > SalesDaily.erp_updated_at,
    ).returning(SalesDaily.product_id)
    # Count the rows actually inserted or updated (multi-row rowcount is -1 under psycopg).
    return len(session.execute(statement).all())


def poll_sales(client: CanonicalClient, settings: Settings) -> dict[str, Any]:
    with worker_session() as session:
        state = session.get(PollState, 1)
        watermark = state.high_watermark if state else None
    today = today_cairo()
    since = watermark - timedelta(seconds=settings.poll_overlap_seconds) if watermark else None
    first = today - timedelta(days=settings.poll_history_days)

    cursor: str | None = None
    pages = rows = changed = 0
    while True:
        page = client.sales_page(first, today, since, cursor, settings.poll_page_limit)
        with worker_session() as session:
            changed += _upsert(session, page.items)
            session.commit()
        pages += 1
        rows += len(page.items)
        if page.next_cursor is None:
            with worker_session() as session:
                session.merge(PollState(id=1, high_watermark=page.high_watermark, saved_at=now_utc()))
                session.commit()
            return {"pages": pages, "rows": rows, "changed": changed}
        cursor = page.next_cursor


def run_sales_poll(run: RunContext) -> dict[str, Any]:
    settings = get_settings()
    with CanonicalClient.from_settings(settings) as client:
        return poll_sales(client, settings)
