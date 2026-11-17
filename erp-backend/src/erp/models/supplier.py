from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from erp.clock import now_utc
from erp.models.base import Base

# S001, S002, ... assigned by the database and never changed (research R-21).
SUPPLIER_ID_DEFAULT = "readable_code('S', nextval('supplier_code_seq'))"  # migration 0005


class Supplier(Base):
    __tablename__ = "supplier"
    __table_args__ = (
        CheckConstraint("lead_time_days >= 1", name="ck_supplier_lead_time"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="ck_supplier_name_len"),
    )

    supplier_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text(SUPPLIER_ID_DEFAULT)
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
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
