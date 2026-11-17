from fastapi import APIRouter, FastAPI

from erp.api import auth, inventory, products, suppliers
from erp.errors import register_error_handlers

# The ERP's own API. /api/v1/canonical/* belongs to feature 002 and is not mounted here.
api = APIRouter(prefix="/api/v1/erp")
api.include_router(auth.router)
api.include_router(suppliers.router)
api.include_router(products.router)
api.include_router(inventory.router)

app = FastAPI(title="BizBrain ERP")
register_error_handlers(app)
app.include_router(api)
