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

# This revision's tables, named so that later models (feature 004's proposals, revision 0002) are
# never created here (feature 004 research R-03).
TWELVE = (
    "sales_daily",
    "poll_state",
    "job_run",
    "product_ref",
    "model_artifact",
    "model_choice",
    "forecast",
    "forecast_evaluation",
    "model_health",
    "anomaly",
    "anomaly_scan_progress",
    "risk_result",
)


def _tables():
    return [Base.metadata.tables[name] for name in TWELVE]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_tables())
    role = get_settings().api_db_user
    if role and role_exists(bind, role):
        apply_api_grants(bind, role)
    else:
        log.warning(
            "brain_api role missing (%s): run postgres/init/02-brain-api-role.sh to grant its reads",
            role or "BRAIN_API_DB_USER not set",
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_tables())
