"""The Canonical error envelope for the cases no story reaches easily (FR-006, research R-05, R-06).

Written before the implementation.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from erp.canonical.errors import register_canonical_error_handlers

from canonical_support import assert_error


def _app() -> TestClient:
    app = FastAPI()
    register_canonical_error_handlers(app)

    @app.get("/db-down")
    def db_down() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret-detail")

    @app.get("/only-get")
    def only_get() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_database_unreachable_is_dependency_unavailable() -> None:
    assert_error(_app().get("/db-down"), 503, "DEPENDENCY_UNAVAILABLE")


def test_unexpected_errors_are_internal_and_leak_nothing() -> None:
    response = _app().get("/boom")
    assert_error(response, 500, "INTERNAL_ERROR")
    assert "secret-detail" not in response.text


def test_a_wrong_method_is_not_found_with_http_405() -> None:
    assert_error(_app().post("/only-get"), 405, "NOT_FOUND")


def test_an_unknown_path_is_not_found() -> None:
    assert_error(_app().get("/nowhere"), 404, "NOT_FOUND")


def test_trace_id_comes_from_a_valid_traceparent() -> None:
    client = _app()
    header = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
    error = assert_error(client.get("/nowhere", headers=header), 404, "NOT_FOUND")
    assert error["trace_id"] == "0af7651916cd43dd8448eb211c80319c"

    malformed = {"traceparent": "01-XYZ"}
    error = assert_error(client.get("/nowhere", headers=malformed), 404, "NOT_FOUND")
    assert len(error["trace_id"]) == 32 and error["trace_id"] != "0af7651916cd43dd8448eb211c80319c"
