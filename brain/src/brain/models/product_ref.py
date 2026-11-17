from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ProductRef(Base):
    """The last successful Canonical reads of a product and its preferred supplier."""

    __tablename__ = "product_ref"

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_supplier_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    pack_multiple: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_order_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
