"""The Canonical API application, mounted by erp.main at /api/v1/canonical (research R-01).

It serves no OpenAPI, Swagger or ReDoc route, so the only paths under /api/v1/canonical are the
six operations of README Section 3, all behind the service token (constitution Principle II,
FR-001, FR-007). The contract test reads canonical_app.openapi() in-process.
"""

from fastapi import FastAPI

from erp.canonical import catalog, purchase_orders, sales
from erp.canonical.errors import register_canonical_error_handlers

canonical_app = FastAPI(
    title="BizBrain Canonical API",
    version="1.0",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)
register_canonical_error_handlers(canonical_app)
canonical_app.include_router(sales.router)
canonical_app.include_router(catalog.router)
canonical_app.include_router(purchase_orders.router)
