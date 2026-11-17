"""Confirming draft purchase orders (FR-016, FR-017, FR-018, FR-024).

Written before the implementation. Drafts normally come from the Brain (feature 002), so each test
inserts one directly through the session.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erp.config import get_settings
from erp.models import PurchaseOrder, PurchaseOrderLine, Stock
from erp.seed.__main__ import run_seed

BASE = "/api/v1/erp"
Headers = dict[str, str]


@pytest.fixture
def draft(db: Session, catalog: None) -> int:
    """A draft purchase order with the line P001 x 60, and P001's stock at 10."""
    db.execute(update(Stock).where(Stock.product_id == "P001").values(on_hand=10))
    order = PurchaseOrder(lines=[PurchaseOrderLine(product_id="P001", quantity=60)])
    db.add(order)
    db.commit()
    return order.po_id


def _on_hand(db: Session, product_id: str = "P001") -> int:
    db.expire_all()
    return db.scalar(select(Stock.on_hand).where(Stock.product_id == product_id))  # type: ignore[return-value]


def test_list_shows_the_draft_with_its_lines(
    client: TestClient, auth_headers: Headers, draft: int
) -> None:
    orders = client.get(f"{BASE}/purchase-orders", headers=auth_headers).json()
    assert len(orders) == 1
    order = orders[0]
    assert order["po_id"] == draft
    assert order["status"] == "draft"
    assert order["confirmed_at"] is None
    assert order["created_at"]
    assert order["lines"] == [{"product_id": "P001", "quantity": 60}]

    one = client.get(f"{BASE}/purchase-orders/{draft}", headers=auth_headers)
    assert one.status_code == 200
    assert one.json()["status"] == "draft"


def test_confirming_adds_the_lines_to_stock(
    client: TestClient, db: Session, auth_headers: Headers, draft: int
) -> None:
    response = client.post(f"{BASE}/purchase-orders/{draft}/confirm", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    assert _on_hand(db) == 70


def test_confirming_twice_adds_nothing_the_second_time(
    client: TestClient, db: Session, auth_headers: Headers, draft: int
) -> None:
    first = client.post(f"{BASE}/purchase-orders/{draft}/confirm", headers=auth_headers).json()
    second = client.post(f"{BASE}/purchase-orders/{draft}/confirm", headers=auth_headers)

    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"
    assert second.json()["confirmed_at"] == first["confirmed_at"]
    assert _on_hand(db) == 70


def test_confirming_needs_a_token_and_leaves_the_draft_alone(
    client: TestClient, db: Session, manager: str, draft: int
) -> None:
    response = client.post(f"{BASE}/purchase-orders/{draft}/confirm")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    db.expire_all()
    assert db.get(PurchaseOrder, draft).status == "draft"  # type: ignore[union-attr]
    assert _on_hand(db) == 10
    assert client.get(f"{BASE}/purchase-orders").status_code == 401


def test_unknown_order_is_not_found(client: TestClient, auth_headers: Headers, draft: int) -> None:
    for call in (
        client.get(f"{BASE}/purchase-orders/9999", headers=auth_headers),
        client.post(f"{BASE}/purchase-orders/9999/confirm", headers=auth_headers),
    ):
        assert call.status_code == 404
        assert call.json()["code"] == "NOT_FOUND"


def test_list_filters_by_status_and_lists_newest_first(
    client: TestClient, db: Session, auth_headers: Headers, draft: int
) -> None:
    second = PurchaseOrder(lines=[PurchaseOrderLine(product_id="P002", quantity=30)])
    db.add(second)
    db.commit()
    client.post(f"{BASE}/purchase-orders/{draft}/confirm", headers=auth_headers)

    everything = client.get(f"{BASE}/purchase-orders", headers=auth_headers).json()
    assert [o["po_id"] for o in everything] == [second.po_id, draft]

    drafts = client.get(f"{BASE}/purchase-orders?status=draft", headers=auth_headers).json()
    assert [o["po_id"] for o in drafts] == [second.po_id]
    confirmed = client.get(f"{BASE}/purchase-orders?status=confirmed", headers=auth_headers).json()
    assert [o["po_id"] for o in confirmed] == [draft]

    bad = client.get(f"{BASE}/purchase-orders?status=shipped", headers=auth_headers)
    assert bad.status_code == 422


def test_there_is_no_way_to_create_edit_or_delete_an_order(
    client: TestClient, auth_headers: Headers, draft: int
) -> None:
    assert client.post(f"{BASE}/purchase-orders", json={}, headers=auth_headers).status_code == 405
    assert client.delete(f"{BASE}/purchase-orders/{draft}", headers=auth_headers).status_code == 405
    assert (
        client.patch(f"{BASE}/purchase-orders/{draft}", json={}, headers=auth_headers).status_code
        == 405
    )


def test_database_refuses_a_confirmed_order_without_a_confirmation_time(
    db: Session, draft: int
) -> None:
    with pytest.raises(IntegrityError):
        db.execute(
            text("UPDATE purchase_order SET status = 'confirmed' WHERE po_id = :id"), {"id": draft}
        )
        db.commit()
    db.rollback()


def test_database_refuses_a_non_positive_quantity(db: Session, draft: int) -> None:
    with pytest.raises(IntegrityError):
        db.add(PurchaseOrderLine(po_id=draft, product_id="P002", quantity=0))
        db.commit()
    db.rollback()


def test_seeding_creates_no_purchase_orders(db: Session, at_cairo) -> None:
    with at_cairo("2026-11-18T10:00"):
        run_seed(db, get_settings(), reset=True)
        db.commit()
    assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 0
