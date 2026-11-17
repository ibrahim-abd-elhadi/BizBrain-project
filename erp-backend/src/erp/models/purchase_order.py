from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp.clock import now_utc
from erp.models.base import Base


class PurchaseOrder(Base):
    """The header of an order (FR-016 to FR-018, FR-024). Drafts come from the Brain later."""

    __tablename__ = "purchase_order"
    __table_args__ = (
        CheckConstraint("status IN ('draft','confirmed')", name="ck_purchase_order_status"),
        CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_purchase_order_confirmed_at",
        ),
    )

    po_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="draft", server_default="draft"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order",
        order_by="PurchaseOrderLine.product_id",
        lazy="selectin",
        cascade="save-update",
    )


class PurchaseOrderLine(Base):
    """The quantity ordered for one product (FR-024)."""

    __tablename__ = "purchase_order_line"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_purchase_order_line_quantity"),)

    po_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_order.po_id"), primary_key=True
    )
    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("product.product_id"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
