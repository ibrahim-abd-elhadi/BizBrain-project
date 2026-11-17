from datetime import date, datetime

from sqlalchemy import CheckConstraint, Computed, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from erp.clock import now_utc
from erp.models.base import Base


class DailySales(Base):
    """The only place sales are stored: one total per product and Cairo business date (FR-007)."""

    __tablename__ = "daily_sales"
    __table_args__ = (
        CheckConstraint("units_sold >= 0", name="ck_daily_sales_units_sold"),
        CheckConstraint("units_returned >= 0", name="ck_daily_sales_units_returned"),
        CheckConstraint("day_status IN ('open','closed')", name="ck_daily_sales_day_status"),
    )

    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("product.product_id"), primary_key=True
    )
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    units_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    units_returned: Mapped[int] = mapped_column(Integer, nullable=False)
    net_units: Mapped[int] = mapped_column(
        Integer, Computed("units_sold - units_returned", persisted=True)
    )
    day_status: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        onupdate=now_utc,
        server_default=func.now(),
    )
