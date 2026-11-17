"""Helpers for the Canonical API tests: JSON Schema validation against the feature 002 contract,
and checks of the error envelope (research R-05, R-15)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CANON = "/api/v1/canonical"
CONTRACTS = Path(__file__).resolve().parents[2] / "specs/002-canonical-api/contracts"
SCHEMAS = CONTRACTS / "schemas"
_BASE_URI = "https://contracts.bizbrain.invalid/schemas/"


@lru_cache
def _registry() -> Registry:
    registry: Registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents, default_specification=DRAFT202012)
        registry = registry.with_resource(
            _BASE_URI + path.relative_to(SCHEMAS).as_posix(), resource
        )
    return registry


def validator(schema_name: str) -> Draft202012Validator:
    """schema_name is relative to contracts/schemas, e.g. "canonical/product.schema.json"."""
    return Draft202012Validator(
        {"$ref": _BASE_URI + schema_name}, registry=_registry(), format_checker=FormatChecker()
    )


def validate(schema_name: str, document: Any) -> None:
    """Raises jsonschema.ValidationError if the document does not match the contract schema."""
    validator(schema_name).validate(document)


def is_valid(schema_name: str, document: Any) -> bool:
    return validator(schema_name).is_valid(document)


def assert_error(
    response: httpx.Response, status: int, code: str, field: str | None = None
) -> dict[str, Any]:
    """The response is the Canonical error envelope with this status and code (and field)."""
    assert response.status_code == status, (response.status_code, response.text)
    body = response.json()
    validate("common/error.schema.json", body)
    error = body["error"]
    assert error["code"] == code, error
    if field is not None:
        fields = [detail.get("field") for detail in error["details"]]
        assert field in fields, (field, fields)
    return error
