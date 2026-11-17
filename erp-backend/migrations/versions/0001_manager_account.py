"""manager_account: the single pharmacy manager

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_account",
        sa.Column(
            "id",
            sa.SmallInteger(),
            primary_key=True,
            autoincrement=False,
            server_default=sa.text("1"),
        ),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_manager_account_single_row"),
        sa.CheckConstraint(
            "char_length(username) BETWEEN 3 AND 64", name="ck_manager_username_len"
        ),
        sa.UniqueConstraint("username", name="uq_manager_account_username"),
    )


def downgrade() -> None:
    op.drop_table("manager_account")
