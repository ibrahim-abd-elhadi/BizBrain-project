"""The main plan's error envelope for the Canonical API (FR-006, research R-05, R-06):

    {"error": {"code", "message", "details": [{"field", "issue"}], "trace_id"}}

The ERP's own endpoints keep feature 001's {"detail", "code"} format (erp.errors).
"""

import logging
import re
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("erp.canonical")

_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")
_LOCATION_PREFIXES = {"query", "path", "body", "header", "cookie"}


class CanonicalError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Iterable[dict[str, str]] = (),
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = list(details)
        self.headers = headers


def validation_error(field: str, issue: str) -> CanonicalError:
    return CanonicalError(
        422, "VALIDATION_ERROR", f"{field}: {issue}", [{"field": field, "issue": issue}]
    )


def trace_id(request: Request) -> str:
    """The trace ID of a valid W3C traceparent header, else a new one (a bad header is ignored)."""
    match = _TRACEPARENT.match(request.headers.get("traceparent", ""))
    return match.group(1) if match else uuid.uuid4().hex


def field_name(location: Sequence[Any]) -> str:
    """("body", "lines", 0, "quantity") -> "lines[0].quantity"; ("query", "from") -> "from"."""
    parts = list(location)
    if parts and parts[0] in _LOCATION_PREFIXES:
        parts = parts[1:]
    name = ""
    for part in parts:
        if isinstance(part, int):
            name += f"[{part}]"
        else:
            name += f".{part}" if name else str(part)
    return name or "request"


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: Iterable[dict[str, str]] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": list(details),
            "trace_id": trace_id(request),
        }
    }
    return JSONResponse(body, status_code=status, headers=headers)


def register_canonical_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CanonicalError)
    async def _canonical(request: Request, exc: CanonicalError) -> JSONResponse:
        return error_response(request, exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": field_name(error.get("loc", ())), "issue": str(error.get("msg", "invalid"))}
            for error in exc.errors()
        ]
        message = f"{details[0]['field']}: {details[0]['issue']}" if details else "Invalid request"
        return error_response(request, 422, "VALIDATION_ERROR", message, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = getattr(exc, "headers", None)
        if exc.status_code == 405:
            # The main plan's code list has no "method not allowed"; the status still says 405.
            return error_response(request, 405, "NOT_FOUND", "Method not allowed", headers=headers)
        if exc.status_code == 404:
            return error_response(request, 404, "NOT_FOUND", "Not found")
        if exc.status_code == 401:
            return error_response(request, 401, "UNAUTHORIZED", "Unauthorized", headers=headers)
        if exc.status_code == 403:
            return error_response(request, 403, "FORBIDDEN", "Forbidden")
        return error_response(request, exc.status_code, "INTERNAL_ERROR", "Request failed")

    @app.exception_handler(OperationalError)
    async def _database(request: Request, exc: OperationalError) -> JSONResponse:
        logger.warning("database unavailable: %s", type(exc.orig or exc).__name__)
        return error_response(
            request, 503, "DEPENDENCY_UNAVAILABLE", "The ERP database is unavailable"
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unexpected Canonical API error: %s", type(exc).__name__)
        return error_response(request, 500, "INTERNAL_ERROR", "Internal error")
