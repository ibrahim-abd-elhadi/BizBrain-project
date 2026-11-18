import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ProposalLiveProduct(Base):
    """One row per product that has a live (awaiting approval or uncertain) proposal: the primary
    key allows one per product (D-30, FR-023). Rows are added by a trigger when lines are inserted
    and removed by a trigger when the proposal's status becomes final (migration 0002)."""

    __tablename__ = "proposal_live_product"

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposal.id"), nullable=False
    )
