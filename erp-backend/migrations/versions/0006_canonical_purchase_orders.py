"""purchase orders gain supplier, creator, approval and updated_at; idempotency_record; sales index

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17

Feature 002 (Canonical API), data-model.md:
- purchase_order: supplier_id (FR-026), created_by, the approval block, updated_at;
- idempotency_record: one row per Idempotency-Key that created a draft (research R-10);
- ix_daily_sales_updated_key: serves updated_since and the sales keyset order (research R-09).

Existing orders get their supplier from their first line's product's preferred supplier. An order
with no lines has no supplier to take, so the migration refuses to run rather than guess.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SHA256 = "'^[0-9a-f]{64}$'"
APPROVAL = (
    "approval_proposal_id",
    "approval_approved_by",
    "approval_approved_at",
    "approval_arguments_sha256",
)


def upgrade() -> None:
    bind = op.get_bind()
    without_lines = (
        bind.execute(
            sa.text(
                "SELECT po.po_id FROM purchase_order po WHERE NOT EXISTS "
                "(SELECT 1 FROM purchase_order_line l WHERE l.po_id = po.po_id) ORDER BY po.po_id"
            )
        )
        .scalars()
        .all()
    )
    if without_lines:
        ids = ", ".join(str(po_id) for po_id in without_lines)
        raise RuntimeError(
            "Migration 0006 refused: these purchase orders have no lines, so no supplier can be "
            f"backfilled: {ids}. Add a line to each, or remove them by hand, then run the "
            "migration again."
        )

    op.add_column("purchase_order", sa.Column("supplier_id", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE purchase_order po SET supplier_id = (
            SELECT p.preferred_supplier_id
            FROM purchase_order_line l JOIN product p USING (product_id)
            WHERE l.po_id = po.po_id
            ORDER BY l.product_id
            LIMIT 1
        )
        """
    )
    op.alter_column("purchase_order", "supplier_id", nullable=False)
    op.create_foreign_key(
        "fk_purchase_order_supplier_id",
        "purchase_order",
        "supplier",
        ["supplier_id"],
        ["supplier_id"],
    )

    op.add_column(
        "purchase_order",
        sa.Column("created_by", sa.Text(), nullable=False, server_default="human"),
    )
    op.add_column(
        "purchase_order", sa.Column("approval_proposal_id", UUID(as_uuid=True), nullable=True)
    )
    op.add_column("purchase_order", sa.Column("approval_approved_by", sa.Text(), nullable=True))
    op.add_column(
        "purchase_order",
        sa.Column("approval_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "purchase_order", sa.Column("approval_arguments_sha256", sa.Text(), nullable=True)
    )
    op.add_column(
        "purchase_order",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute("UPDATE purchase_order SET updated_at = COALESCE(confirmed_at, created_at)")

    op.create_unique_constraint(
        "uq_purchase_order_approval_proposal_id", "purchase_order", ["approval_proposal_id"]
    )
    op.create_check_constraint(
        "ck_purchase_order_created_by", "purchase_order", "created_by IN ('human','agent')"
    )
    op.create_check_constraint(
        "ck_purchase_order_approved_by_length",
        "purchase_order",
        "char_length(approval_approved_by) BETWEEN 1 AND 128",
    )
    op.create_check_constraint(
        "ck_purchase_order_arguments_sha256",
        "purchase_order",
        f"approval_arguments_sha256 ~ {SHA256}",
    )
    all_null = " AND ".join(f"{column} IS NULL" for column in APPROVAL)
    none_null = " AND ".join(f"{column} IS NOT NULL" for column in APPROVAL)
    op.create_check_constraint(
        "ck_purchase_order_approval_all_or_none",
        "purchase_order",
        f"({all_null}) OR ({none_null})",
    )
    op.create_check_constraint(
        "ck_purchase_order_approval_matches_creator",
        "purchase_order",
        "(created_by = 'agent') = (approval_proposal_id IS NOT NULL)",
    )

    op.create_table(
        "idempotency_record",
        sa.Column("key", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_sha256", sa.Text(), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=False),
        sa.Column("response_body", JSONB(), nullable=False),
        sa.Column(
            "po_id",
            sa.BigInteger(),
            sa.ForeignKey("purchase_order.po_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            f"request_sha256 ~ {SHA256}", name="ck_idempotency_record_request_sha256"
        ),
    )

    op.create_index(
        "ix_daily_sales_updated_key", "daily_sales", ["updated_at", "product_id", "business_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_daily_sales_updated_key", table_name="daily_sales")
    op.drop_table("idempotency_record")
    for name in (
        "ck_purchase_order_approval_matches_creator",
        "ck_purchase_order_approval_all_or_none",
        "ck_purchase_order_arguments_sha256",
        "ck_purchase_order_approved_by_length",
        "ck_purchase_order_created_by",
    ):
        op.drop_constraint(name, "purchase_order", type_="check")
    op.drop_constraint("uq_purchase_order_approval_proposal_id", "purchase_order", type_="unique")
    op.drop_constraint("fk_purchase_order_supplier_id", "purchase_order", type_="foreignkey")
    for column in ("updated_at", *reversed(APPROVAL), "created_by", "supplier_id"):
        op.drop_column("purchase_order", column)
