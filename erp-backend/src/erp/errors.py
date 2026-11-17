"""One error shape for the whole API: {"detail": "...", "code": "..."}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErpError(Exception):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def _body(detail: str, code: str) -> dict[str, str]:
    return {"detail": detail, "code": code}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErpError)
    async def _erp_error(_: Request, exc: ErpError) -> JSONResponse:
        return JSONResponse(_body(exc.detail, exc.code), status_code=exc.status_code)

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
