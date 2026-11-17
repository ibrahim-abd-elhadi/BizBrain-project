from fastapi import APIRouter, Depends
from sqlalchemy import select

from erp.api.deps import require_manager
from erp.db import SessionDep
from erp.models import Product, Stock
from erp.schemas.catalog import StockRow, StockSet
from erp.services import stock as stock_service

# Stock for the pharmacy's one location: no location, branch or organization anywhere (FR-005).
router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=[Depends(require_manager)])


def _row(stock: Stock, name: str) -> StockRow:
    return StockRow(
        product_id=stock.product_id, name=name, on_hand=stock.on_hand, updated_at=stock.updated_at
    )


@router.get("", response_model=list[StockRow])
def list_inventory(session: SessionDep) -> list[StockRow]:
    rows = session.execute(
        select(Stock, Product.name)
        .join(Product, Product.product_id == Stock.product_id)
        .order_by(Stock.product_id)
    )
    return [_row(stock, name) for stock, name in rows]


@router.put("/{product_id}", response_model=StockRow)
def set_stock(product_id: str, body: StockSet, session: SessionDep) -> StockRow:
    stock = stock_service.set_on_hand(session, product_id, body.on_hand)
    name = session.scalar(select(Product.name).where(Product.product_id == product_id))
    return _row(stock, name or "")
