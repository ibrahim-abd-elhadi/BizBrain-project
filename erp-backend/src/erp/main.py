from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from erp.api import auth, inventory, products, purchase_orders, sales, suppliers
from erp.canonical.app import canonical_app
from erp.db import get_sessionmaker
from erp.errors import register_error_handlers
from erp.services.day_close import close_past_days

# The ERP's own API, for the manager's screens. The Canonical API, for the Brain, is a separate
# application mounted below with its own error format and service-token auth (feature 002 R-01).
api = APIRouter(prefix="/api/v1/erp")
api.include_router(auth.router)
api.include_router(suppliers.router)
api.include_router(products.router)
api.include_router(inventory.router)
api.include_router(sales.router)
api.include_router(purchase_orders.router)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Days that ended while the ERP was down are closed on start-up (research R-14).
    with get_sessionmaker()() as session:
        close_past_days(session)
        session.commit()
    yield


app = FastAPI(title="BizBrain ERP", lifespan=lifespan)
register_error_handlers(app)
app.include_router(api)
app.mount("/api/v1/canonical", canonical_app)
