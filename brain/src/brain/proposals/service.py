"""Creating proposals (feature 004 research R-02, R-08, R-09; contracts/brain/create-proposal.md).

`create_proposal` is the one internal create function: the Risk and insights action uses it
through `propose_from_recommendation`, and feature 005's `propose_purchase_order` tool will call
it directly. It only writes the proposal in the caller's transaction; it never contacts the ERP
and never calls an LLM (FR-003, FR-008).
"""

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from brain.clock import now_utc
from brain.models import ProductRef, Proposal, ProposalLine, ProposalLiveProduct, RiskResult
from brain.proposals.canonical import canonical, fingerprint

SUPPLIER_ID = re.compile(r"^S[0-9]{3,}$")
PRODUCT_ID = re.compile(r"^P[0-9]{3,}$")
MAX_LINES = 50
MAX_QUANTITY = 1_000_000
ORIGINS = ("recommendation", "assistant")

REASON_WORDS = {
    "OPEN_PO_UNAVAILABLE": "open orders couldn't be read, so there is no order quantity",
    "NO_SUPPLIER": "the supplier couldn't be read, so there is no order quantity",
}
CHANGED = "the recommendation changed; reload to see the new quantity"


class ProposalRefused(Exception):
    """A proposal that can't be created; nothing is written. `code` is the API's error code."""

    def __init__(self, code: str, detail: str, proposal_id: uuid.UUID | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.proposal_id = proposal_id


def _invalid(detail: str) -> ProposalRefused:
    return ProposalRefused("VALIDATION_ERROR", detail)


def build_arguments(supplier_id: Any, lines: Any) -> dict[str, Any]:
    """Validate the draft-PO arguments (feature 002's request without its approval block) and
    return them with the lines sorted by product, so equal arguments give one fingerprint."""
    if not isinstance(supplier_id, str) or not SUPPLIER_ID.match(supplier_id):
        raise _invalid("supplier_id: must look like S001")
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise _invalid(f"lines: between 1 and {MAX_LINES} lines are required")
    clean: list[dict[str, Any]] = []
    for n, line in enumerate(lines, start=1):
        if not isinstance(line, dict) or set(line) != {"product_id", "quantity"}:
            raise _invalid(f"lines[{n}]: needs exactly product_id and quantity")
        product, quantity = line["product_id"], line["quantity"]
        if not isinstance(product, str) or not PRODUCT_ID.match(product):
            raise _invalid(f"lines[{n}].product_id: must look like P001")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise _invalid(f"lines[{n}].quantity: must be a whole number")
        if not 1 <= quantity <= MAX_QUANTITY:
            raise _invalid(f"lines[{n}].quantity: must be between 1 and {MAX_QUANTITY:,}")
        clean.append({"product_id": product, "quantity": quantity})
    products = [line["product_id"] for line in clean]
    if len(set(products)) != len(products):
        raise _invalid("lines: the same product appears twice")
    return {"supplier_id": supplier_id, "lines": sorted(clean, key=lambda line: line["product_id"])}


def check_origin(origin: str, recommendation_id: uuid.UUID | None) -> None:
    if origin not in ORIGINS:
        raise _invalid("origin: must be recommendation or assistant")
    if (origin == "recommendation") != (recommendation_id is not None):
        raise _invalid("recommendation_id: required for a rule-built proposal, only for one")


def _live_proposal(session: Session, products: list[str]) -> uuid.UUID | None:
    return session.scalar(
        select(ProposalLiveProduct.proposal_id).where(ProposalLiveProduct.product_id.in_(products))
    )


def _pending(proposal_id: uuid.UUID) -> ProposalRefused:
    return ProposalRefused(
        "PROPOSAL_PENDING",
        "a proposal for this product is already awaiting approval or uncertain",
        proposal_id,
    )


def create_proposal(
    session: Session,
    *,
    supplier_id: str,
    lines: list[dict[str, Any]],
    origin: str,
    recommendation_id: uuid.UUID | None = None,
) -> Proposal:
    """Create one immutable `create_purchase_order` proposal awaiting approval.

    Guarantees: the fingerprint is SHA-256 of the arguments' RFC 8785 canonical JSON; the same
    supplier and lines give the same arguments and fingerprint; a product with a live proposal is
    refused with PROPOSAL_PENDING (the database enforces it too); no HTTP request is made. The
    caller commits. On ProposalRefused nothing has been written."""
    check_origin(origin, recommendation_id)
    arguments = build_arguments(supplier_id, lines)
    products = [line["product_id"] for line in arguments["lines"]]
    live = _live_proposal(session, products)
    if live is not None:
        raise _pending(live)
    proposal = Proposal(
        id=uuid.uuid4(),
        action="create_purchase_order",
        origin=origin,
        recommendation_id=recommendation_id,
        supplier_id=arguments["supplier_id"],
        arguments=arguments,
        arguments_canonical=canonical(arguments),
        arguments_sha256=fingerprint(arguments),
        status="awaiting_approval",
        created_at=now_utc(),
    )
    try:
        with session.begin_nested():
            session.add(proposal)
            session.flush()
            session.add_all(
                ProposalLine(
                    proposal_id=proposal.id,
                    product_id=line["product_id"],
                    line_no=n,
                    quantity=line["quantity"],
                )
                for n, line in enumerate(arguments["lines"], start=1)
            )
            session.flush()  # the lock trigger runs here
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "proposal_live_product_pkey":
            raise _pending(_live_proposal(session, products)) from None
        raise
    return proposal


def propose_from_recommendation(session: Session, recommendation_id: uuid.UUID) -> Proposal:
    """The rule-built proposal (README 4.5 step 1): the recommendation's preferred supplier and its
    order quantity, only from the product's newest recommendation (FR-001, FR-002)."""
    rec = session.get(RiskResult, recommendation_id)
    if rec is None:
        raise ProposalRefused("NOT_FOUND", f"no recommendation {recommendation_id}")
    newest = session.scalar(
        select(RiskResult.id)
        .where(RiskResult.product_id == rec.product_id)
        .order_by(RiskResult.computed_at.desc(), RiskResult.id)
        .limit(1)
    )
    if newest != rec.id:
        raise ProposalRefused("RECOMMENDATION_CHANGED", CHANGED)
    if rec.reason_code is not None:
        raise ProposalRefused(
            "NO_ORDER_RECOMMENDED", REASON_WORDS.get(rec.reason_code, rec.reason_code)
        )
    if not rec.order_qty:
        raise ProposalRefused(
            "NO_ORDER_RECOMMENDED", f"no order is recommended for {rec.product_id}"
        )
    ref = session.get(ProductRef, rec.product_id)
    if ref is None or ref.preferred_supplier_id is None:
        raise ProposalRefused("NO_ORDER_RECOMMENDED", f"{rec.product_id} has no preferred supplier")
    if ref.product_read_at != rec.computed_at:
        # The product was read again after this recommendation (research R-08), so its supplier
        # might no longer be the recommendation's.
        raise ProposalRefused("RECOMMENDATION_CHANGED", CHANGED)
    return create_proposal(
        session,
        supplier_id=ref.preferred_supplier_id,
        lines=[{"product_id": rec.product_id, "quantity": rec.order_qty}],
        origin="recommendation",
        recommendation_id=rec.id,
    )
