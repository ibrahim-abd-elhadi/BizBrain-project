from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from brain.models.base import Base


class ModelChoice(Base):
    """Per end-of-day run and product: eligibility, both backtest WAPEs and the chosen model."""

    __tablename__ = "model_choice"
    __table_args__ = (
        CheckConstraint(
            "chosen_model IN ('seasonal_naive','lightgbm')", name="ck_model_choice_model"
        ),
    )

    job_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("job_run.id"), primary_key=True)
    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    history_days: Mapped[int] = mapped_column(Integer, nullable=False)
    lgbm_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lgbm_replaced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sn_backtest_wape: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    lgbm_backtest_wape: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    chosen_model: Mapped[str] = mapped_column(Text, nullable=False)
    residual_q10: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    residual_q90: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
