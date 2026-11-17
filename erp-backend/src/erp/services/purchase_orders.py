"""Confirming a purchase order (FR-016, FR-017, FR-024).

Confirming is the manager's approval. It treats the ordered quantities as received, so the demo
loop closes: the lines' quantities are added to stock.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.clock import now_utc
from erp.errors import ErpError
from erp.models import PurchaseOrder
from erp.services import stock


def confirm(session: Session, po_id: int) -> PurchaseOrder:
    """Confirms a draft and adds its lines to stock, in the caller's one transaction.

    The order row is locked first, so two confirms at once can't both add stock. Confirming an
    order that is already confirmed returns it unchanged and adds nothing.
    """
    order = session.scalar(
        select(PurchaseOrder).where(PurchaseOrder.po_id == po_id).with_for_update()
    )
    if order is None:
        raise ErpError(404, "NOT_FOUND", f"Purchase order {po_id} not found")
    if order.status == "confirmed":
        return order

    order.status = "confirmed"
    order.confirmed_at = now_utc()
    for line in sorted(order.lines, key=lambda each: each.product_id):
        stock.add_quantity(session, line.product_id, line.quantity)
    session.flush()
    return order
