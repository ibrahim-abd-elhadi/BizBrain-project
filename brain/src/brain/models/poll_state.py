from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class PollState(Base):
    """The saved watermark: the last page's high_watermark of the last complete poll."""

    __tablename__ = "poll_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_poll_state_single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    high_watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
