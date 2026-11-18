"""One error shape, the ERP's: {"detail": "...", "code": "..."} (copied from erp/errors.py), so the
React app's error handling and "back to sign-in" work for Brain calls too."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class BrainError(Exception):
    def __init__(
        self, status_code: int, code: str, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.headers = headers


def _body(detail: str, code: str) -> dict[str, str]:
    return {"detail": detail, "code": code}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BrainError)
    async def _brain_error(_: Request, exc: BrainError) -> JSONResponse:
        return JSONResponse(
            _body(exc.detail, exc.code), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path"))
        message = first.get("msg", "Invalid request")
        detail = f"{where}: {message}" if where else message
        return JSONResponse(_body(detail, "VALIDATION_ERROR"), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:
            return JSONResponse(
                _body("Method not allowed", "METHOD_NOT_ALLOWED"),
                status_code=405,
                headers=getattr(exc, "headers", None),
            )
        if exc.status_code == 404:
            return JSONResponse(_body("Not found", "NOT_FOUND"), status_code=404)
        return JSONResponse(_body(str(exc.detail), "HTTP_ERROR"), status_code=exc.status_code)
