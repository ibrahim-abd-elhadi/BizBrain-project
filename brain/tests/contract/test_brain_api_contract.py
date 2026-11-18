"""The running brain-api and contracts/brain-api.openapi.yaml describe the same operations, and
the responses validate against the contract's schemas (research R-20). Written first."""

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "specs/003-brain-intelligence/contracts/brain-api.openapi.yaml"
)
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def operations(paths: dict) -> set[tuple[str, str]]:
    return {(p, m) for p, item in paths.items() for m in item if m in HTTP_METHODS}


def validate(schema_name: str, document) -> None:
    contract = _contract()
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": contract["components"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def validate_list(schema_name: str, documents: list) -> None:
    for document in documents:
        validate(schema_name, document)


def test_the_app_serves_exactly_the_contract_operations(api_client) -> None:
    contract = _contract()
    prefix = contract["servers"][0]["url"]
    assert prefix == "/api/v1/brain"
    expected = {(prefix + p, m) for p, m in operations(contract["paths"])}
    served = operations(api_client.app.openapi()["paths"])
    assert served == expected, f"contract only: {expected - served}; app only: {served - expected}"
    assert all(m == "get" for _, m in served)


def test_the_risk_list_matches_the_contract(first_night, api_client, manager) -> None:
    body = api_client.get("/api/v1/brain/risk", headers=manager).json()
    validate("RiskList", body)
    assert len(body["items"]) == 20


def test_an_empty_risk_list_matches_the_contract(api_client, manager) -> None:
    validate("RiskList", api_client.get("/api/v1/brain/risk", headers=manager).json())


def test_errors_match_the_contract(api_client) -> None:
    validate("Error", api_client.get("/api/v1/brain/risk").json())


# ---------------------------------------------------------------- part 2 (US5)


def test_the_forecast_endpoints_match_the_contract(first_night, api_client, manager) -> None:
    products = api_client.get("/api/v1/brain/forecasts", headers=manager).json()
    assert len(products) == 20
    validate_list("ForecastProduct", products)
    for product_id in ("P003", "P013", "P020"):
        body = api_client.get(f"/api/v1/brain/forecasts/{product_id}", headers=manager).json()
        validate("ProductForecast", body)


def test_forecast_errors_match_the_contract(first_night, api_client, manager) -> None:
    for path in ("/api/v1/brain/forecasts/P999", "/api/v1/brain/forecasts/p003"):
        validate("Error", api_client.get(path, headers=manager).json())
