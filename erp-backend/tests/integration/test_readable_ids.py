"""Readable IDs keep every digit past 999: P999 → P1000, never P100 (research R-21).

PostgreSQL's lpad() truncates text longer than its target length, so the original
`'P' || lpad(n::text, 3, '0')` turned 1000 into "P100" and collided with the real P100.
"""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

BASE = "/api/v1/erp"
Headers = dict[str, str]


def _next_ids_from(db: Session, value: int) -> None:
    """The next supplier and product IDs will be number `value`."""
    db.execute(text("SELECT setval('supplier_code_seq', :v, false)"), {"v": value})
    db.execute(text("SELECT setval('product_code_seq', :v, false)"), {"v": value})
    db.commit()


def _supplier(client: TestClient, headers: Headers, name: str) -> str:
    response = client.post(
        f"{BASE}/suppliers", json={"name": name, "lead_time_days": 4}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["supplier_id"]


def _product(client: TestClient, headers: Headers, name: str, supplier_id: str) -> str:
    response = client.post(
        f"{BASE}/products",
        json={
            "name": name,
            "preferred_supplier_id": supplier_id,
            "pack_multiple": 10,
            "max_order_qty": 200,
            "starting_stock": 30,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["product_id"]


def test_ids_grow_past_999_without_truncation(
    client: TestClient, db: Session, auth_headers: Headers
) -> None:
    _next_ids_from(db, 999)

    suppliers = [_supplier(client, auth_headers, f"Supplier {i}") for i in range(3)]
    assert suppliers == ["S999", "S1000", "S1001"]

    products = [_product(client, auth_headers, f"Product {i}", "S1000") for i in range(3)]
    assert products == ["P999", "P1000", "P1001"]


def test_small_ids_keep_three_digits(client: TestClient, auth_headers: Headers) -> None:
    supplier = _supplier(client, auth_headers, "First supplier")
    assert supplier == "S001"
    assert _product(client, auth_headers, "First product", supplier) == "P001"


def test_four_digit_ids_work_everywhere_an_id_is_accepted(
    client: TestClient, db: Session, auth_headers: Headers
) -> None:
    _next_ids_from(db, 1000)
    supplier = _supplier(client, auth_headers, "Big supplier")
    product = _product(client, auth_headers, "Big product", supplier)
    assert (supplier, product) == ("S1000", "P1000")

    # Reads and edits by ID.
    assert client.get(f"{BASE}/suppliers/S1000", headers=auth_headers).status_code == 200
    assert client.get(f"{BASE}/products/P1000", headers=auth_headers).status_code == 200
    edited = client.patch(
        f"{BASE}/products/P1000", json={"preferred_supplier_id": "S1000"}, headers=auth_headers
    )
    assert edited.status_code == 200, edited.text
    stock = client.put(f"{BASE}/inventory/P1000", json={"on_hand": 12}, headers=auth_headers)
    assert stock.status_code == 200, stock.text

    # Query and body fields that carry an ID accept four digits too.
    sales = client.get(f"{BASE}/sales", params={"product_id": "P1000"}, headers=auth_headers)
    assert sales.status_code == 200, sales.text
    spike = client.post(
        f"{BASE}/sales/simulate", json={"spike_product_id": "P1000"}, headers=auth_headers
    )
    assert spike.status_code == 422
    assert spike.json()["code"] == "SPIKE_NEEDS_HISTORY"  # the ID is valid; it's just too new

    # Still refused: malformed IDs.
    for bad in ("S10", "X1000", "S1000a"):
        refused = client.post(
            f"{BASE}/products",
            json={
                "name": "Nope",
                "preferred_supplier_id": bad,
                "pack_multiple": 1,
                "max_order_qty": 1,
            },
            headers=auth_headers,
        )
        assert refused.status_code == 422, bad
        assert refused.json()["code"] == "VALIDATION_ERROR", bad


def test_the_code_function_pads_to_three_digits_and_never_truncates(db: Session) -> None:
    rows = db.execute(
        text("SELECT readable_code('P', n) FROM unnest(ARRAY[1, 42, 999, 1000, 1001, 123456]) AS n")
    ).scalars()
    assert list(rows) == ["P001", "P042", "P999", "P1000", "P1001", "P123456"]
