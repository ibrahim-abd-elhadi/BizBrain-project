"""What an ERP answer means for a proposal (feature 004, research R-07; FR-017 to FR-019).
One case per row of the outcome table. Written before the implementation."""

import uuid
from types import SimpleNamespace

import pytest

from brain.canonical.client import SendResult
from brain.proposals.execution import classify

PID = uuid.UUID("11111111-1111-4111-8111-111111111111")
PROPOSAL = SimpleNamespace(
    id=PID,
    supplier_id="S004",
    arguments={"supplier_id": "S004", "lines": [{"product_id": "P003", "quantity": 108}]},
)
TOKEN = "test-service-token"


def _order(**changes) -> dict:
    order = {
        "schema": "canonical.PurchaseOrder",
        "version": "1.0",
        "purchase_order_id": 1001,
        "supplier_id": "S004",
        "status": "draft",
        "lines": [{"product_id": "P003", "ordered_qty": 108, "received_qty": 0, "open_qty": 108}],
        "created_by": "agent",
        "approval": {
            "proposal_id": str(PID),
            "approved_by": "manager",
            "approved_at": "2026-11-18T09:00:00.000Z",
            "arguments_sha256": "a" * 64,
        },
        "created_at": "2026-11-18T09:00:01Z",
        "updated_at": "2026-11-18T09:00:01Z",
    }
    order.update(changes)
    return order


def _error(code: str, message: str = "refused") -> dict:
    return {"error": {"code": code, "message": message, "details": [], "trace_id": "0" * 32}}


@pytest.mark.parametrize("status", [201, 200])
def test_a_matching_draft_is_created(status) -> None:
    outcome = classify(SendResult(status=status, body=_order()), PROPOSAL)
    assert (outcome.status, outcome.outcome, outcome.purchase_order_id) == (
        "draft_created",
        "draft_created",
        1001,
    )
    assert outcome.http_status == status


@pytest.mark.parametrize(
    "body",
    [
        None,  # not JSON
        "<html>",
        _order(supplier_id="S001"),
        _order(
            lines=[{"product_id": "P003", "ordered_qty": 96, "received_qty": 0, "open_qty": 96}]
        ),
        _order(
            lines=[{"product_id": "P004", "ordered_qty": 108, "received_qty": 0, "open_qty": 108}]
        ),
        _order(status="confirmed"),
        _order(approval={**_order()["approval"], "proposal_id": str(uuid.uuid4())}),
        _order(purchase_order_id="1001"),
    ],
    ids=["no body", "html", "supplier", "quantity", "product", "status", "proposal", "order id"],
)
def test_an_unreadable_or_mismatching_success_is_uncertain(body) -> None:
    outcome = classify(SendResult(status=201, body=body), PROPOSAL)
    assert (outcome.status, outcome.outcome) == ("uncertain", "uncertain")
    assert outcome.purchase_order_id is None
    assert "couldn't be read" in outcome.detail


@pytest.mark.parametrize(
    ("status", "body", "code", "reason"),
    [
        (
            409,
            _error("IDEMPOTENCY_CONFLICT"),
            "IDEMPOTENCY_CONFLICT",
            "the ERP already used this proposal's key for a different order",
        ),
        (
            422,
            _error("VALIDATION_ERROR", "supplier_id: no supplier S009"),
            "VALIDATION_ERROR",
            "the ERP refused the order: supplier_id: no supplier S009",
        ),
        (401, _error("UNAUTHORIZED"), "UNAUTHORIZED", "the Brain's ERP credential was refused"),
        (403, _error("FORBIDDEN"), "FORBIDDEN", "the Brain's ERP credential was refused"),
        (404, None, "HTTP_404", "the ERP refused the request (HTTP 404)"),
    ],
)
def test_a_clear_refusal_fails(status, body, code, reason) -> None:
    outcome = classify(SendResult(status=status, body=body), PROPOSAL)
    assert (outcome.status, outcome.outcome) == ("failed", "failed")
    assert (outcome.failure_code, outcome.failure_reason) == (code, reason)
    assert outcome.http_status == status


@pytest.mark.parametrize(
    "result",
    [
        SendResult(status=500, body=_error("INTERNAL_ERROR")),
        SendResult(status=503, body=None),
        SendResult(status=429, body=None),
        SendResult(error="timeout"),
        SendResult(error="connection"),
    ],
    ids=["500", "503", "429", "timeout", "connection"],
)
def test_an_unclear_answer_is_uncertain(result) -> None:
    outcome = classify(result, PROPOSAL)
    assert (outcome.status, outcome.outcome) == ("uncertain", "uncertain")
    assert outcome.detail == "the ERP didn't confirm the draft"


def test_a_missing_credential_file_sends_nothing_and_stays_uncertain() -> None:
    outcome = classify(SendResult(error="not_sent"), PROPOSAL)
    assert (outcome.status, outcome.outcome) == ("uncertain", "not_sent")
    assert outcome.detail == "the Brain's ERP credential file is missing"
    assert outcome.http_status is None


def test_no_reason_carries_the_token() -> None:
    results = [
        SendResult(status=401, body=_error("UNAUTHORIZED", f"Bearer {TOKEN} rejected")),
        SendResult(status=422, body=_error("VALIDATION_ERROR", f"Bearer {TOKEN}")),
        SendResult(error="timeout"),
    ]
    for result in results:
        outcome = classify(result, PROPOSAL)
        for text in (outcome.detail, outcome.failure_reason or ""):
            assert TOKEN not in text and "Bearer" not in text
