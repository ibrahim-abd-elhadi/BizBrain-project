import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base

STATUSES = ("awaiting_approval", "uncertain", "draft_created", "failed", "rejected")
LIVE = ("awaiting_approval", "uncertain")
FINAL = ("draft_created", "failed", "rejected")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


class Proposal(Base):
    """One intended create_purchase_order action (feature 004 data-model.md; README 4.5).

    The arguments, their canonical text and fingerprint never change, and the approval is written
    once: triggers in migration 0002 enforce it (FR-005). The id is also the Idempotency-Key."""

    __tablename__ = "proposal"
    __table_args__ = (
        CheckConstraint("action = 'create_purchase_order'", name="ck_proposal_action"),
        CheckConstraint("origin IN ('recommendation','assistant')", name="ck_proposal_origin"),
        CheckConstraint(
            "(origin = 'recommendation') = (recommendation_id IS NOT NULL)",
            name="ck_proposal_origin_recommendation",
        ),
        CheckConstraint("supplier_id ~ '^S[0-9]{3,}$'", name="ck_proposal_supplier"),
        CheckConstraint("arguments_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposal_sha256"),
        CheckConstraint(f"status IN {_in(STATUSES)}", name="ck_proposal_status"),
        CheckConstraint(
            "((approved_by IS NULL) = (approved_at IS NULL))"
            " AND ((approved_at IS NULL) = (request_body IS NULL))",
            name="ck_proposal_approval_trio",
        ),
        CheckConstraint(
            "(status IN ('awaiting_approval','rejected')) = (approved_at IS NULL)",
            name="ck_proposal_approval_by_status",
        ),
        CheckConstraint(
            "approved_by IS NULL OR char_length(approved_by) BETWEEN 1 AND 128",
            name="ck_proposal_approved_by",
        ),
        CheckConstraint(
            "(status = 'draft_created') = (purchase_order_id IS NOT NULL)",
            name="ck_proposal_order",
        ),
        CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)", name="ck_proposal_failure"
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_reason IS NOT NULL", name="ck_proposal_failure_reason"
        ),
        CheckConstraint(
            f"(status IN {_in(FINAL)}) = (closed_at IS NOT NULL)", name="ck_proposal_closed"
        ),
        Index("ix_proposal_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_result.id"), nullable=True
    )
    supplier_id: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    arguments_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    arguments_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
