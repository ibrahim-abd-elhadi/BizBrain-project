from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from erp.clock import now_utc
from erp.models.base import Base

# P001, P002, ... assigned by the database and never changed (research R-21).
PRODUCT_ID_DEFAULT = "readable_code('P', nextval('product_code_seq'))"  # migration 0005


class Product(Base):
    __tablename__ = "product"
    __table_args__ = (
        CheckConstraint("pack_multiple >= 1", name="ck_product_pack_multiple"),
        CheckConstraint("max_order_qty >= pack_multiple", name="ck_product_max_order_qty"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="ck_product_name_len"),
    )

    product_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text(PRODUCT_ID_DEFAULT)
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_supplier_id: Mapped[str] = mapped_column(
        Text, ForeignKey("supplier.supplier_id"), nullable=False
    )
    pack_multiple: Mapped[int] = mapped_column(Integer, nullable=False)
    max_order_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        onupdate=now_utc,
        server_default=func.now(),
    )
