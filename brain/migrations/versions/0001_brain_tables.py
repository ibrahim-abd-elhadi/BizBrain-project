"""the twelve brain_db tables, and brain-api's read grants

Revision ID: 0001
Revises:
Create Date: 2026-11-17

Feature 003 data-model.md. The tables are created from the models as they are at this revision;
any later change gets its own explicit migration. After creating them, brain-api's login gets
SELECT on the eight read tables if that role already exists (research R-16). If it doesn't, the
idempotent postgres/init/02-brain-api-role.sh applies the same grants when it runs.
"""

import logging

from alembic import op

from brain.config import get_settings
from brain.grants import apply_api_grants, role_exists
from brain.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.brain")


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    role = get_settings().api_db_user
    if role and role_exists(bind, role):
        apply_api_grants(bind, role)
    else:
        log.warning(
            "brain_api role missing (%s): run postgres/init/02-brain-api-role.sh to grant its reads",
            role or "BRAIN_API_DB_USER not set",
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
