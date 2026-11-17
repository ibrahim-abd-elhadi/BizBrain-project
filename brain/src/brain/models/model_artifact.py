from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ModelArtifact(Base):
    """A night's LightGBM model in LightGBM's own text format; never pickle (research R-11)."""

    __tablename__ = "model_artifact"
    __table_args__ = (
        CheckConstraint("format = 'lightgbm-text'", name="ck_model_artifact_format"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_model_artifact_sha256"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    job_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_run.id"), nullable=False, unique=True
    )
    format: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    lightgbm_version: Mapped[str] = mapped_column(Text, nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trained_through: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
