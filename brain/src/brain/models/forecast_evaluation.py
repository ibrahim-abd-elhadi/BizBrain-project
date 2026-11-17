from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ForecastEvaluation(Base):
    """Yesterday's forecast against yesterday's closed actual, per product (FR-017)."""

    __tablename__ = "forecast_evaluation"

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    job_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("job_run.id"), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    forecast: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    actual: Mapped[int] = mapped_column(Integer, nullable=False)
