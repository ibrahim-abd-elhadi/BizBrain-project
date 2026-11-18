"""the four proposal tables, their rules, and brain-api's write grants

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18

Feature 004 data-model.md. The database itself enforces (research R-03 to R-05):

- proposal_guard: arguments, fingerprint and identity never change; the approval is written once;
  only the status changes of FR-025a; a final proposal never changes;
- proposal_line_lock / proposal_release: one live proposal per product (D-30, FR-023);
- proposal_attempt_guard: an attempt is finished once.

The functions belong to brain_worker (the migrating login), so brain_api can't drop or disable
them. Then brain_api gets its grants (brain/src/brain/grants.py) if the role exists.
"""

import logging

from alembic import op

from brain.config import get_settings
from brain.grants import apply_api_grants, role_exists
from brain.models import Base

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.brain")

FOUR = ("proposal", "proposal_line", "proposal_live_product", "proposal_attempt")

FUNCTIONS = """
CREATE FUNCTION proposal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.action IS DISTINCT FROM OLD.action
       OR NEW.origin IS DISTINCT FROM OLD.origin
       OR NEW.recommendation_id IS DISTINCT FROM OLD.recommendation_id
       OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
       OR NEW.arguments IS DISTINCT FROM OLD.arguments
       OR NEW.arguments_canonical IS DISTINCT FROM OLD.arguments_canonical
       OR NEW.arguments_sha256 IS DISTINCT FROM OLD.arguments_sha256
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'proposal %: arguments are immutable', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF (OLD.approved_by IS NOT NULL AND NEW.approved_by IS DISTINCT FROM OLD.approved_by)
       OR (OLD.approved_at IS NOT NULL AND NEW.approved_at IS DISTINCT FROM OLD.approved_at)
       OR (OLD.request_body IS NOT NULL AND NEW.request_body IS DISTINCT FROM OLD.request_body) THEN
        RAISE EXCEPTION 'proposal %: the approval is written once', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status IN ('draft_created', 'failed', 'rejected') AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'proposal %: a % proposal never changes', OLD.id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'awaiting_approval'
            AND NEW.status IN ('uncertain', 'draft_created', 'failed', 'rejected'))
        OR (OLD.status = 'uncertain' AND NEW.status IN ('draft_created', 'failed'))
    ) THEN
        RAISE EXCEPTION 'proposal %: % -> % is not allowed', OLD.id, OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION proposal_line_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO proposal_live_product (product_id, proposal_id)
    VALUES (NEW.product_id, NEW.proposal_id);
    RETURN NULL;
END $$;

CREATE FUNCTION proposal_release() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM proposal_live_product WHERE proposal_id = NEW.id;
    RETURN NULL;
END $$;

CREATE FUNCTION proposal_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.finished_at IS NOT NULL THEN
        RAISE EXCEPTION 'attempt % of proposal % is already finished', OLD.attempt_no, OLD.proposal_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.proposal_id IS DISTINCT FROM OLD.proposal_id
       OR NEW.attempt_no IS DISTINCT FROM OLD.attempt_no
       OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
        RAISE EXCEPTION 'attempt % of proposal %: only its result may be recorded',
            OLD.attempt_no, OLD.proposal_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER proposal_guard BEFORE UPDATE ON proposal
    FOR EACH ROW EXECUTE FUNCTION proposal_guard();
CREATE TRIGGER proposal_line_lock AFTER INSERT ON proposal_line
    FOR EACH ROW EXECUTE FUNCTION proposal_line_lock();
CREATE TRIGGER proposal_release AFTER UPDATE OF status ON proposal
    FOR EACH ROW WHEN (NEW.status IN ('draft_created', 'failed', 'rejected'))
    EXECUTE FUNCTION proposal_release();
CREATE TRIGGER proposal_attempt_guard BEFORE UPDATE ON proposal_attempt
    FOR EACH ROW EXECUTE FUNCTION proposal_attempt_guard();
"""


def _tables():
    return [Base.metadata.tables[name] for name in FOUR]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_tables())
    op.execute(FUNCTIONS)
    role = get_settings().api_db_user
    if role and role_exists(bind, role):
        apply_api_grants(bind, role)
    else:
        log.warning(
            "brain_api role missing (%s): run postgres/init/02-brain-api-role.sh to grant its access",
            role or "BRAIN_API_DB_USER not set",
        )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=_tables())  # drops the triggers with the tables
    op.execute(
        "DROP FUNCTION IF EXISTS proposal_guard(), proposal_line_lock(), proposal_release(),"
        " proposal_attempt_guard()"
    )
