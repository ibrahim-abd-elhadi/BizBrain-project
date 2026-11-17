from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Identity, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class JobRun(Base):
    """One run of a job: the worker's own bookkeeping, not an audit log (README Section 7)."""

    __tablename__ = "job_run"
    __table_args__ = (
        CheckConstraint(
            "job IN ('sales-poll','hourly-window','end-of-day')", name="ck_job_run_job"
        ),
        CheckConstraint(
            "trigger IN ('schedule','manual','catch-up')", name="ck_job_run_trigger"
        ),
        CheckConstraint(
            "status IN ('running','succeeded','failed','skipped')", name="ck_job_run_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
