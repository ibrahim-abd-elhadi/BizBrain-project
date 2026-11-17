from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from erp.clock import now_utc
from erp.models.base import Base


class Stock(Base):
    """Stock at the pharmacy's one location (FR-005): one row per product, no location column."""

    __tablename__ = "stock"
    __table_args__ = (CheckConstraint("on_hand >= 0", name="ck_stock_on_hand"),)

    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("product.product_id"), primary_key=True
    )
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        onupdate=now_utc,
        server_default=func.now(),
    )
