import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ProposalLine(Base):
    """A proposal's line, written once with the proposal. Inserting one takes the product's
    live-proposal lock (trigger proposal_line_lock, migration 0002)."""

    __tablename__ = "proposal_line"
    __table_args__ = (
        CheckConstraint("product_id ~ '^P[0-9]{3,}$'", name="ck_proposal_line_product"),
        CheckConstraint("line_no BETWEEN 1 AND 50", name="ck_proposal_line_no"),
        CheckConstraint("quantity BETWEEN 1 AND 1000000", name="ck_proposal_line_quantity"),
        UniqueConstraint("proposal_id", "line_no", name="uq_proposal_line_no"),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposal.id"), primary_key=True
    )
    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
