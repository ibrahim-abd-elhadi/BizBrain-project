"""The Canonical contract files agree with themselves and with the mounted sub-application
(research R-15, SC-006). Written before the implementation."""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from canonical_support import CANON, CONTRACTS, is_valid, validate

OPENAPI = CONTRACTS / "openapi/canonical.openapi.yaml"
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
SIX = {
    (f"{CANON}/sales", "get"),
    (f"{CANON}/products/{{product_id}}", "get"),
    (f"{CANON}/inventory/{{product_id}}", "get"),
    (f"{CANON}/suppliers/{{supplier_id}}", "get"),
    (f"{CANON}/purchase-orders", "get"),
    (f"{CANON}/purchase-orders", "post"),
}


def operations(paths: dict, prefix: str = "") -> set[tuple[str, str]]:
    return {
        (prefix + path, method)
        for path, item in paths.items()
        for method in item
        if method in HTTP_METHODS
    }


def _fixtures(kind: str) -> list[Path]:
    return sorted((CONTRACTS / "fixtures" / kind).rglob("*.json"))


@pytest.mark.parametrize("path", _fixtures("valid"), ids=lambda p: p.stem)
def test_valid_fixtures_pass_their_schema(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    schema = fixture["$schema_ref"].removeprefix("schemas/")
    assert is_valid(schema, fixture["document"]), path


@pytest.mark.parametrize("path", _fixtures("invalid"), ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_invalid_fixtures_fail_their_schema(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    schema = fixture["$schema_ref"].removeprefix("schemas/")
    assert not is_valid(schema, fixture["document"]), path


def test_the_contract_has_exactly_the_six_readme_operations() -> None:
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    assert operations(contract["paths"]) == SIX


def test_the_app_serves_exactly_the_contract_operations() -> None:
    from erp.canonical.app import canonical_app

    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    # In-process: the app serves no OpenAPI or docs route (research R-01).
    served = operations(canonical_app.openapi()["paths"], prefix=CANON)
    expected = operations(contract["paths"])
    assert served == expected, (
        f"only in contract: {sorted(expected - served)}; only in app: {sorted(served - expected)}"
    )


def _success_schema(contract: dict, path: str, method: str, status: str) -> str:
    """The schema file the contract names for a success response, relative to schemas/."""
    ref = contract["paths"][path][method]["responses"][status]["content"]["application/json"][
        "schema"
    ]["$ref"]
    return ref.removeprefix("../schemas/")


def test_every_operation_answers_in_its_contract_schema(
    client: TestClient, at_cairo, seed, service_token
) -> None:
    """SC-006: one live call per operation, each body checked against the contract's schema."""
    import uuid

    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    body_fixture = json.loads(
        (
            CONTRACTS / "fixtures/valid/canonical/create_draft_po_request/from_proposal.json"
        ).read_text(encoding="utf-8")
    )["document"]
    key = str(uuid.uuid4())
    body_fixture["approval"]["proposal_id"] = key

    with at_cairo("2026-11-18T13:05"):
        seed()
        headers = {"Authorization": f"Bearer {service_token()}"}
        created = client.post(
            f"{CANON}/purchase-orders",
            json=body_fixture,
            headers={**headers, "Idempotency-Key": key},
        )
        replay = client.post(
            f"{CANON}/purchase-orders",
            json=body_fixture,
            headers={**headers, "Idempotency-Key": key},
        )
        calls = [
            (
                "/sales",
                "get",
                "200",
                client.get(f"{CANON}/sales?from=2026-08-20&to=2026-11-18", headers=headers),
            ),
            (
                "/products/{product_id}",
                "get",
                "200",
                client.get(f"{CANON}/products/P003", headers=headers),
            ),
            (
                "/inventory/{product_id}",
                "get",
                "200",
                client.get(f"{CANON}/inventory/P003", headers=headers),
            ),
            (
                "/suppliers/{supplier_id}",
                "get",
                "200",
                client.get(f"{CANON}/suppliers/S004", headers=headers),
            ),
            (
                "/purchase-orders",
                "get",
                "200",
                client.get(f"{CANON}/purchase-orders?status=open&product_id=P003", headers=headers),
            ),
            ("/purchase-orders", "post", "201", created),
            ("/purchase-orders", "post", "200", replay),
        ]

    for path, method, status, response in calls:
        assert str(response.status_code) == status, (path, response.text)
        schema = _success_schema(contract, CANON + path, method, status)
        validate(schema, response.json())
    assert calls[4][3].json()["items"], "the open list should hold the new draft"
