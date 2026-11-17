"""GET /purchase-orders (open orders, US3) and POST /purchase-orders (a draft, US4).

Open means draft, the ERP's only status before the manager confirms (FR-023). The list is read
live inside the request's transaction (FR-025).

The POST runs its steps in this order (research R-10), so a used key with a different body is
always 409, as constitution Principle V and FR-030 require:
1. auth (401/403), before the body is read;
2. read the Idempotency-Key header (missing or not a UUID: 422) and hash the body;
3. lock the key and look it up: same content -> 200 with the stored response, else 409;
4. only for a new key, validate the body (422);
5. create the draft and its idempotency record in one transaction (201).
A refusal at any step stores nothing, so it never uses up a key (FR-032).
"""

import hashlib
import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import exists, select, text

from erp.canonical import cursor as cursors
from erp.canonical.auth import CreateDraftAccess, ReadAccess
from erp.canonical.errors import CanonicalError, field_name, validation_error
from erp.canonical.schemas import (
    CreateDraftPurchaseOrderRequest,
    PurchaseOrderPage,
    to_canonical_order,
)
from erp.canonical.schemas import (
    PurchaseOrder as PurchaseOrderDoc,
)
from erp.db import SessionDep
from erp.ids import PRODUCT_ID_PATTERN
from erp.models import IdempotencyRecord, PurchaseOrder, PurchaseOrderLine
from erp.services import purchase_orders as po_service

router = APIRouter()

_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))")
_NOT_PARSED = object()


async def read_body(
    request: Request, _scopes: Annotated[frozenset[str], CreateDraftAccess]
) -> bytes:
    """Depends on the auth dependency, so the body is read only once auth has passed."""
    return await request.body()


def _request_sha256(raw: bytes) -> tuple[str, Any]:
    """Same content, same hash: sorted keys, no whitespace. A body that isn't JSON is hashed as
    its raw bytes; it can never match a stored hash."""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return hashlib.sha256(raw).hexdigest(), _NOT_PARSED
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), parsed


def _validate(parsed: Any, key: uuid.UUID) -> CreateDraftPurchaseOrderRequest:
    if parsed is _NOT_PARSED:
        raise validation_error("body", "must be a JSON object")
    try:
        body = CreateDraftPurchaseOrderRequest.model_validate(parsed)
    except ValidationError as exc:
        details = [
            {"field": field_name(error["loc"]), "issue": error["msg"]} for error in exc.errors()
        ]
        raise CanonicalError(
            422, "VALIDATION_ERROR", f"{details[0]['field']}: {details[0]['issue']}", details
        ) from None
    if uuid.UUID(body.approval.proposal_id) != key:
        raise validation_error("approval.proposal_id", "must equal the Idempotency-Key header")
    return body


@router.post(
    "/purchase-orders",
    status_code=201,
    response_model=PurchaseOrderDoc,
    responses={200: {"model": PurchaseOrderDoc, "description": "Replay of the original 201"}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": CreateDraftPurchaseOrderRequest.model_json_schema()}
            },
        }
    },
)
def create_draft_purchase_order(
    raw: Annotated[bytes, Depends(read_body)],
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    # A plain def: FastAPI runs it in the thread pool, so concurrent requests really overlap.
    if idempotency_key is None:
        raise validation_error("Idempotency-Key", "the header is required")
    try:
        key = uuid.UUID(idempotency_key)
    except ValueError:
        raise validation_error("Idempotency-Key", "must be a UUID") from None
    request_sha256, parsed = _request_sha256(raw)

    session.execute(_LOCK, {"key": str(key)})
    record = session.get(IdempotencyRecord, key)
    if record is not None:
        if record.request_sha256 == request_sha256:
            return JSONResponse(record.response_body, status_code=200)
        raise CanonicalError(
            409,
            "IDEMPOTENCY_CONFLICT",
            "This Idempotency-Key was already used with a different request body",
        )

    body = _validate(parsed, key)
    po_service.check_references(session, body)
    order = po_service.create_draft(session, body)
    response = to_canonical_order(order).model_dump(mode="json", by_alias=True)
    session.add(
        IdempotencyRecord(
            key=key,
            request_sha256=request_sha256,
            response_status=201,
            response_body=response,
            po_id=order.po_id,
        )
    )
    session.flush()
    return JSONResponse(response, status_code=201)


@router.get("/purchase-orders", response_model=PurchaseOrderPage, dependencies=[ReadAccess])
def list_open_purchase_orders(
    session: SessionDep,
    status: Annotated[Literal["open"], Query(description="Must be `open` (= draft)")],
    product_id: Annotated[str | None, Query(pattern=PRODUCT_ID_PATTERN)] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> PurchaseOrderPage:
    after: int | None = None
    if cursor is not None:
        try:
            after = int(cursors.decode("po", cursor, {"product_id": product_id})["last"])
        except (cursors.InvalidCursor, KeyError, TypeError, ValueError):
            raise validation_error(
                "cursor", "invalid, tampered with, or issued for other filters"
            ) from None

    query = select(PurchaseOrder).where(PurchaseOrder.status == "draft")
    if product_id is not None:
        query = query.where(
            exists().where(
                PurchaseOrderLine.po_id == PurchaseOrder.po_id,
                PurchaseOrderLine.product_id == product_id,
            )
        )
    if after is not None:
        query = query.where(PurchaseOrder.po_id > after)
    orders = list(session.scalars(query.order_by(PurchaseOrder.po_id).limit(limit + 1)))

    next_cursor = None
    if len(orders) > limit:
        orders = orders[:limit]
        next_cursor = cursors.encode("po", {"product_id": product_id, "last": orders[-1].po_id})
    return PurchaseOrderPage(
        items=[to_canonical_order(order) for order in orders], next_cursor=next_cursor
    )
