"""Confirming a purchase order (FR-016, FR-017, FR-024), and creating the Brain's draft (feature
002, FR-027 to FR-029).

Confirming is the manager's approval. It treats the ordered quantities as received, so the demo
loop closes: the lines' quantities are added to stock.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.canonical.errors import validation_error
from erp.clock import now_utc
from erp.errors import ErpError
from erp.models import Product, PurchaseOrder, PurchaseOrderLine, Supplier
from erp.services import stock

if TYPE_CHECKING:
    from erp.canonical.schemas import CreateDraftPurchaseOrderRequest


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
    order.confirmed_at = order.updated_at = now_utc()
    for line in sorted(order.lines, key=lambda each: each.product_id):
        stock.add_quantity(session, line.product_id, line.quantity)
    session.flush()
    return order


def check_references(session: Session, request: "CreateDraftPurchaseOrderRequest") -> None:
    """The supplier and every product exist (feature 002 FR-027). Validation: it runs only for a
    key that isn't used yet, before anything is created (research R-10, step 4)."""
    if session.get(Supplier, request.supplier_id) is None:
        raise validation_error("supplier_id", f"unknown supplier {request.supplier_id}")
    for index, line in enumerate(request.lines):
        if session.get(Product, line.product_id) is None:
            raise validation_error(
                f"lines[{index}].product_id", f"unknown product {line.product_id}"
            )


def create_draft(session: Session, request: "CreateDraftPurchaseOrderRequest") -> PurchaseOrder:
    """A draft from the Brain, carrying the approval block as evidence (FR-029, FR-034). The ERP
    does not judge the approval, the supplier choice or the quantities. Stock doesn't change."""
    now = now_utc()
    approval = request.approval
    order = PurchaseOrder(
        status="draft",
        supplier_id=request.supplier_id,
        created_by="agent",
        approval_proposal_id=uuid.UUID(approval.proposal_id),
        approval_approved_by=approval.approved_by,
        approval_approved_at=datetime.fromisoformat(approval.approved_at),
        approval_arguments_sha256=approval.arguments_sha256,
        created_at=now,
        updated_at=now,
        lines=[
            PurchaseOrderLine(product_id=line.product_id, quantity=line.quantity)
            for line in request.lines
        ],
    )
    session.add(order)
    session.flush()
    return order
