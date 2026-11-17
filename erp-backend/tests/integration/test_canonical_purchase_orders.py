"""GET and POST /api/v1/canonical/purchase-orders.

Part 1, the open list: US3 scenarios 1-6, FR-023 to FR-025.
Part 2, creating a draft exactly once: US4 scenarios 1-9, FR-027 to FR-034, SC-004.

Written before the implementation.
"""

import copy
import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.models import IdempotencyRecord, PurchaseOrder, PurchaseOrderLine, Stock

from canonical_support import CANON, CONTRACTS, assert_error, validate

ERP = "/api/v1/erp"
Headers = dict[str, str]


def _order(db: Session, lines: dict[str, int], status: str = "draft") -> int:
    order = PurchaseOrder(
        supplier_id="S001",
        lines=[PurchaseOrderLine(product_id=p, quantity=q) for p, q in lines.items()],
    )
    db.add(order)
    db.commit()
    if status == "confirmed":
        from erp.services.purchase_orders import confirm

        confirm(db, order.po_id)
        db.commit()
    return order.po_id


def _open(client: TestClient, headers: Headers, **params: Any) -> dict[str, Any]:
    response = client.get(
        f"{CANON}/purchase-orders", params={"status": "open", **params}, headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    validate("canonical/purchase_order_page.schema.json", body)
    return body


# ---------------------------------------------------------------- Part 1: open orders (US3)


def test_only_drafts_are_open_with_their_quantities(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    draft = _order(db, {"P001": 60})
    _order(db, {"P001": 40}, status="confirmed")

    body = _open(client, canon_headers, product_id="P001")
    assert [o["purchase_order_id"] for o in body["items"]] == [draft]
    order = body["items"][0]
    assert order["status"] == "draft"
    assert order["supplier_id"] == "S001"
    assert order["created_by"] == "human" and order["approval"] is None
    assert order["lines"] == [
        {"product_id": "P001", "ordered_qty": 60, "received_qty": 0, "open_qty": 60}
    ]
    assert order["created_at"].endswith("Z") and order["updated_at"].endswith("Z")
    assert body["next_cursor"] is None


def test_an_order_is_returned_whole_and_others_are_filtered_out(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    both = _order(db, {"P001": 10, "P002": 20})
    body = _open(client, canon_headers, product_id="P001")
    assert [o["purchase_order_id"] for o in body["items"]] == [both]
    assert [line["product_id"] for line in body["items"][0]["lines"]] == ["P001", "P002"]

    _order(db, {"P001": 5})
    db.commit()
    assert _open(client, canon_headers, product_id="P002")["items"][0]["purchase_order_id"] == both
    assert len(_open(client, canon_headers)["items"]) == 2


def test_no_draft_for_a_product_gives_an_empty_page(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    _order(db, {"P001": 10})
    assert _open(client, canon_headers, product_id="P002") == {
        "schema": "canonical.PurchaseOrderPage",
        "version": "1.0",
        "items": [],
        "next_cursor": None,
    }


def test_a_confirmed_order_leaves_the_list_at_once(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers, auth_headers: Headers
) -> None:
    draft = _order(db, {"P001": 60})
    assert len(_open(client, canon_headers, product_id="P001")["items"]) == 1
    assert (
        client.post(f"{ERP}/purchase-orders/{draft}/confirm", headers=auth_headers).status_code
        == 200
    )
    assert _open(client, canon_headers, product_id="P001")["items"] == []


def test_paging_returns_every_order_once_in_order(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    ids = [_order(db, {"P001": n}) for n in (1, 2, 3)]
    first = _open(client, canon_headers, product_id="P001", limit=2)
    assert first["next_cursor"] is not None
    second = _open(client, canon_headers, product_id="P001", limit=2, cursor=first["next_cursor"])
    assert second["next_cursor"] is None
    seen = [o["purchase_order_id"] for o in first["items"] + second["items"]]
    assert seen == ids


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({}, "status"),
        ({"status": "draft"}, "status"),
        ({"status": "confirmed"}, "status"),
        ({"status": "open", "product_id": "p001"}, "product_id"),
        ({"status": "open", "limit": 0}, "limit"),
        ({"status": "open", "limit": 501}, "limit"),
    ],
)
def test_invalid_list_parameters_are_refused(
    client: TestClient, catalog: None, canon_headers: Headers, params: dict, field: str
) -> None:
    response = client.get(f"{CANON}/purchase-orders", params=params, headers=canon_headers)
    assert_error(response, 422, "VALIDATION_ERROR", field)


def test_a_cursor_reused_for_another_product_is_refused(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    for n in (1, 2):
        _order(db, {"P001": n, "P002": n})
    cursor = _open(client, canon_headers, product_id="P001", limit=1)["next_cursor"]
    response = client.get(
        f"{CANON}/purchase-orders",
        params={"status": "open", "product_id": "P002", "cursor": cursor},
        headers=canon_headers,
    )
    assert_error(response, 422, "VALIDATION_ERROR", "cursor")
    response = client.get(
        f"{CANON}/purchase-orders",
        params={"status": "open", "product_id": "P001", "cursor": cursor + "x"},
        headers=canon_headers,
    )
    assert_error(response, 422, "VALIDATION_ERROR", "cursor")


# ---------------------------------------------------------------- Part 2: POST (US4)

FIXTURE = CONTRACTS / "fixtures/valid/canonical/create_draft_po_request/from_proposal.json"


def request_body(key: str, supplier: str = "S001", lines: dict[str, int] | None = None) -> dict:
    """The contract's valid fixture, re-keyed to the given proposal UUID and catalog."""
    body = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["document"])
    body["supplier_id"] = supplier
    body["lines"] = [{"product_id": p, "quantity": q} for p, q in (lines or {"P001": 120}).items()]
    body["approval"]["proposal_id"] = key
    return body


def _with(body: dict, path: tuple, value: Any) -> dict:
    target = body
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return body


def _without(body: dict, name: str) -> dict:
    return {k: v for k, v in body.items() if k != name}


def post(client: TestClient, headers: Headers, key: str | None, body: Any):
    sent = dict(headers)
    if key is not None:
        sent["Idempotency-Key"] = key
    if isinstance(body, (str, bytes)):
        sent["Content-Type"] = "application/json"
        return client.post(f"{CANON}/purchase-orders", content=body, headers=sent)
    return client.post(f"{CANON}/purchase-orders", json=body, headers=sent)


def _counts(db: Session) -> tuple[int, int]:
    db.expire_all()
    return (
        db.scalar(select(func.count()).select_from(PurchaseOrder)) or 0,
        db.scalar(select(func.count()).select_from(IdempotencyRecord)) or 0,
    )


def _stock(db: Session) -> dict[str, int]:
    db.expire_all()
    return {s.product_id: s.on_hand for s in db.scalars(select(Stock))}


def test_the_brain_creates_a_draft_from_an_approved_proposal(
    client: TestClient, db: Session, at_cairo, seed, service_token
) -> None:
    key = str(uuid.uuid4())
    with at_cairo("2026-11-18T13:05"):
        seed()
        stock_before = _stock(db)
        body = request_body(key, supplier="S004", lines={"P003": 120})
        response = post(client, {"Authorization": f"Bearer {service_token()}"}, key, body)

    assert response.status_code == 201, response.text
    order = response.json()
    validate("canonical/purchase_order.schema.json", order)
    assert order["status"] == "draft" and order["created_by"] == "agent"
    assert order["supplier_id"] == "S004"
    assert order["approval"] == body["approval"]
    assert order["lines"] == [
        {"product_id": "P003", "ordered_qty": 120, "received_qty": 0, "open_qty": 120}
    ]
    assert _counts(db) == (1, 1)
    assert _stock(db) == stock_before


def test_same_key_and_body_replays_the_original_response(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    key = str(uuid.uuid4())
    body = request_body(key)
    first = post(client, canon_headers, key, body)
    assert first.status_code == 201, first.text

    again = post(client, canon_headers, key, body)
    reordered = json.dumps(dict(reversed(list(body.items()))), indent=3)
    spaced = post(client, canon_headers, key, reordered)
    for replay in (again, spaced):
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json()  # content, not bytes: the stored body is jsonb
        validate("canonical/purchase_order.schema.json", replay.json())
    assert _counts(db) == (1, 1)


def test_a_used_key_with_any_other_body_is_a_conflict(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    key = str(uuid.uuid4())
    body = request_body(key)
    original = post(client, canon_headers, key, body)
    assert original.status_code == 201

    other_proposal = _with(request_body(key), ("approval", "proposal_id"), str(uuid.uuid4()))
    others: list[Any] = [
        request_body(key, lines={"P001": 121}),
        request_body(key, lines={"P001": 0}),
        _without(body, "approval"),
        {**body, "note": "urgent"},
        other_proposal,
        '{"supplier_id":',
    ]
    for other in others:
        assert_error(post(client, canon_headers, key, other), 409, "IDEMPOTENCY_CONFLICT")
    assert _counts(db) == (1, 1)
    assert post(client, canon_headers, key, body).json() == original.json()
    # Without a usable key there is nothing to look up: still a validation error.
    assert_error(
        post(client, canon_headers, None, body), 422, "VALIDATION_ERROR", "Idempotency-Key"
    )


def _many_lines(n: int) -> dict[str, int]:
    return {f"P{index:03d}": 1 for index in range(1, n + 1)}


REFUSALS: list[tuple[str, Callable[[str], tuple[str | None, Any]], str]] = [
    ("no header", lambda k: (None, request_body(k)), "Idempotency-Key"),
    ("header not a UUID", lambda k: ("not-a-uuid", request_body(k)), "Idempotency-Key"),
    (
        "header differs from proposal_id",
        lambda k: (k, request_body(str(uuid.uuid4()))),
        "approval.proposal_id",
    ),
    ("no approval", lambda k: (k, _without(request_body(k), "approval")), "approval"),
    ("quantity 0", lambda k: (k, request_body(k, lines={"P001": 0})), "lines[0].quantity"),
    ("quantity -1", lambda k: (k, request_body(k, lines={"P001": -1})), "lines[0].quantity"),
    (
        "quantity 1.5",
        lambda k: (k, _with(request_body(k), ("lines", 0, "quantity"), 1.5)),
        "lines[0].quantity",
    ),
    (
        "upper-case hash",
        lambda k: (k, _with(request_body(k), ("approval", "arguments_sha256"), "D" * 64)),
        "approval.arguments_sha256",
    ),
    (
        "approved_by empty",
        lambda k: (k, _with(request_body(k), ("approval", "approved_by"), "")),
        "approval.approved_by",
    ),
    (
        "approved_by 129 characters",
        lambda k: (k, _with(request_body(k), ("approval", "approved_by"), "m" * 129)),
        "approval.approved_by",
    ),
    (
        "approved_at without a time zone",
        lambda k: (k, _with(request_body(k), ("approval", "approved_at"), "2026-11-18T11:02:00")),
        "approval.approved_at",
    ),
    (
        "approved_at with +02:00",
        lambda k: (
            k,
            _with(request_body(k), ("approval", "approved_at"), "2026-11-18T13:02:00+02:00"),
        ),
        "approval.approved_at",
    ),
    (
        "upper-case proposal_id",
        lambda k: (k.upper(), _with(request_body(k), ("approval", "proposal_id"), k.upper())),
        "approval.proposal_id",
    ),
    ("note field", lambda k: (k, {**request_body(k), "note": "urgent"}), "note"),
    ("unknown supplier", lambda k: (k, request_body(k, supplier="S999")), "supplier_id"),
    ("unknown product", lambda k: (k, request_body(k, lines={"P999": 5})), "lines[0].product_id"),
    (
        "same product twice",
        lambda k: (
            k,
            _with(request_body(k), ("lines",), [{"product_id": "P001", "quantity": 1}] * 2),
        ),
        "lines",
    ),
    ("no lines", lambda k: (k, _with(request_body(k), ("lines",), [])), "lines"),
    ("51 lines", lambda k: (k, request_body(k, lines=_many_lines(51))), "lines"),
    ("not JSON", lambda k: (k, '{"supplier_id":'), "body"),
]


@pytest.mark.parametrize(("name", "build", "field"), REFUSALS, ids=[r[0] for r in REFUSALS])
def test_refused_requests_create_nothing_and_leave_the_key_free(
    client: TestClient,
    db: Session,
    catalog: None,
    canon_headers: Headers,
    name: str,
    build: Callable[[str], tuple[str | None, Any]],
    field: str,
) -> None:
    key = str(uuid.uuid4())
    header, body = build(key)
    assert_error(post(client, canon_headers, header, body), 422, "VALIDATION_ERROR", field)
    assert _counts(db) == (0, 0)
    retry = post(client, canon_headers, key, request_body(key))
    assert retry.status_code == 201, retry.text  # FR-032: the refusal did not use up the key


def test_the_erp_does_not_judge_supplier_quantities_or_the_approval(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    from erp.models import Supplier

    db.add(Supplier(name="Delta Health", lead_time_days=5))  # S002: nobody's preferred supplier
    db.commit()
    key = str(uuid.uuid4())
    body = request_body(key, supplier="S002", lines={"P001": 7, "P002": 999})
    body["approval"]["approved_at"] = "2030-01-01T00:00:00Z"  # in the future
    body["approval"]["approved_by"] = "someone-else"
    response = post(client, canon_headers, key, body)
    assert response.status_code == 201, response.text
    assert response.json()["approval"] == body["approval"]
    assert [line["ordered_qty"] for line in response.json()["lines"]] == [7, 999]


def test_ten_identical_requests_at_once_create_one_draft(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers
) -> None:
    key = str(uuid.uuid4())
    body = request_body(key)
    barrier = threading.Barrier(10)
    results: list[Any] = []
    lock = threading.Lock()

    def send() -> None:
        barrier.wait()
        response = post(client, canon_headers, key, body)
        with lock:
            results.append(response)

    threads = [threading.Thread(target=send) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(r.status_code for r in results) == [200] * 9 + [201]
    assert len({r.json()["purchase_order_id"] for r in results}) == 1
    assert _counts(db) == (1, 1)


def test_confirming_the_brains_draft_adds_its_stock_and_replays_still_match(
    client: TestClient, db: Session, catalog: None, canon_headers: Headers, auth_headers: Headers
) -> None:
    key = str(uuid.uuid4())
    body = request_body(key, lines={"P001": 30, "P002": 5})
    created = post(client, canon_headers, key, body)
    assert created.status_code == 201
    before = _stock(db)
    po_id = created.json()["purchase_order_id"]

    confirmed = client.post(f"{ERP}/purchase-orders/{po_id}/confirm", headers=auth_headers)
    assert confirmed.status_code == 200
    after = _stock(db)
    assert after == {"P001": before["P001"] + 30, "P002": before["P002"] + 5}
    assert _open(client, canon_headers, product_id="P001")["items"] == []

    replay = post(client, canon_headers, key, body)
    assert replay.status_code == 200
    assert replay.json() == created.json()  # the order as it was when created
    assert replay.json()["status"] == "draft"
    assert _stock(db) == after


def test_a_reseed_wipes_the_idempotency_keys(
    client: TestClient, db: Session, at_cairo, seed, service_token
) -> None:
    with at_cairo("2026-11-18T10:00"):
        seed()
        key = str(uuid.uuid4())
        headers = {"Authorization": f"Bearer {service_token()}"}
        assert (
            post(
                client, headers, key, request_body(key, supplier="S004", lines={"P003": 12})
            ).status_code
            == 201
        )
        assert _counts(db) == (1, 1)
        seed()  # run_seed(reset=True), as `python -m erp.seed --reset` does
    assert _counts(db) == (0, 0)
