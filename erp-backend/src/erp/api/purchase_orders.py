from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select

from erp.api.deps import require_manager
from erp.db import SessionDep
from erp.errors import ErpError
from erp.models import PurchaseOrder
from erp.schemas.purchase_orders import PurchaseOrder as PurchaseOrderOut
from erp.services import purchase_orders as po_service

# No create, edit or delete: drafts arrive from the Brain (feature 002), and the manager can only
# confirm them (FR-017, FR-022).
router = APIRouter(
    prefix="/purchase-orders", tags=["purchase-orders"], dependencies=[Depends(require_manager)]
)


@router.get("", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    session: SessionDep, status: Literal["draft", "confirmed"] | None = None
) -> list[PurchaseOrder]:
    query = select(PurchaseOrder).order_by(
        PurchaseOrder.created_at.desc(), PurchaseOrder.po_id.desc()
    )
    if status is not None:
        query = query.where(PurchaseOrder.status == status)
    return list(session.scalars(query))


@router.get("/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(po_id: int, session: SessionDep) -> PurchaseOrder:
    order = session.get(PurchaseOrder, po_id)
    if order is None:
        raise ErpError(404, "NOT_FOUND", f"Purchase order {po_id} not found")
    return order


@router.post("/{po_id}/confirm", response_model=PurchaseOrderOut)
def confirm_purchase_order(po_id: int, session: SessionDep) -> PurchaseOrder:
    return po_service.confirm(session, po_id)
