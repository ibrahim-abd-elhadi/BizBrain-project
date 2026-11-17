"""Stock at the pharmacy's one location (FR-005). Written before the implementation."""

import pytest
from fastapi.testclient import TestClient

BASE = "/api/v1/erp"
Headers = dict[str, str]


@pytest.fixture
def two_products(client: TestClient, auth_headers: Headers) -> None:
    client.post(
        f"{BASE}/suppliers", json={"name": "Nile Pharma", "lead_time_days": 3}, headers=auth_headers
    )
    for name, stock in (("Paracetamol 500 mg", 12), ("Ibuprofen 400 mg", 0)):
        response = client.post(
            f"{BASE}/products",
            json={
                "name": name,
                "preferred_supplier_id": "S001",
                "pack_multiple": 10,
                "max_order_qty": 400,
                "starting_stock": stock,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text


def test_inventory_lists_one_row_per_product_with_no_location(
    client: TestClient, auth_headers: Headers, two_products: None
) -> None:
    rows = client.get(f"{BASE}/inventory", headers=auth_headers).json()
    assert [r["product_id"] for r in rows] == ["P001", "P002"]
    assert [r["on_hand"] for r in rows] == [12, 0]
    assert rows[0]["name"] == "Paracetamol 500 mg"
    assert "updated_at" in rows[0]
    for row in rows:
        assert not {"location", "location_id", "branch", "branch_id"} & set(row)


def test_stock_can_be_set_by_hand(
    client: TestClient, auth_headers: Headers, two_products: None
) -> None:
    response = client.put(f"{BASE}/inventory/P001", json={"on_hand": 25}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["on_hand"] == 25
    assert response.json()["product_id"] == "P001"

    rows = client.get(f"{BASE}/inventory", headers=auth_headers).json()
    assert rows[0]["on_hand"] == 25

    assert (
        client.put(f"{BASE}/inventory/P001", json={"on_hand": 0}, headers=auth_headers).status_code
        == 200
    )


def test_negative_or_fractional_stock_is_refused(
    client: TestClient, auth_headers: Headers, two_products: None
) -> None:
    for bad in (-1, 1.5, "ten"):
        response = client.put(f"{BASE}/inventory/P001", json={"on_hand": bad}, headers=auth_headers)
        assert response.status_code == 422, bad
        assert response.json()["code"] == "VALIDATION_ERROR"
    assert client.get(f"{BASE}/inventory", headers=auth_headers).json()[0]["on_hand"] == 12


def test_unknown_product_is_not_found(
    client: TestClient, auth_headers: Headers, two_products: None
) -> None:
    response = client.put(f"{BASE}/inventory/P099", json={"on_hand": 5}, headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_inventory_needs_a_token(client: TestClient, manager: str) -> None:
    assert client.get(f"{BASE}/inventory").status_code == 401
    assert client.put(f"{BASE}/inventory/P001", json={"on_hand": 1}).status_code == 401
