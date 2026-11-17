import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base

_LEVEL = "CASE {c} WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 END"


class RiskResult(Base):
    """One risk and recommendation computation, append-only (FR-022 to FR-028). Every input is
    kept so the numbers can be checked by hand; feature 004 will point proposals at `id`."""

    __tablename__ = "risk_result"
    __table_args__ = (
        CheckConstraint("risk IN ('high','medium','low')", name="ck_risk_result_risk"),
        CheckConstraint("base_risk IN ('high','medium','low')", name="ck_risk_result_base"),
        CheckConstraint(
            "(risk IS NULL) = (base_risk IS NULL)", name="ck_risk_result_risk_needs_base"
        ),
        CheckConstraint(
            f"risk IS NULL OR {_LEVEL.format(c='risk')} >= {_LEVEL.format(c='base_risk')}",
            name="ck_risk_result_raise_only",
        ),
        CheckConstraint(
            "(order_qty IS NULL) = (reason_code IS NOT NULL)", name="ck_risk_result_qty_or_reason"
        ),
        CheckConstraint(
            "reason_code IN ('NO_SUPPLIER','OPEN_PO_UNAVAILABLE')", name="ck_risk_result_reason"
        ),
        CheckConstraint("order_qty >= 0", name="ck_risk_result_order_qty"),
        Index("ix_risk_result_product_computed", "product_id", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    job_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("job_run.id"), nullable=False)
    forecast_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_run.id"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_of_cover: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    base_risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    raised_by_spike: Mapped[bool] = mapped_column(Boolean, nullable=False)
    open_po_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forecast_over_lead: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    review_period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sd_28: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    mean_28: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pack_multiple: Mapped[int] = mapped_column(Integer, nullable=False)
    max_order_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(Text, nullable=True)
