"""A day closes at 00:00 Africa/Cairo and closing bumps updated_at (FR-008, research R-14).

Written before the implementation.
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.models import DailySales

BASE = "/api/v1/erp"


def _row(db: Session, product_id: str, business_date: date) -> DailySales:
    db.expire_all()
    return db.scalars(
        select(DailySales).where(
            DailySales.product_id == product_id, DailySales.business_date == business_date
        )
    ).one()


def test_open_day_closes_after_cairo_midnight_and_closing_is_idempotent(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo("2026-11-17T23:50"):
        db.add(
            DailySales(
                product_id="P001",
                business_date=date(2026, 11, 17),
                units_sold=10,
                units_returned=1,
                day_status="open",
            )
        )
        db.commit()
        before = _row(db, "P001", date(2026, 11, 17))
        assert before.day_status == "open"
        assert before.net_units == 9
        opened_at = before.updated_at
        # Still the same business day: reading does not close it.
        first = client.get(f"{BASE}/sales", headers=login()).json()["items"][0]
        assert first["day_status"] == "open"

    with at_cairo("2026-11-18T00:01"):
        response = client.get(f"{BASE}/sales", headers=login())
        assert response.status_code == 200
        assert response.json()["today"] == "2026-11-18"
        assert response.json()["items"][0]["day_status"] == "closed"
        closed = _row(db, "P001", date(2026, 11, 17))
        assert closed.day_status == "closed"
        assert closed.updated_at > opened_at
        closed_at = closed.updated_at

    with at_cairo("2026-11-18T09:00"):
        client.get(f"{BASE}/sales", headers=login())
        again = _row(db, "P001", date(2026, 11, 17))
        assert again.updated_at == closed_at  # closing again changes nothing
        assert (again.units_sold, again.units_returned) == (10, 1)


def test_nothing_sets_a_closed_row_back_to_open(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo("2026-11-18T10:00"):
        db.add(
            DailySales(
                product_id="P002",
                business_date=date(2026, 11, 16),
                units_sold=5,
                units_returned=0,
                day_status="closed",
            )
        )
        db.commit()
        for _ in range(3):
            client.get(f"{BASE}/sales", headers=login())
        assert _row(db, "P002", date(2026, 11, 16)).day_status == "closed"
    with at_cairo("2026-11-20T10:00"):
        client.get(f"{BASE}/sales", headers=login())
        assert _row(db, "P002", date(2026, 11, 16)).day_status == "closed"


def test_start_up_closes_days_that_ended_while_the_erp_was_down(
    pg, db: Session, catalog: None, at_cairo
) -> None:
    from erp.main import app

    with at_cairo("2026-11-17T22:00"):
        db.add(
            DailySales(
                product_id="P001",
                business_date=date(2026, 11, 17),
                units_sold=3,
                units_returned=0,
                day_status="open",
            )
        )
        db.commit()

    with at_cairo("2026-11-19T08:00"), TestClient(app):  # entering the client runs start-up
        assert _row(db, "P001", date(2026, 11, 17)).day_status == "closed"
