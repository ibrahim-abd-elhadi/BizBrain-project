"""readable IDs no longer truncate past 999

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-17

0002 built IDs as 'P' || lpad(n::text, 3, '0'). PostgreSQL's lpad() truncates text that is longer
than the target length, so n = 1000 became 'P100' and collided with the real P100. The new
default pads to three digits but never cuts: P001 ... P999, P1000, P1001. IDs below 1000 come out
exactly as before, so existing rows keep their IDs.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

OLD_SUPPLIER_DEFAULT = "'S' || lpad(nextval('supplier_code_seq')::text, 3, '0')"
OLD_PRODUCT_DEFAULT = "'P' || lpad(nextval('product_code_seq')::text, 3, '0')"


def upgrade() -> None:
    # A function, so nextval() is evaluated once and its digits are read twice safely.
    op.execute(
        """
        CREATE FUNCTION readable_code(prefix text, n bigint) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        AS $$ SELECT prefix || lpad(n::text, greatest(3, length(n::text)), '0') $$
        """
    )
    op.execute(
        "ALTER TABLE supplier ALTER COLUMN supplier_id "
        "SET DEFAULT readable_code('S', nextval('supplier_code_seq'))"
    )
    op.execute(
        "ALTER TABLE product ALTER COLUMN product_id "
        "SET DEFAULT readable_code('P', nextval('product_code_seq'))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE product ALTER COLUMN product_id SET DEFAULT {OLD_PRODUCT_DEFAULT}")
    op.execute(f"ALTER TABLE supplier ALTER COLUMN supplier_id SET DEFAULT {OLD_SUPPLIER_DEFAULT}")
    op.execute("DROP FUNCTION readable_code(text, bigint)")
