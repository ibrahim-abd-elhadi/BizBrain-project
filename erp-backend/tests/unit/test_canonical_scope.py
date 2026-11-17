"""Scope guards for the Canonical API (FR-001, FR-002, FR-021; constitution Principles I and II).

No tenant, organization, branch or location field, none of the fields the ERP doesn't hold, and
exactly the six operations of README Section 3, with nothing else served under the prefix.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from canonical_support import CANON, SCHEMAS, assert_error

CANONICAL_SRC = Path(__file__).resolve().parents[2] / "src/erp/canonical"
BANNED = (
    "tenant",
    "organization",
    "branch",
    "location",
    "complete",
    "coverage",
    "sku",
    "reserved",
    "reorder_point",
    "note",
)
SIX = {
    ("/sales", "GET"),
    ("/products/{product_id}", "GET"),
    ("/inventory/{product_id}", "GET"),
    ("/suppliers/{supplier_id}", "GET"),
    ("/purchase-orders", "GET"),
    ("/purchase-orders", "POST"),
}


def _property_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                names |= set(value)
            names |= _property_names(value)
    elif isinstance(node, list):
        for value in node:
            names |= _property_names(value)
    return names


def _banned(name: str) -> bool:
    return any(word in name.lower() for word in BANNED)


def test_no_canonical_schema_defines_a_banned_field() -> None:
    for path in SCHEMAS.rglob("*.schema.json"):
        fields = _property_names(json.loads(path.read_text(encoding="utf-8")))
        assert not [f for f in fields if _banned(f)], path


def test_no_canonical_model_defines_a_banned_field() -> None:
    from pydantic import BaseModel

    from erp.canonical import schemas

    for value in vars(schemas).values():
        if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
            fields = set(value.model_fields) | {
                f.alias for f in value.model_fields.values() if f.alias
            }
            assert not [f for f in fields if _banned(f)], value.__name__


def test_the_canonical_code_uses_no_banned_field_name() -> None:
    pattern = re.compile(r"\b(tenant_id|organization_id|branch_id|location_id|inventory_scope)\b")
    for path in CANONICAL_SRC.glob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_the_mounted_app_serves_exactly_the_six_operations() -> None:
    from erp.canonical.app import canonical_app

    served: set[tuple[str, str]] = set()
    other_routes: list[object] = []

    def walk(routes: list) -> None:
        for route in routes:
            if hasattr(route, "original_router"):  # FastAPI wraps each included router
                walk(route.original_router.routes)
            elif isinstance(route, APIRoute):
                served.update((route.path, method) for method in route.methods)
            else:
                other_routes.append(route)

    walk(canonical_app.routes)
    assert served == SIX
    assert other_routes == [], other_routes  # no OpenAPI, Swagger or ReDoc route


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"])
def test_no_api_description_or_docs_page_is_served(client: TestClient, path: str) -> None:
    assert_error(client.get(CANON + path), 404, "NOT_FOUND")
