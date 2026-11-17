"""Suppliers and products (FR-003, FR-004, FR-022). Written before the implementation."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

BASE = "/api/v1/erp"
Headers = dict[str, str]


def create_supplier(client: TestClient, headers: Headers, **overrides) -> dict:
    body = {"name": "Nile Pharma", "lead_time_days": 3, **overrides}
    response = client.post(f"{BASE}/suppliers", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def product_body(supplier_id: str, **overrides) -> dict:
    return {
        "name": "Paracetamol 500 mg",
        "preferred_supplier_id": supplier_id,
        "pack_multiple": 10,
        "max_order_qty": 400,
        **overrides,
    }


def test_supplier_is_created_with_an_assigned_id_and_can_be_edited(
    client: TestClient, auth_headers: Headers
) -> None:
    supplier = create_supplier(client, auth_headers)
    assert supplier == {"supplier_id": "S001", "name": "Nile Pharma", "lead_time_days": 3}
    assert create_supplier(client, auth_headers, name="Delta Meds")["supplier_id"] == "S002"

    response = client.patch(
        f"{BASE}/suppliers/S001", json={"lead_time_days": 5}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["lead_time_days"] == 5
    assert response.json()["name"] == "Nile Pharma"

    listed = client.get(f"{BASE}/suppliers", headers=auth_headers).json()
    assert [s["supplier_id"] for s in listed] == ["S001", "S002"]
    assert client.get(f"{BASE}/suppliers/S001", headers=auth_headers).json()["lead_time_days"] == 5
    assert client.get(f"{BASE}/suppliers/S099", headers=auth_headers).status_code == 404


def test_supplier_lead_time_must_be_at_least_one_day(
    client: TestClient, auth_headers: Headers
) -> None:
    response = client.post(
        f"{BASE}/suppliers", json={"name": "X", "lead_time_days": 0}, headers=auth_headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"

    create_supplier(client, auth_headers)
    patched = client.patch(
        f"{BASE}/suppliers/S001", json={"lead_time_days": 0}, headers=auth_headers
    )
    assert patched.status_code == 422


def test_product_with_unknown_supplier_is_refused(
    client: TestClient, auth_headers: Headers
) -> None:
    response = client.post(f"{BASE}/products", json=product_body("S099"), headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["code"] == "SUPPLIER_NOT_FOUND"


def test_max_order_qty_cannot_be_below_pack_multiple(
    client: TestClient, auth_headers: Headers
) -> None:
    create_supplier(client, auth_headers)
    response = client.post(
        f"{BASE}/products",
        json=product_body("S001", pack_multiple=10, max_order_qty=5),
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "MAX_BELOW_PACK"

    created = client.post(
        f"{BASE}/products", json=product_body("S001"), headers=auth_headers
    ).json()
    patched = client.patch(
        f"{BASE}/products/{created['product_id']}",
        json={"max_order_qty": 5},
        headers=auth_headers,
    )
    assert patched.status_code == 422
    assert patched.json()["code"] == "MAX_BELOW_PACK"


def test_product_creation_assigns_an_id_and_a_stock_row(
    client: TestClient, auth_headers: Headers, db: Session
) -> None:
    create_supplier(client, auth_headers)
    response = client.post(
        f"{BASE}/products", json=product_body("S001", starting_stock=42), headers=auth_headers
    )
    assert response.status_code == 201, response.text
    assert response.json() == {
        "product_id": "P001",
        "name": "Paracetamol 500 mg",
        "preferred_supplier_id": "S001",
        "pack_multiple": 10,
        "max_order_qty": 400,
    }
    assert db.execute(text("select on_hand from stock where product_id = 'P001'")).scalar() == 42

    second = client.post(
        f"{BASE}/products", json=product_body("S001", name="Ibuprofen 400 mg"), headers=auth_headers
    ).json()
    assert second["product_id"] == "P002"
    assert db.execute(text("select on_hand from stock where product_id = 'P002'")).scalar() == 0


def test_product_can_be_edited_but_its_id_cannot_change(
    client: TestClient, auth_headers: Headers
) -> None:
    create_supplier(client, auth_headers)
    create_supplier(client, auth_headers, name="Delta Meds")
    client.post(f"{BASE}/products", json=product_body("S001"), headers=auth_headers)

    edited = client.patch(
        f"{BASE}/products/P001",
        json={"name": "Paracetamol 1 g", "preferred_supplier_id": "S002", "pack_multiple": 20},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "Paracetamol 1 g"
    assert edited.json()["preferred_supplier_id"] == "S002"
    assert edited.json()["pack_multiple"] == 20

    with_id = client.patch(
        f"{BASE}/products/P001", json={"product_id": "P999"}, headers=auth_headers
    )
    assert with_id.status_code == 422
    assert client.get(f"{BASE}/products/P999", headers=auth_headers).status_code == 404
    assert client.get(f"{BASE}/products/P001", headers=auth_headers).status_code == 200


def test_there_is_no_way_to_delete_anything(client: TestClient, auth_headers: Headers) -> None:
    create_supplier(client, auth_headers)
    client.post(f"{BASE}/products", json=product_body("S001"), headers=auth_headers)
    for path in ("/products/P001", "/suppliers/S001", "/products", "/suppliers"):
        response = client.delete(f"{BASE}{path}", headers=auth_headers)
        assert response.status_code == 405, path
        assert response.json()["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/suppliers", None),
        ("POST", "/suppliers", {"name": "X", "lead_time_days": 2}),
        ("GET", "/suppliers/S001", None),
        ("PATCH", "/suppliers/S001", {"lead_time_days": 2}),
        ("GET", "/products", None),
        (
            "POST",
            "/products",
            {"name": "X", "preferred_supplier_id": "S001", "pack_multiple": 1, "max_order_qty": 1},
        ),
        ("GET", "/products/P001", None),
        ("PATCH", "/products/P001", {"name": "Y"}),
    ],
)
def test_every_catalog_endpoint_needs_a_token(
    client: TestClient, manager: str, method: str, path: str, body: dict | None
) -> None:
    response = client.request(method, f"{BASE}{path}", json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
