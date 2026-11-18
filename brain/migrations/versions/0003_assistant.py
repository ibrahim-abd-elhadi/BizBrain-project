"""the assistant's two tables: briefing and explanation, and brain-api's grants on them

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18

Feature 005 data-model.md:

- briefing: one row per end-of-day run, written by brain-worker (status, both texts when written,
  the facts it was written from);
- explanation: a kept model-phrased Why? per recommendation and language.

Then brain_api gets SELECT on briefing and SELECT, INSERT on explanation (brain/src/brain/grants.py)
if the role exists. Nothing about conversations or model calls is stored (README Section 7).
"""

import logging

from alembic import op

from brain.config import get_settings
from brain.grants import apply_api_grants, role_exists
from brain.models import Base

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.brain")

TWO = ("briefing", "explanation")


def _tables():
    return [Base.metadata.tables[name] for name in TWO]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_tables())
    role = get_settings().api_db_user
    if role and role_exists(bind, role):
        apply_api_grants(bind, role)
    else:
        log.warning(
            "brain_api role missing (%s): run postgres/init/02-brain-api-role.sh to grant its access",
            role or "BRAIN_API_DB_USER not set",
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_tables())
