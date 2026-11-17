from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class SalesDaily(Base):
    """The Brain's copy of one product's daily total (FR-005 to FR-008). Upserted by the sales
    poll; an older ERP updated_at never overwrites a newer one."""

    __tablename__ = "sales_daily"
    __table_args__ = (
        CheckConstraint("units_sold >= 0", name="ck_sales_daily_units_sold"),
        CheckConstraint("units_returned >= 0", name="ck_sales_daily_units_returned"),
        CheckConstraint("day_status IN ('open','closed')", name="ck_sales_daily_day_status"),
        Index("ix_sales_daily_changed_at", "changed_at"),
    )

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    units_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    units_returned: Mapped[int] = mapped_column(Integer, nullable=False)
    net_units: Mapped[int] = mapped_column(Integer, nullable=False)  # may be negative
    day_status: Mapped[str] = mapped_column(Text, nullable=False)
    erp_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
