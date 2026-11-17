"""GET products/{id}, inventory/{id} and suppliers/{id} (US2, FR-018 to FR-022).

An ID in the wrong format is a VALIDATION_ERROR; an unknown one is NOT_FOUND.
"""

from typing import Annotated

from fastapi import APIRouter, Path

from erp.canonical.auth import ReadAccess
from erp.canonical.errors import CanonicalError
from erp.canonical.schemas import InventoryItem, Product, Supplier
from erp.db import SessionDep
from erp.ids import PRODUCT_ID_PATTERN, SUPPLIER_ID_PATTERN
from erp.models import Product as ProductRow
from erp.models import Stock
from erp.models import Supplier as SupplierRow

router = APIRouter(dependencies=[ReadAccess])

ProductIdPath = Annotated[str, Path(pattern=PRODUCT_ID_PATTERN)]
SupplierIdPath = Annotated[str, Path(pattern=SUPPLIER_ID_PATTERN)]


def _not_found(what: str, value: str) -> CanonicalError:
    return CanonicalError(404, "NOT_FOUND", f"{what} {value} not found")


@router.get("/products/{product_id}", response_model=Product)
def get_product(product_id: ProductIdPath, session: SessionDep) -> Product:
    row = session.get(ProductRow, product_id)
    if row is None:
        raise _not_found("Product", product_id)
    return Product(
        product_id=row.product_id,
        name=row.name,
        preferred_supplier_id=row.preferred_supplier_id,
        pack_multiple=row.pack_multiple,
        max_order_qty=row.max_order_qty,
        updated_at=row.updated_at,
    )


@router.get("/inventory/{product_id}", response_model=InventoryItem)
def get_inventory(product_id: ProductIdPath, session: SessionDep) -> InventoryItem:
    stock = session.get(Stock, product_id)
    if stock is None:
        raise _not_found("Product", product_id)
    return InventoryItem(
        product_id=stock.product_id,
        on_hand=stock.on_hand,
        available=stock.on_hand,
        updated_at=stock.updated_at,
    )


@router.get("/suppliers/{supplier_id}", response_model=Supplier)
def get_supplier(supplier_id: SupplierIdPath, session: SessionDep) -> Supplier:
    row = session.get(SupplierRow, supplier_id)
    if row is None:
        raise _not_found("Supplier", supplier_id)
    return Supplier(
        supplier_id=row.supplier_id,
        name=row.name,
        lead_time_days=row.lead_time_days,
        updated_at=row.updated_at,
    )
