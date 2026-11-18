"""brain-api: read-only endpoints for the Brain screens (feature 003; research R-17).

`create_app()` loads the ERP's public key first and refuses to start without it. The module's
`app` (what uvicorn serves, `brain.api.app:app`) is built on first access, so importing this
module in tests needs no key file. No OpenAPI or docs routes are served; no endpoint writes or
runs a job (D-38).
"""

from functools import lru_cache
from typing import Any

from fastapi import FastAPI

from brain.api import forecasts, proposals, risk
from brain.api.auth import load_public_key
from brain.api.errors import register_error_handlers
from brain.config import get_settings


def create_app() -> FastAPI:
    public_key = load_public_key(get_settings().erp_jwt_public_key_file)
    app = FastAPI(
        title="BizBrain Brain API",
        version="1.0.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.public_key = public_key
    register_error_handlers(app)
    app.include_router(risk.router)
    app.include_router(forecasts.router)
    app.include_router(proposals.router)
    return app


@lru_cache
def _served_app() -> FastAPI:
    return create_app()


def __getattr__(name: str) -> Any:
    if name == "app":
        return _served_app()
    raise AttributeError(name)
