"""Approving, rejecting and sending proposals (feature 004 research R-06, R-07; README 4.5 steps
3-5; FR-013 to FR-025a).

The ERP call never happens inside a database transaction:

1. one short transaction checks the fingerprint, records the approval and the exact request body,
   moves the proposal to "uncertain" and starts an attempt;
2. one POST to the ERP, with no transaction open (one attempt, no automatic retry);
3. one short transaction records the outcome, with a guarded update, so a late or repeated
   answer never moves a "draft_created" proposal backwards.

A crash between 1 and 3 leaves the proposal "uncertain" with its stored body, so Send again
resends exactly the same request (same key, same bytes) and can never create a second order.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from brain.canonical.client import CanonicalClient, CanonicalUnavailable, SendResult
from brain.clock import now_utc
from brain.config import get_settings
from brain.models import Proposal, ProposalAttempt
from brain.proposals.canonical import canonical
from brain.proposals.service import ProposalRefused

UNCLEAR = "the ERP didn't confirm the draft"
UNREADABLE = "the ERP's answer couldn't be read"
NOT_SENT = "the Brain's ERP credential file is missing"
CREDENTIAL = "the Brain's ERP credential was refused"
CONFLICT = "the ERP already used this proposal's key for a different order"


@dataclass(frozen=True)
class Outcome:
    status: str  # the proposal's status after this answer
    outcome: str  # the attempt's outcome
    detail: str
    http_status: int | None = None
    erp_code: str | None = None
    purchase_order_id: int | None = None
    failure_code: str | None = None
    failure_reason: str | None = None


def _redact(text: str) -> str:
    """Never let a credential through into a stored reason (FR-028)."""
    return re.sub(r"(?i)bearer\s+\S+", "[credential]", text)[:200]


def _erp_error(body: Any) -> tuple[str | None, str | None]:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        return error.get("code"), error.get("message")
    return None, None


def _matches(body: Any, proposal: Any) -> bool:
    """A 2xx counts only if it is the draft this proposal asked for."""
    if not isinstance(body, dict):
        return False
    order_id = body.get("purchase_order_id")
    if isinstance(order_id, bool) or not isinstance(order_id, int):
        return False
    approval = body.get("approval")
    if not isinstance(approval, dict) or approval.get("proposal_id") != str(proposal.id):
        return False
    if body.get("status") != "draft" or body.get("supplier_id") != proposal.supplier_id:
        return False
    lines = body.get("lines")
    if not isinstance(lines, list):
        return False
    try:
        got = sorted((line["product_id"], line["ordered_qty"]) for line in lines)
    except (KeyError, TypeError):
        return False
    wanted = sorted((line["product_id"], line["quantity"]) for line in proposal.arguments["lines"])
    return got == wanted


def classify(result: SendResult, proposal: Any) -> Outcome:
    """What one ERP answer means (the research R-07 table)."""
    if result.error == "not_sent":
        return Outcome("uncertain", "not_sent", NOT_SENT)
    if result.error is not None or result.status is None:
        return Outcome("uncertain", "uncertain", UNCLEAR)
    status, body = result.status, result.body
    code, message = _erp_error(body)
    if status in (200, 201):
        if _matches(body, proposal):
            number = body["purchase_order_id"]
            return Outcome(
                "draft_created",
                "draft_created",
                f"draft created: ERP order #{number}",
                http_status=status,
                purchase_order_id=number,
            )
        return Outcome("uncertain", "uncertain", UNREADABLE, http_status=status)
    if status == 429 or status >= 500:
        return Outcome("uncertain", "uncertain", UNCLEAR, http_status=status, erp_code=code)
    if status == 409 and code == "IDEMPOTENCY_CONFLICT":
        reason = CONFLICT
    elif status == 422:
        code = code or "VALIDATION_ERROR"
        reason = "the ERP refused the order" + (f": {_redact(message)}" if message else "")
    elif status in (401, 403):
        code = code or ("UNAUTHORIZED" if status == 401 else "FORBIDDEN")
        reason = CREDENTIAL
    else:
        code = f"HTTP_{status}"
        reason = f"the ERP refused the request (HTTP {status})"
    return Outcome(
        "failed",
        "failed",
        reason,
        http_status=status,
        erp_code=code,
        failure_code=code,
        failure_reason=reason,
    )


def _approval_time() -> datetime:
    """Now, to the millisecond, so the stored time and the sent text are the same instant."""
    now = now_utc().astimezone(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def _iso_ms(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _locked(session: Session, proposal_id: uuid.UUID) -> Proposal:
    proposal = session.scalars(
        select(Proposal).where(Proposal.id == proposal_id).with_for_update()
    ).first()
    if proposal is None:
        raise ProposalRefused("NOT_FOUND", f"No proposal {proposal_id}")
    return proposal


def send(proposal_id: uuid.UUID, body: str) -> SendResult:
    """One draft-PO request with the stored body. The token file is read now (FR-028)."""
    try:
        client = CanonicalClient.from_settings(get_settings())
    except CanonicalUnavailable:
        return SendResult(error="not_sent")
    with client:
        return client.create_draft_purchase_order(proposal_id, body.encode("utf-8"))


def record(
    factory: sessionmaker[Session], proposal_id: uuid.UUID, attempt_no: int, result: SendResult
) -> None:
    """Transaction 2: finish the attempt and move the proposal, never backwards."""
    with factory() as session:
        proposal = session.get(Proposal, proposal_id)
        outcome = classify(result, proposal)
        now = now_utc()
        attempt = session.scalars(
            select(ProposalAttempt).where(
                ProposalAttempt.proposal_id == proposal_id, ProposalAttempt.attempt_no == attempt_no
            )
        ).one()
        attempt.finished_at = now
        attempt.outcome = outcome.outcome
        attempt.http_status = outcome.http_status
        attempt.erp_code = outcome.erp_code
        attempt.detail = outcome.detail
        attempt.purchase_order_id = outcome.purchase_order_id
        if outcome.status in ("draft_created", "failed"):
            session.execute(
                update(Proposal)
                .where(Proposal.id == proposal_id, Proposal.status == "uncertain")
                .values(
                    status=outcome.status,
                    purchase_order_id=outcome.purchase_order_id,
                    failure_code=outcome.failure_code,
                    failure_reason=outcome.failure_reason,
                    closed_at=now,
                )
                .execution_options(synchronize_session=False)
            )
        session.commit()


def approve(
    factory: sessionmaker[Session], proposal_id: uuid.UUID | str, sent_sha256: str, username: str
) -> None:
    """Approve with the fingerprint the manager saw, then send once (FR-013 to FR-016)."""
    proposal_id = uuid.UUID(str(proposal_id))
    with factory() as session:
        proposal = _locked(session, proposal_id)
        if proposal.status != "awaiting_approval":
            raise ProposalRefused(
                "NOT_AWAITING_APPROVAL", "this proposal is no longer awaiting approval"
            )
        if sent_sha256 != proposal.arguments_sha256:
            raise ProposalRefused(
                "FINGERPRINT_MISMATCH",
                "the fingerprint you approved isn't this proposal's; reload it and check again",
            )
        approved_at = _approval_time()
        body = canonical(
            {
                **proposal.arguments,
                "approval": {
                    "proposal_id": str(proposal.id),
                    "approved_by": username,
                    "approved_at": _iso_ms(approved_at),
                    "arguments_sha256": proposal.arguments_sha256,
                },
            }
        )
        proposal.approved_by = username
        proposal.approved_at = approved_at
        proposal.request_body = body
        proposal.status = "uncertain"
        session.add(ProposalAttempt(proposal_id=proposal.id, attempt_no=1, started_at=now_utc()))
        session.commit()
    record(factory, proposal_id, 1, send(proposal_id, body))


def reject(session: Session, proposal_id: uuid.UUID) -> None:
    """Close a proposal awaiting approval for good; nothing is sent (FR-025). The caller commits."""
    proposal = _locked(session, proposal_id)
    if proposal.status != "awaiting_approval":
        raise ProposalRefused(
            "NOT_AWAITING_APPROVAL", "only a proposal awaiting approval can be rejected"
        )
    proposal.status = "rejected"
    proposal.closed_at = now_utc()


def send_again(factory: sessionmaker[Session], proposal_id: uuid.UUID | str) -> None:
    """Resend an uncertain proposal's stored request: same key, same bytes (FR-016, FR-018).
    A "draft_created" proposal is never sent again (FR-021)."""
    proposal_id = uuid.UUID(str(proposal_id))
    with factory() as session:
        proposal = _locked(session, proposal_id)
        if proposal.status != "uncertain":
            raise ProposalRefused("NOT_UNCERTAIN", "only an uncertain proposal can be sent again")
        body = proposal.request_body
        number = (
            session.scalar(
                select(func.max(ProposalAttempt.attempt_no)).where(
                    ProposalAttempt.proposal_id == proposal_id
                )
            )
            or 0
        ) + 1
        session.add(
            ProposalAttempt(proposal_id=proposal_id, attempt_no=number, started_at=now_utc())
        )
        session.commit()
    record(factory, proposal_id, number, send(proposal_id, body))
