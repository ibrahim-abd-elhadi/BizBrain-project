from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from erp.models.base import Base


class ManagerAccount(Base):
    """The single pharmacy manager (FR-001, FR-002, FR-010). There is no role column."""

    __tablename__ = "manager_account"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_manager_account_single_row"),
        CheckConstraint("char_length(username) BETWEEN 3 AND 64", name="ck_manager_username_len"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, default=1, server_default=text("1")
    )
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
