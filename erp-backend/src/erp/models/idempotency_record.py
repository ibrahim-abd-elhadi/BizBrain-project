import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from erp.clock import now_utc
from erp.models.base import Base


class IdempotencyRecord(Base):
    """One Idempotency-Key that created a draft purchase order, with the original response
    (feature 002 FR-030 to FR-033, research R-10). Never updated or deleted in normal use; the
    development reseed truncates it with every other table."""

    __tablename__ = "idempotency_record"
    __table_args__ = (
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_idempotency_record_request_sha256"
        ),
    )

    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    po_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_order.po_id"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
