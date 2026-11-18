import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class Explanation(Base):
    """A kept, model-phrased Why? for one recommendation and language (feature 005 FR-014a).

    Inserted once after passing the grounding check; brain-api has no UPDATE or DELETE on it, so
    it never changes. Template explanations are never stored."""

    __tablename__ = "explanation"
    __table_args__ = (
        CheckConstraint("language IN ('en','ar')", name="ck_explanation_language"),
        CheckConstraint("char_length(text) BETWEEN 1 AND 2000", name="ck_explanation_text_len"),
    )

    risk_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_result.id"), primary_key=True
    )
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
