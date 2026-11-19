"""The running app and the approved OpenAPI contract describe the same operations."""

from pathlib import Path

import yaml

from erp.main import app

CONTRACT = Path(__file__).resolve().parents[3] / "contracts/erp/erp-api.openapi.yaml"
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def operations(paths: dict) -> set[tuple[str, str]]:
    return {
        (path, method) for path, item in paths.items() for method in item if method in HTTP_METHODS
    }


def test_the_app_serves_exactly_the_contract_operations() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    prefix = contract["servers"][0]["url"]
    assert prefix == "/api/v1/erp"
    expected = {(prefix + path, method) for path, method in operations(contract["paths"])}

    served = {
        (path, method)
        for path, method in operations(app.openapi()["paths"])
        if path.startswith(prefix)
    }
    assert served == expected, (
        f"only in contract: {sorted(expected - served)}; only in app: {sorted(served - expected)}"
    )


def test_every_app_route_is_under_the_erp_prefix() -> None:
    paths = app.openapi()["paths"]
    assert all(path.startswith("/api/v1/erp/") for path in paths), sorted(paths)


def test_there_are_no_canonical_paths_and_no_delete_operations() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    app_paths = app.openapi()["paths"]
    for paths in (contract["paths"], app_paths):
        assert not any("/api/v1/canonical" in path for path in paths)
        assert not any("delete" in item for item in paths.values())
