"""Who may call the Canonical API (FR-006 to FR-009, SC-005; US1 scenarios 7 and 8, US4 8 and 9).

Every operation is listed once in OPERATIONS; each story adds its own. Written before the
implementation.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import time_machine
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from canonical_support import CANON, assert_error

READ = "canonical:read"
DRAFT = "canonical:po:create_draft"

# (method, path with a valid query, the scope it needs)
OPERATIONS: list[tuple[str, str, str]] = [
    ("GET", "/sales?from=2026-08-20&to=2026-11-18", READ),
    ("GET", "/products/P001", READ),
    ("GET", "/inventory/P001", READ),
    ("GET", "/suppliers/S001", READ),
    ("GET", "/purchase-orders?status=open", READ),
    ("POST", "/purchase-orders", DRAFT),
]

TokenFactory = Callable[..., str]


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]):
    return client.request(method, CANON + path, headers=headers)


def _foreign_token() -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "bizbrain-erp",
        "aud": "bizbrain-canonical",
        "sub": "brain",
        "scope": f"{READ} {DRAFT}",
        "iat": now,
        "exp": now + timedelta(days=1),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, Ed25519PrivateKey.generate(), algorithm="EdDSA")


@pytest.mark.parametrize(("method", "path", "scope"), OPERATIONS)
def test_calls_without_a_valid_service_token_are_unauthorized(
    client: TestClient,
    auth_headers: dict[str, str],
    service_token: TokenFactory,
    method: str,
    path: str,
    scope: str,
) -> None:
    refused = {
        "no header": {},
        "not a JWT": {"Authorization": "Bearer not-a-token"},
        "another key": {"Authorization": f"Bearer {_foreign_token()}"},
        "manager token": auth_headers,
        "basic scheme": {"Authorization": "Basic YnJhaW46YnJhaW4="},
    }
    for name, headers in refused.items():
        response = _call(client, method, path, headers)
        error = assert_error(response, 401, "UNAUTHORIZED")
        assert "items" not in response.json(), name
        assert response.headers.get("www-authenticate") == "Bearer", name
        assert "Bearer" not in error["message"]

    issued = datetime.now(UTC)
    with time_machine.travel(issued, tick=False):
        expiring = service_token(days=1)
    with time_machine.travel(issued + timedelta(days=2), tick=False):
        assert_error(
            _call(client, method, path, {"Authorization": f"Bearer {expiring}"}),
            401,
            "UNAUTHORIZED",
        )


@pytest.mark.parametrize(("method", "path", "scope"), OPERATIONS)
def test_a_token_without_the_scope_is_forbidden(
    client: TestClient, service_token: TokenFactory, method: str, path: str, scope: str
) -> None:
    other = DRAFT if scope == READ else READ
    headers = {"Authorization": f"Bearer {service_token(scopes=(other,))}"}
    assert_error(_call(client, method, path, headers), 403, "FORBIDDEN")


@pytest.mark.parametrize(("method", "path", "scope"), OPERATIONS)
def test_the_right_scope_gets_past_auth(
    client: TestClient, service_token: TokenFactory, method: str, path: str, scope: str
) -> None:
    headers = {"Authorization": f"Bearer {service_token(scopes=(scope,))}"}
    assert _call(client, method, path, headers).status_code not in (401, 403)


def test_the_service_token_is_refused_on_the_erp_screens(
    client: TestClient, canon_headers: dict[str, str], manager: str
) -> None:
    response = client.get("/api/v1/erp/products", headers=canon_headers)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"  # feature 001's own format (FR-009)


def test_trace_id_follows_traceparent(client: TestClient) -> None:
    header = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
    error = assert_error(client.get(f"{CANON}/sales", headers=header), 401, "UNAUTHORIZED")
    assert error["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    error = assert_error(client.get(f"{CANON}/sales"), 401, "UNAUTHORIZED")
    assert len(error["trace_id"]) == 32


def test_unknown_canonical_paths_are_not_found(
    client: TestClient, canon_headers: dict[str, str]
) -> None:
    assert_error(client.get(f"{CANON}/locations", headers=canon_headers), 404, "NOT_FOUND")


def test_refused_post_requests_create_nothing_and_auth_runs_before_the_body(
    client: TestClient, db, auth_headers: dict[str, str], service_token: TokenFactory
) -> None:
    from sqlalchemy import func, select

    from erp.models import IdempotencyRecord, PurchaseOrder

    key = str(uuid.uuid4())
    read_only = {"Authorization": f"Bearer {service_token(scopes=(READ,))}"}
    bodies = ('{"supplier_id":', '{"supplier_id": "S001", "lines": [], "approval": {}}')
    for headers, status, code in (
        ({}, 401, "UNAUTHORIZED"),
        (auth_headers, 401, "UNAUTHORIZED"),
        (read_only, 403, "FORBIDDEN"),
    ):
        for body in bodies:
            response = client.post(
                f"{CANON}/purchase-orders",
                content=body,
                headers={**headers, "Idempotency-Key": key, "Content-Type": "application/json"},
            )
            assert_error(response, status, code)  # never 422: auth runs before the body is read
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 0
    assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
