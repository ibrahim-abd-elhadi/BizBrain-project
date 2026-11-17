"""daily_sales: one total per product and Cairo business date

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_sales",
        sa.Column("product_id", sa.Text(), sa.ForeignKey("product.product_id"), primary_key=True),
        sa.Column("business_date", sa.Date(), primary_key=True),
        sa.Column("units_sold", sa.Integer(), nullable=False),
        sa.Column("units_returned", sa.Integer(), nullable=False),
        sa.Column(
            "net_units",
            sa.Integer(),
            sa.Computed("units_sold - units_returned", persisted=True),
        ),
        sa.Column("day_status", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("units_sold >= 0", name="ck_daily_sales_units_sold"),
        sa.CheckConstraint("units_returned >= 0", name="ck_daily_sales_units_returned"),
        sa.CheckConstraint("day_status IN ('open','closed')", name="ck_daily_sales_day_status"),
    )
    # The 28-day history lookups and the default GET /sales range read by date.
    op.create_index("ix_daily_sales_business_date", "daily_sales", ["business_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_sales_business_date", table_name="daily_sales")
    op.drop_table("daily_sales")
