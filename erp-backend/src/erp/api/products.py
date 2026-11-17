from fastapi import APIRouter, Depends
from sqlalchemy import select

from erp.api.deps import require_manager
from erp.db import SessionDep
from erp.errors import ErpError
from erp.models import Product, Stock, Supplier
from erp.schemas.catalog import Product as ProductOut
from erp.schemas.catalog import ProductCreate, ProductUpdate

# No DELETE: nothing in the ERP is ever deleted (FR-022).
router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(require_manager)])


def _check_rules(session: SessionDep, supplier_id: str, pack_multiple: int, max_order_qty: int):
    if session.get(Supplier, supplier_id) is None:
        raise ErpError(422, "SUPPLIER_NOT_FOUND", f"Supplier {supplier_id} does not exist")
    if max_order_qty < pack_multiple:
        raise ErpError(
            422,
            "MAX_BELOW_PACK",
            f"Maximum order quantity ({max_order_qty}) cannot be below the pack multiple "
            f"({pack_multiple})",
        )


def _get(session: SessionDep, product_id: str) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise ErpError(404, "NOT_FOUND", f"Product {product_id} not found")
    return product


@router.get("", response_model=list[ProductOut])
def list_products(session: SessionDep) -> list[Product]:
    return list(session.scalars(select(Product).order_by(Product.product_id)))


@router.post("", response_model=ProductOut, status_code=201)
def create_product(body: ProductCreate, session: SessionDep) -> Product:
    _check_rules(session, body.preferred_supplier_id, body.pack_multiple, body.max_order_qty)
    product = Product(
        name=body.name,
        preferred_supplier_id=body.preferred_supplier_id,
        pack_multiple=body.pack_multiple,
        max_order_qty=body.max_order_qty,
    )
    session.add(product)
    session.flush()  # the database assigns product_id
    session.add(Stock(product_id=product.product_id, on_hand=body.starting_stock))
    session.flush()
    return product


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: str, session: SessionDep) -> Product:
    return _get(session, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: str, body: ProductUpdate, session: SessionDep) -> Product:
    product = _get(session, product_id)
    changes = body.model_dump(exclude_unset=True)
    _check_rules(
        session,
        changes.get("preferred_supplier_id", product.preferred_supplier_id),
        changes.get("pack_multiple", product.pack_multiple),
        changes.get("max_order_qty", product.max_order_qty),
    )
    for field, value in changes.items():
        setattr(product, field, value)
    session.flush()
    return product
