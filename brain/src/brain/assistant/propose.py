"""The chat agent's one write tool, propose_purchase_order (research R-08; FR-006 to FR-008).

It only creates a proposal through feature 004's create function, with origin "assistant"; the
proposal then goes through approval, rejection and Send again exactly like a rule-built one. It
never approves, sends or calls the ERP (Principle V). Code, not the model, decides:

1. every product must be known;
2. every product must have a recommendation;
3. all products must share one preferred supplier: the supplier is always that one (README 4.4);
4. without a quantity, each line takes its newest recommended order (refused if 0 or a reason
   code);
5. a quantity must appear in the manager's newest message or equal the recommendation (FR-007):
   a number the model made up, or one written inside data (FR-019), is refused;
6. at most one proposal per turn;
7. feature 004's own refusals (a live proposal, invalid arguments) are passed on with a link.

The proposal is flushed in the turn's transaction; the chat endpoint commits at the end of the turn.
"""

import re
from typing import Any

from sqlalchemy import select

from brain.assistant.grounding import Allowed, ids_in
from brain.models import ProductRef, RiskResult
from brain.proposals.service import REASON_WORDS, ProposalRefused, create_proposal

PRODUCT_ID = re.compile(r"^P[0-9]{3,}$")


def _path(proposal_id: Any) -> str:
    return f"/brain/proposals/{proposal_id}"


def _refuse(ctx: Any, code: str, detail: str, live_id: Any = None) -> dict[str, Any]:
    refusal = {
        "code": code,
        "detail": detail,
        "live_proposal_id": str(live_id) if live_id else None,
        "path": _path(live_id) if live_id else None,
    }
    ctx.refusal = refusal
    return {"refused": code, **{k: v for k, v in refusal.items() if k != "code"}}


def _newest(ctx: Any, product_id: str) -> RiskResult | None:
    return ctx.session.scalars(
        select(RiskResult)
        .where(RiskResult.product_id == product_id)
        .order_by(RiskResult.computed_at.desc(), RiskResult.id)
        .limit(1)
    ).first()


def _conversation_product(ctx: Any) -> str | None:
    """The product the manager named most recently (newest message first)."""
    for text in reversed(ctx.manager_texts or [ctx.manager_text]):
        found = [i for i in ids_in(text) if i.startswith("P")]
        if found:
            # the last one written in that message
            return max(found, key=lambda i: text.rfind(i))
    return None


def propose(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    product_ids = args.get("product_ids")
    quantity = args.get("quantity")
    # A follow-up that gives only a quantity ("25") names no product: the product comes from the
    # conversation, also when the model lost it or sent one nobody named (live, 2026-11-19).
    newest_names_one = any(i.startswith("P") for i in ids_in(ctx.manager_text))
    if not product_ids:
        product = _conversation_product(ctx)
        if product is None:
            return _refuse(ctx, "VALIDATION_ERROR", "which product? name the product to order")
        product_ids = [product]
    elif (
        quantity is not None
        and isinstance(product_ids, list)
        and len(product_ids) == 1
        and not newest_names_one
        and isinstance(product_ids[0], str)
        and ctx.session.get(ProductRef, product_ids[0]) is None
    ):
        product = _conversation_product(ctx)
        if product is not None:
            product_ids = [product]
    if (
        not isinstance(product_ids, list)
        or not 1 <= len(product_ids) <= 10
        or not all(isinstance(p, str) and PRODUCT_ID.match(p) for p in product_ids)
        or len(set(product_ids)) != len(product_ids)
    ):
        return _refuse(ctx, "VALIDATION_ERROR", "product_ids: 1 to 10 different IDs like P003")
    if isinstance(quantity, float) and quantity.is_integer():
        quantity = int(quantity)
    if quantity is not None and (
        isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1
    ):
        return _refuse(ctx, "VALIDATION_ERROR", "quantity: a whole number of at least 1")
    if quantity is not None and len(product_ids) != 1:
        return _refuse(ctx, "VALIDATION_ERROR", "quantity: give it for one product at a time")

    # 1. known products
    refs: list[ProductRef] = []
    for product_id in product_ids:
        ref = ctx.session.get(ProductRef, product_id)
        if ref is None:
            return _refuse(ctx, "UNKNOWN_PRODUCT", f"{product_id} is not a known product")
        refs.append(ref)
    # 2. a recommendation for each
    recs: dict[str, RiskResult] = {}
    for ref in refs:
        rec = _newest(ctx, ref.product_id)
        if rec is None:
            return _refuse(ctx, "NO_RESULTS", f"{ref.product_id} has no recommendation yet")
        recs[ref.product_id] = rec
    # 3. one preferred supplier
    for ref in refs:
        if ref.preferred_supplier_id is None:
            return _refuse(
                ctx, "NO_RECOMMENDED_QUANTITY", f"{ref.product_id}: {REASON_WORDS['NO_SUPPLIER']}"
            )
    suppliers = {ref.preferred_supplier_id for ref in refs}
    if len(suppliers) != 1:
        return _refuse(
            ctx,
            "DIFFERENT_SUPPLIERS",
            "these products come from different preferred suppliers; ask for one order per supplier",
        )
    supplier_id = suppliers.pop()

    lines: list[dict[str, Any]] = []
    for ref in refs:
        rec = recs[ref.product_id]
        if quantity is None:
            # 4. the recommended quantity
            if rec.reason_code is not None:
                return _refuse(
                    ctx,
                    "NO_RECOMMENDED_QUANTITY",
                    f"{ref.product_id}: {REASON_WORDS.get(rec.reason_code, rec.reason_code)}",
                )
            if not rec.order_qty:
                return _refuse(
                    ctx,
                    "NO_RECOMMENDED_QUANTITY",
                    f"no order is recommended for {ref.product_id}; give a quantity to order anyway",
                )
            lines.append({"product_id": ref.product_id, "quantity": rec.order_qty})
        else:
            # 5. the manager's number, or the recommendation
            written = Allowed.from_facts([], extra_texts=[ctx.manager_text]).numbers
            if quantity != rec.order_qty and not any(n == quantity for n in written):
                return _refuse(
                    ctx,
                    "QUANTITY_NOT_GIVEN",
                    f"{quantity} is neither the quantity you asked for nor the recommended order",
                )
            lines.append({"product_id": ref.product_id, "quantity": quantity})

    # 6. one proposal per turn
    if ctx.proposals_created >= 1:
        return _refuse(ctx, "VALIDATION_ERROR", "only one proposal can be created per message")

    # 7. feature 004's create function, unchanged
    try:
        proposal = create_proposal(
            ctx.session, supplier_id=supplier_id, lines=lines, origin="assistant"
        )
    except ProposalRefused as exc:
        return _refuse(ctx, exc.code, exc.detail, exc.proposal_id)

    names = {ref.product_id: ref.name for ref in refs}
    supplier_name = refs[0].supplier_name or supplier_id
    card = {
        "id": str(proposal.id),
        "path": _path(proposal.id),
        "status": proposal.status,
        "origin": proposal.origin,
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "lines": [
            {
                "product_id": line["product_id"],
                "product_name": names[line["product_id"]],
                "quantity": line["quantity"],
            }
            for line in proposal.arguments["lines"]
        ],
    }
    ctx.proposals_created += 1
    ctx.proposal = card
    return {"proposal_id": card["id"], **{k: v for k, v in card.items() if k != "id"}}
