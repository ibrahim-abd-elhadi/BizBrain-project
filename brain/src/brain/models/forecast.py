from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class Forecast(Base):
    """One product's forecast for one day, from one end-of-day run."""

    __tablename__ = "forecast"
    __table_args__ = (
        CheckConstraint("0 <= low AND low <= yhat AND yhat <= high", name="ck_forecast_range"),
        CheckConstraint("model IN ('seasonal_naive','lightgbm')", name="ck_forecast_model"),
    )

    job_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_run.id"), primary_key=True
    )
    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    target_date: Mapped[date] = mapped_column(Date, primary_key=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    yhat: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
