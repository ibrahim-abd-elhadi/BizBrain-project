from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class Briefing(Base):
    """The morning briefing of one end-of-day run (feature 005 data-model.md; README 4.6).

    Written once by the night's job; both texts exist only when it was written and grounded. The
    facts it was written from are kept with it. No model ID, prompt or timing is stored (no LLM
    usage log, README Section 7)."""

    __tablename__ = "briefing"
    __table_args__ = (
        CheckConstraint(
            "status IN ('written','offline','not_grounded')", name="ck_briefing_status"
        ),
        CheckConstraint("(status = 'written') = (text_en IS NOT NULL)", name="ck_briefing_written"),
        CheckConstraint("(text_en IS NULL) = (text_ar IS NULL)", name="ck_briefing_both_texts"),
        CheckConstraint(
            "text_en IS NULL OR char_length(text_en) BETWEEN 1 AND 6000", name="ck_briefing_en_len"
        ),
        CheckConstraint(
            "text_ar IS NULL OR char_length(text_ar) BETWEEN 1 AND 6000", name="ck_briefing_ar_len"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    job_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_run.id"), nullable=False, unique=True
    )
    night: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
