"""Every change to stock goes through here, under a row lock (research R-23).

The caller owns the transaction: lock first, then change, so concurrent requests can't interleave.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.clock import now_utc
from erp.errors import ErpError
from erp.models import Stock


class StockBelowZero(Exception):
    """The change would leave a product with negative stock (FR-023)."""

    def __init__(self, product_id: str, on_hand: int, net_delta: int) -> None:
        super().__init__(
            f"Product {product_id} has {on_hand} in stock; a change of {net_delta} would go below 0"
        )
        self.product_id = product_id
        self.on_hand = on_hand
        self.net_delta = net_delta


def lock_stock(session: Session, product_id: str) -> Stock:
    row = session.scalar(select(Stock).where(Stock.product_id == product_id).with_for_update())
    if row is None:
        raise ErpError(404, "NOT_FOUND", f"Product {product_id} not found")
    return row


def set_on_hand(session: Session, product_id: str, value: int) -> Stock:
    if value < 0:
        raise ErpError(422, "VALIDATION_ERROR", "Stock must be a whole number of 0 or more")
    row = lock_stock(session, product_id)
    row.on_hand = value
    row.updated_at = now_utc()
    session.flush()
    return row


def apply_net_change(session: Session, product_id: str, net_delta: int) -> int:
    """Net units sold go out of stock: on_hand = on_hand - net_delta. Refuses to go below 0."""
    row = lock_stock(session, product_id)
    new_value = row.on_hand - net_delta
    if new_value < 0:
        raise StockBelowZero(product_id, row.on_hand, net_delta)
    row.on_hand = new_value
    row.updated_at = now_utc()
    session.flush()
    return new_value


def add_quantity(session: Session, product_id: str, quantity: int) -> int:
    row = lock_stock(session, product_id)
    row.on_hand += quantity
    row.updated_at = now_utc()
    session.flush()
    return row.on_hand
