from datetime import date

from sqlalchemy import Date, Text
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class AnomalyScanProgress(Base):
    """Per product: the newest closed day the end-of-day scan has checked."""

    __tablename__ = "anomaly_scan_progress"

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scanned_through: Mapped[date] = mapped_column(Date, nullable=False)
