from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class Anomaly(Base):
    """A spike or drop on one day (FR-019 to FR-021). Only a spike on the day being checked
    raises risk; a drop never does."""

    __tablename__ = "anomaly"
    __table_args__ = (
        CheckConstraint("scope IN ('intraday','closed')", name="ck_anomaly_scope"),
        CheckConstraint("kind IN ('spike','drop')", name="ck_anomaly_kind"),
        CheckConstraint("kind = 'spike' OR scope = 'closed'", name="ck_anomaly_drop_closed"),
        CheckConstraint("kind = 'spike' OR NOT raised_risk", name="ck_anomaly_drop_no_raise"),
        UniqueConstraint("product_id", "business_date", "scope", name="uq_anomaly_day_scope"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    net_units: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_28: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    sd_28: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    z: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    raised_risk: Mapped[bool] = mapped_column(Boolean, nullable=False)
    job_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("job_run.id"), nullable=False)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
