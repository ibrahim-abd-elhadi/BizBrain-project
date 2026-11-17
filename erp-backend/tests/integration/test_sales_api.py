"""GET /sales: daily totals with day status (FR-020). Written before the implementation."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from erp.models import DailySales

BASE = "/api/v1/erp"
TODAY = date(2026, 11, 18)


def _add(db: Session, product_id: str, day: date, sold: int, returned: int, status: str) -> None:
    db.add(
        DailySales(
            product_id=product_id,
            business_date=day,
            units_sold=sold,
            units_returned=returned,
            day_status=status,
        )
    )


def test_default_request_returns_today_and_items_newest_first(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo("2026-11-18T10:00"):
        _add(db, "P001", TODAY - timedelta(days=2), 10, 1, "closed")
        _add(db, "P002", TODAY - timedelta(days=1), 4, 0, "closed")
        _add(db, "P001", TODAY - timedelta(days=1), 6, 0, "closed")
        _add(db, "P001", TODAY, 3, 0, "open")
        db.commit()

        body = client.get(f"{BASE}/sales", headers=login()).json()

    assert body["today"] == "2026-11-18"
    assert [(i["business_date"], i["product_id"]) for i in body["items"]] == [
        ("2026-11-18", "P001"),
        ("2026-11-17", "P001"),
        ("2026-11-17", "P002"),
        ("2026-11-16", "P001"),
    ]
    assert body["items"][0] == {
        "product_id": "P001",
        "business_date": "2026-11-18",
        "units_sold": 3,
        "units_returned": 0,
        "net_units": 3,
        "day_status": "open",
    }
    assert body["items"][-1]["net_units"] == 9


def test_default_range_covers_90_closed_days_plus_today(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo("2026-11-18T10:00"):
        _add(db, "P001", TODAY - timedelta(days=90), 1, 0, "closed")  # the oldest of 90 closed days
        _add(db, "P001", TODAY - timedelta(days=91), 1, 0, "closed")  # one day too old
        _add(db, "P001", TODAY, 1, 0, "open")
        db.commit()
        items = client.get(f"{BASE}/sales", headers=login()).json()["items"]
    assert [i["business_date"] for i in items] == [str(TODAY), str(TODAY - timedelta(days=90))]


def test_filters_by_product_and_date_range(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo("2026-11-18T10:00"):
        for offset in (1, 2, 3):
            _add(db, "P001", TODAY - timedelta(days=offset), 5, 0, "closed")
            _add(db, "P002", TODAY - timedelta(days=offset), 7, 0, "closed")
        db.commit()
        headers = login()

        only_p1 = client.get(f"{BASE}/sales", params={"product_id": "P001"}, headers=headers)
        assert {i["product_id"] for i in only_p1.json()["items"]} == {"P001"}
        assert len(only_p1.json()["items"]) == 3

        window = client.get(
            f"{BASE}/sales", params={"from": "2026-11-16", "to": "2026-11-17"}, headers=headers
        )
        assert {i["business_date"] for i in window.json()["items"]} == {"2026-11-16", "2026-11-17"}


def test_from_after_to_is_refused(client: TestClient, manager: str, at_cairo, login) -> None:
    with at_cairo("2026-11-18T10:00"):
        response = client.get(
            f"{BASE}/sales", params={"from": "2026-11-18", "to": "2026-11-01"}, headers=login()
        )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_sales_needs_a_token(client: TestClient, manager: str) -> None:
    response = client.get(f"{BASE}/sales")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
