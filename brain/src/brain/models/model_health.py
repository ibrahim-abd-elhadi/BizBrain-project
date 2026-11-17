from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ModelHealth(Base):
    """Per product: the live-WAPE window of the model kind serving it, and the degraded mark."""

    __tablename__ = "model_health"

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    window_started: Mapped[date] = mapped_column(Date, nullable=False)
    evaluated_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backtest_wape: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    live_wape: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degraded_on: Mapped[date | None] = mapped_column(Date, nullable=True)
