"""catalog: supplier, product, stock and the readable-ID sequences

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE supplier_code_seq")
    op.execute("CREATE SEQUENCE product_code_seq")

    op.create_table(
        "supplier",
        sa.Column(
            "supplier_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("'S' || lpad(nextval('supplier_code_seq')::text, 3, '0')"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("lead_time_days >= 1", name="ck_supplier_lead_time"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="ck_supplier_name_len"),
    )

    op.create_table(
        "product",
        sa.Column(
            "product_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("'P' || lpad(nextval('product_code_seq')::text, 3, '0')"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "preferred_supplier_id",
            sa.Text(),
            sa.ForeignKey("supplier.supplier_id"),
            nullable=False,
        ),
        sa.Column("pack_multiple", sa.Integer(), nullable=False),
        sa.Column("max_order_qty", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("pack_multiple >= 1", name="ck_product_pack_multiple"),
        sa.CheckConstraint("max_order_qty >= pack_multiple", name="ck_product_max_order_qty"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="ck_product_name_len"),
    )

    op.create_table(
        "stock",
        sa.Column("product_id", sa.Text(), sa.ForeignKey("product.product_id"), primary_key=True),
        sa.Column("on_hand", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("on_hand >= 0", name="ck_stock_on_hand"),
    )


def downgrade() -> None:
    op.drop_table("stock")
    op.drop_table("product")
    op.drop_table("supplier")
    op.execute("DROP SEQUENCE product_code_seq")
    op.execute("DROP SEQUENCE supplier_code_seq")
