import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ProposalAttempt(Base):
    """One send of an approved proposal to the ERP: the proposal's own history shown on its
    screen, not an audit log (README Section 7). Finished once (trigger, migration 0002)."""

    __tablename__ = "proposal_attempt"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('draft_created','uncertain','failed','not_sent')",
            name="ck_proposal_attempt_outcome",
        ),
        CheckConstraint(
            "(finished_at IS NULL) = (outcome IS NULL)", name="ck_proposal_attempt_finished"
        ),
        CheckConstraint("attempt_no >= 1", name="ck_proposal_attempt_no"),
        UniqueConstraint("proposal_id", "attempt_no", name="uq_proposal_attempt_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposal.id"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    erp_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
