"""GET products/{id}, inventory/{id} and suppliers/{id} (US2 scenarios 1-5, FR-018 to FR-022).

Written before the implementation.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from erp.models import Stock

from canonical_support import CANON, assert_error, validate

NOW = "2026-11-18T10:00"
ERP = "/api/v1/erp"
REMOVED = {
    "sku",
    "unit",
    "active",
    "tenant_id",
    "location_id",
    "inventory_scope",
    "reserved",
    "reorder_point",
}


def _ok(client: TestClient, path: str, headers: dict[str, str], schema: str) -> dict:
    response = client.get(f"{CANON}/{path}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    validate(f"canonical/{schema}.schema.json", body)
    assert not REMOVED & body.keys()
    return body


def test_product_stock_and_supplier_of_the_seed(
    client: TestClient, db: Session, at_cairo, seed, service_token
) -> None:
    with at_cairo(NOW):
        seed()
        headers = {"Authorization": f"Bearer {service_token()}"}
        product = _ok(client, "products/P003", headers, "product")
        stock = _ok(client, "inventory/P003", headers, "inventory_item")
        supplier = _ok(client, "suppliers/S004", headers, "supplier")

    assert product["schema"] == "canonical.Product" and product["version"] == "1.0"
    assert product["product_id"] == "P003"
    assert product["name"] == "Amoxicillin 500 mg capsules"
    assert (
        product["preferred_supplier_id"],
        product["pack_multiple"],
        product["max_order_qty"],
    ) == (
        "S004",
        12,
        240,
    )
    assert product["updated_at"].endswith("Z")

    row = db.scalars(select(Stock).where(Stock.product_id == "P003")).one()
    assert stock["schema"] == "canonical.InventoryItem"
    assert stock["on_hand"] == stock["available"] == row.on_hand
    assert datetime.fromisoformat(stock["updated_at"]) == row.updated_at

    assert supplier["schema"] == "canonical.Supplier"
    assert (supplier["supplier_id"], supplier["lead_time_days"]) == ("S004", 7)


def test_changes_made_on_the_erp_screens_are_read_back(
    client: TestClient, at_cairo, seed, service_token, login
) -> None:
    with at_cairo(NOW) as clock:
        seed()
        headers = {"Authorization": f"Bearer {service_token()}"}
        before = _ok(client, "inventory/P003", headers, "inventory_item")
        clock.shift(timedelta(minutes=1))
        manager = login()
        assert (
            client.put(f"{ERP}/inventory/P003", json={"on_hand": 95}, headers=manager).status_code
            == 200
        )
        assert (
            client.patch(
                f"{ERP}/suppliers/S004", json={"lead_time_days": 6}, headers=manager
            ).status_code
            == 200
        )
        after = _ok(client, "inventory/P003", headers, "inventory_item")
        supplier = _ok(client, "suppliers/S004", headers, "supplier")

    assert after["on_hand"] == after["available"] == 95
    assert datetime.fromisoformat(after["updated_at"]) > datetime.fromisoformat(
        before["updated_at"]
    )
    assert supplier["lead_time_days"] == 6


@pytest.mark.parametrize("path", ["products/P999", "inventory/P999", "suppliers/S999"])
def test_unknown_ids_are_not_found(
    client: TestClient, catalog: None, canon_headers: dict[str, str], path: str
) -> None:
    assert_error(client.get(f"{CANON}/{path}", headers=canon_headers), 404, "NOT_FOUND")


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("products/p003", "product_id"),
        ("products/P03", "product_id"),
        ("products/X001", "product_id"),
        ("inventory/S001", "product_id"),
        ("suppliers/P001", "supplier_id"),
        ("suppliers/S1", "supplier_id"),
    ],
)
def test_ids_in_the_wrong_format_are_validation_errors(
    client: TestClient, catalog: None, canon_headers: dict[str, str], path: str, field: str
) -> None:
    assert_error(
        client.get(f"{CANON}/{path}", headers=canon_headers), 422, "VALIDATION_ERROR", field
    )


def test_four_digit_ids_are_read_back_whole(
    client: TestClient,
    db: Session,
    catalog: None,
    auth_headers: dict[str, str],
    canon_headers: dict[str, str],
) -> None:
    db.execute(text("SELECT setval('product_code_seq', 1000, false)"))
    db.commit()
    created = client.post(
        f"{ERP}/products",
        json={
            "name": "Cetirizine 10 mg",
            "preferred_supplier_id": "S001",
            "pack_multiple": 10,
            "max_order_qty": 200,
            "starting_stock": 30,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["product_id"] == "P1000"
    assert _ok(client, "products/P1000", canon_headers, "product")["product_id"] == "P1000"
    assert _ok(client, "inventory/P1000", canon_headers, "inventory_item")["on_hand"] == 30
