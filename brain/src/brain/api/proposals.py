"""Proposals for the signed-in manager (feature 004; contracts/brain/brain-api-proposals.openapi.yaml).

Create, list and read in User Story 1; approve and reject in User Story 2; send again in User
Story 3. Only `approve` and `send-again` ever reach the ERP (research R-06). Nothing here calls an
LLM (FR-003) or runs a worker job (D-38).
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.api.auth import require_manager
from brain.api.errors import BrainError
from brain.clock import now_utc
from brain.config import get_settings
from brain.db import SessionDep, get_api_sessionmaker
from brain.models import ProductRef, Proposal, ProposalAttempt, ProposalLine, RiskResult
from brain.proposals import execution
from brain.proposals.service import ProposalRefused, propose_from_recommendation

router = APIRouter(prefix="/api/v1/brain", dependencies=[Depends(require_manager)])

STATUS_CODES = {
    "NOT_FOUND": 404,
    "VALIDATION_ERROR": 422,
    "NO_ORDER_RECOMMENDED": 422,
    "RECOMMENDATION_CHANGED": 409,
    "PROPOSAL_PENDING": 409,
    "FINGERPRINT_MISMATCH": 409,
    "NOT_AWAITING_APPROVAL": 409,
    "NOT_UNCERTAIN": 409,
}


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation_id: uuid.UUID


class ApproveBody(BaseModel):
    """The fingerprint the manager was shown (FR-013)."""

    model_config = ConfigDict(extra="forbid")
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def refused(exc: ProposalRefused) -> JSONResponse:
    body: dict[str, Any] = {"detail": exc.detail, "code": exc.code}
    if exc.proposal_id is not None:
        body["proposal_id"] = str(exc.proposal_id)
    return JSONResponse(body, status_code=STATUS_CODES.get(exc.code, 422))


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _supplier_names(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(ProductRef.preferred_supplier_id, ProductRef.supplier_name).where(
            ProductRef.supplier_name.is_not(None)
        )
    ).all()
    return {supplier: name for supplier, name in rows if supplier}


def _sending(attempt: ProposalAttempt | None) -> bool:
    """An attempt in flight: unfinished and started less than the ERP timeout + 5 s ago."""
    if attempt is None or attempt.finished_at is not None:
        return False
    limit = timedelta(seconds=get_settings().erp_timeout_seconds + 5)
    return now_utc() - attempt.started_at < limit


def _attempts(session: Session, proposal_id: uuid.UUID) -> list[ProposalAttempt]:
    return list(
        session.scalars(
            select(ProposalAttempt)
            .where(ProposalAttempt.proposal_id == proposal_id)
            .order_by(ProposalAttempt.attempt_no)
        )
    )


def proposal_json(
    p: Proposal, names: dict[str, str], latest: ProposalAttempt | None
) -> dict[str, Any]:
    return {
        "synthetic": True,
        "id": str(p.id),
        "action": p.action,
        "origin": p.origin,
        "status": p.status,
        "sending": _sending(latest),
        "supplier_id": p.supplier_id,
        "supplier_name": names.get(p.supplier_id),
        "arguments": p.arguments,
        "arguments_sha256": p.arguments_sha256,
        "recommendation_id": str(p.recommendation_id) if p.recommendation_id else None,
        "purchase_order_id": p.purchase_order_id,
        "created_at": p.created_at.isoformat(),
    }


def _summary(r: RiskResult) -> dict[str, Any]:
    return {
        "recommendation_id": str(r.id),
        "product_id": r.product_id,
        "risk": r.risk,
        "days_of_cover": _num(r.days_of_cover),
        "lead_time_days": r.lead_time_days,
        "order_qty": r.order_qty,
        "computed_at": r.computed_at.isoformat(),
    }


def _newest(session: Session, product_id: str) -> RiskResult | None:
    return session.scalars(
        select(RiskResult)
        .where(RiskResult.product_id == product_id)
        .order_by(RiskResult.computed_at.desc(), RiskResult.id)
        .limit(1)
    ).first()


def detail_json(session: Session, p: Proposal) -> dict[str, Any]:
    names = _supplier_names(session)
    attempts = _attempts(session, p.id)
    body = proposal_json(p, names, attempts[-1] if attempts else None)
    product_names = dict(session.execute(select(ProductRef.product_id, ProductRef.name)).all())
    lines = session.scalars(
        select(ProposalLine).where(ProposalLine.proposal_id == p.id).order_by(ProposalLine.line_no)
    )
    rec = session.get(RiskResult, p.recommendation_id) if p.recommendation_id else None
    newer = None
    if rec is not None and p.status == "awaiting_approval":
        newest = _newest(session, rec.product_id)
        if newest is not None and newest.id != rec.id:
            newer = _summary(newest)
    body.update(
        {
            "lines": [
                {
                    "product_id": line.product_id,
                    "product_name": product_names.get(line.product_id),
                    "quantity": line.quantity,
                }
                for line in lines
            ],
            "recommendation": _summary(rec) if rec is not None else None,
            "newer_recommendation": newer,
            "approval": (
                {"approved_by": p.approved_by, "approved_at": p.approved_at.isoformat()}
                if p.approved_at is not None
                else None
            ),
            "failure": (
                {"code": p.failure_code, "reason": p.failure_reason} if p.failure_code else None
            ),
            "attempts": [
                {
                    "attempt_no": a.attempt_no,
                    "started_at": a.started_at.isoformat(),
                    "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                    "outcome": a.outcome,
                    "http_status": a.http_status,
                    "erp_code": a.erp_code,
                    "detail": a.detail,
                    "purchase_order_id": a.purchase_order_id,
                }
                for a in attempts
            ],
        }
    )
    return body


def load(session: Session, proposal_id: uuid.UUID) -> Proposal:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise BrainError(404, "NOT_FOUND", f"No proposal {proposal_id}")
    return proposal


@router.post("/proposals", status_code=201)
def create_from_recommendation(body: CreateBody, session: SessionDep) -> Any:
    try:
        proposal = propose_from_recommendation(session, body.recommendation_id)
    except ProposalRefused as exc:
        session.rollback()
        return refused(exc)
    session.commit()
    return proposal_json(proposal, _supplier_names(session), None)


@router.get("/proposals")
def list_proposals(session: SessionDep) -> dict[str, Any]:
    names = _supplier_names(session)
    proposals = list(
        session.scalars(select(Proposal).order_by(Proposal.created_at.desc(), Proposal.id))
    )
    latest: dict[uuid.UUID, ProposalAttempt] = {}
    for attempt in session.scalars(select(ProposalAttempt).order_by(ProposalAttempt.attempt_no)):
        latest[attempt.proposal_id] = attempt
    return {
        "synthetic": True,
        "items": [proposal_json(p, names, latest.get(p.id)) for p in proposals],
    }


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    return detail_json(session, load(session, proposal_id))


def _fresh(session: Session, proposal_id: uuid.UUID) -> dict[str, Any]:
    session.expire_all()
    return detail_json(session, load(session, proposal_id))


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(
    proposal_id: uuid.UUID,
    body: ApproveBody,
    session: SessionDep,
    username: str = Depends(require_manager),
) -> Any:
    """Check the fingerprint, record the approval, send the draft once (research R-06). The ERP's
    answer is in the returned status; it is never an HTTP error here."""
    try:
        execution.approve(get_api_sessionmaker(), proposal_id, body.arguments_sha256, username)
    except ProposalRefused as exc:
        return refused(exc)
    return _fresh(session, proposal_id)


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: uuid.UUID, session: SessionDep) -> Any:
    try:
        execution.reject(session, proposal_id)
    except ProposalRefused as exc:
        session.rollback()
        return refused(exc)
    session.commit()
    return _fresh(session, proposal_id)


@router.post("/proposals/{proposal_id}/send-again")
def send_proposal_again(proposal_id: uuid.UUID, session: SessionDep) -> Any:
    """Resend the stored request of an uncertain proposal (research R-06)."""
    try:
        execution.send_again(get_api_sessionmaker(), proposal_id)
    except ProposalRefused as exc:
        return refused(exc)
    return _fresh(session, proposal_id)
