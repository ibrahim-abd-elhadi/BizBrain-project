import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp.clock import now_utc
from erp.models.base import Base


class PurchaseOrder(Base):
    """The header of an order (FR-016 to FR-018, FR-024).

    Drafts are created by the Brain through the Canonical API (feature 002, `created_by` =
    `agent`, with the approval block), or by hand for testing (`human`). Every order has one
    supplier (feature 002 FR-026).
    """

    __tablename__ = "purchase_order"
    __table_args__ = (
        CheckConstraint("status IN ('draft','confirmed')", name="ck_purchase_order_status"),
        CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_purchase_order_confirmed_at",
        ),
        CheckConstraint("created_by IN ('human','agent')", name="ck_purchase_order_created_by"),
        CheckConstraint(
            "char_length(approval_approved_by) BETWEEN 1 AND 128",
            name="ck_purchase_order_approved_by_length",
        ),
        CheckConstraint(
            "approval_arguments_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_purchase_order_arguments_sha256",
        ),
        CheckConstraint(
            "(approval_proposal_id IS NULL AND approval_approved_by IS NULL"
            " AND approval_approved_at IS NULL AND approval_arguments_sha256 IS NULL)"
            " OR (approval_proposal_id IS NOT NULL AND approval_approved_by IS NOT NULL"
            " AND approval_approved_at IS NOT NULL AND approval_arguments_sha256 IS NOT NULL)",
            name="ck_purchase_order_approval_all_or_none",
        ),
        CheckConstraint(
            "(created_by = 'agent') = (approval_proposal_id IS NOT NULL)",
            name="ck_purchase_order_approval_matches_creator",
        ),
        UniqueConstraint("approval_proposal_id", name="uq_purchase_order_approval_proposal_id"),
    )

    po_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="draft", server_default="draft"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supplier_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("supplier.supplier_id", name="fk_purchase_order_supplier_id"),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        Text, nullable=False, default="human", server_default="human"
    )
    approval_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    approval_approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_arguments_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )

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
