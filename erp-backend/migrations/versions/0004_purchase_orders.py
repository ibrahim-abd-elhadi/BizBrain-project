"""purchase_order and purchase_order_line

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_order",
        sa.Column("po_id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft','confirmed')", name="ck_purchase_order_status"),
        sa.CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_purchase_order_confirmed_at",
        ),
    )
    op.create_table(
        "purchase_order_line",
        sa.Column(
            "po_id", sa.BigInteger(), sa.ForeignKey("purchase_order.po_id"), primary_key=True
        ),
        sa.Column("product_id", sa.Text(), sa.ForeignKey("product.product_id"), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_order_line_quantity"),
    )


def downgrade() -> None:
    op.drop_table("purchase_order_line")
    op.drop_table("purchase_order")
