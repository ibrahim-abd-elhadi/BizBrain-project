"""A fake ERP Canonical API for the Brain's tests (feature 003, T007).

FakeCanonical is an httpx.MockTransport serving the five Canonical GETs from in-memory documents.
Every document and page it serves is validated against feature 002's contract schemas, so the
Brain is tested against the Canonical contract, not against itself.
"""

import base64
import csv
import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "contracts/canonical/schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE_URI = "https://contracts.bizbrain.invalid/schemas/"
TOKEN = "test-service-token"


@lru_cache
def _registry() -> Registry:
    registry: Registry = Registry()
    for path in SCHEMAS.rglob("*.schema.json"):
        resource = Resource.from_contents(
            json.loads(path.read_text(encoding="utf-8")), default_specification=DRAFT202012
        )
        registry = registry.with_resource(BASE_URI + path.relative_to(SCHEMAS).as_posix(), resource)
    return registry


def validate(schema_name: str, document: Any) -> None:
    Draft202012Validator(
        {"$ref": BASE_URI + schema_name}, registry=_registry(), format_checker=FormatChecker()
    ).validate(document)


def z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sales_row(
    product_id: str,
    business_date: date,
    sold: int,
    returned: int = 0,
    status: str = "closed",
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "schema": "canonical.DailySalesTotal",
        "version": "1.0",
        "product_id": product_id,
        "business_date": business_date.isoformat(),
        "units_sold": sold,
        "units_returned": returned,
        "net_units": sold - returned,
        "day_status": status,
        "updated_at": z(updated_at or datetime(2026, 1, 1, tzinfo=UTC)),
    }


def load_seed_rows(today: date, updated_at: datetime) -> list[dict[str, Any]]:
    """The 1,800 seeded totals, re-dated so day 90 is yesterday (day_index 1 = today − 90)."""
    rows = []
    with (FIXTURES / "seed_sales.csv").open(encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            day = today - timedelta(days=91 - int(rec["day_index"]))
            rows.append(
                sales_row(
                    rec["product_id"],
                    day,
                    int(rec["units_sold"]),
                    int(rec["units_returned"]),
                    "closed",
                    updated_at,
                )
            )
    return rows


def load_seed_catalog() -> dict[str, dict[str, dict[str, Any]]]:
    data = json.loads((FIXTURES / "seed_catalog.json").read_text(encoding="utf-8"))
    return {
        "products": {d["product_id"]: d for d in data["products"]},
        "inventory": {d["product_id"]: d for d in data["inventory"]},
        "suppliers": {d["supplier_id"]: d for d in data["suppliers"]},
    }


def purchase_order(po_id: int, supplier_id: str, lines: dict[str, int]) -> dict[str, Any]:
    return {
        "schema": "canonical.PurchaseOrder",
        "version": "1.0",
        "purchase_order_id": po_id,
        "supplier_id": supplier_id,
        "status": "draft",
        "lines": [
            {"product_id": p, "ordered_qty": q, "received_qty": 0, "open_qty": q}
            for p, q in lines.items()
        ],
        "created_by": "human",
        "approval": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _error(status: int, code: str, message: str) -> httpx.Response:
    body = {"error": {"code": code, "message": message, "details": [], "trace_id": "0" * 32}}
    validate("common/error.schema.json", body)
    return httpx.Response(status, json=body)


class FakeCanonical:
    """In-memory Canonical API. `fail[op] = status | "timeout"` makes an operation fail; for
    sales, `fail["sales_page_N"]` fails only the N-th page (1-based) of each poll."""

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self.sales: dict[tuple[str, str], dict[str, Any]] = {}
        self.products: dict[str, dict[str, Any]] = {}
        self.inventory: dict[str, dict[str, Any]] = {}
        self.suppliers: dict[str, dict[str, Any]] = {}
        self.open_orders: list[dict[str, Any]] = []
        self.fail: dict[str, int | str] = {}
        self.requests: list[httpx.Request] = []
        self._now = now or (lambda: datetime.now(UTC))
        self._sales_page_count = 0
        # Draft POs (feature 004): idempotency records by key, and every POST received.
        self.idempotency: dict[str, tuple[str, dict[str, Any]]] = {}
        self.posts: list[httpx.Request] = []
        self._po_lock = threading.Lock()
        self._next_po = 1001

    # ---- set-up helpers
    def load_seed(self, today: date, updated_at: datetime) -> "FakeCanonical":
        for row in load_seed_rows(today, updated_at):
            self.put_sales(row)
        catalog = load_seed_catalog()
        self.products.update(catalog["products"])
        self.inventory.update(catalog["inventory"])
        self.suppliers.update(catalog["suppliers"])
        return self

    def put_sales(self, row: dict[str, Any]) -> None:
        validate("canonical/daily_sales_total.schema.json", row)
        self.sales[(row["product_id"], row["business_date"])] = row

    def remove_sales(self, product_id: str, business_date: date) -> None:
        self.sales.pop((product_id, business_date.isoformat()), None)

    def set_stock(self, product_id: str, on_hand: int) -> None:
        doc = dict(self.inventory[product_id], on_hand=on_hand, available=on_hand)
        doc["updated_at"] = z(self._now())
        self.inventory[product_id] = doc

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport(), base_url="http://erp.test")

    def sales_queries(self) -> list[dict[str, str]]:
        return [
            dict(r.url.params) for r in self.requests if r.url.path.endswith("/canonical/sales")
        ]

    def new_poll(self) -> None:
        self._sales_page_count = 0

    def drafts(self) -> list[dict[str, Any]]:
        """The draft orders this fake created through the POST."""
        return [o for o in self.open_orders if o.get("created_by") == "agent"]

    def post_requests(self) -> list[dict[str, Any]]:
        """Every draft-PO request received: its raw body and headers."""
        return [{"body": r.content, "headers": dict(r.headers)} for r in self.posts]

    # ---- request handling
    def _failure(self, op: str) -> httpx.Response | None:
        status = self.fail.get(op)
        if status is None:
            return None
        if status == "timeout":
            raise httpx.ReadTimeout("fake timeout")
        return _error(int(status), "DEPENDENCY_UNAVAILABLE", f"fake failure of {op}")

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return _error(401, "UNAUTHORIZED", "A valid service token is required")
        path = request.url.path.removeprefix("/api/v1/canonical")
        if request.method == "POST" and path == "/purchase-orders":
            return self._create_po(request)
        if path == "/sales":
            return self._sales(request)
        for prefix, store, op, schema in (
            ("/products/", self.products, "product", "canonical/product.schema.json"),
            ("/inventory/", self.inventory, "inventory", "canonical/inventory_item.schema.json"),
            ("/suppliers/", self.suppliers, "supplier", "canonical/supplier.schema.json"),
        ):
            if path.startswith(prefix):
                failed = self._failure(op)
                if failed is not None:
                    return failed
                doc = store.get(path.removeprefix(prefix))
                if doc is None:
                    return _error(404, "NOT_FOUND", "not found")
                validate(schema, doc)
                return httpx.Response(200, json=doc)
        if path == "/purchase-orders":
            failed = self._failure("purchase_orders")
            if failed is not None:
                return failed
            product_id = request.url.params.get("product_id")
            items = [
                o
                for o in self.open_orders
                if product_id is None or any(l["product_id"] == product_id for l in o["lines"])
            ]
            page = {
                "schema": "canonical.PurchaseOrderPage",
                "version": "1.0",
                "items": items,
                "next_cursor": None,
            }
            validate("canonical/purchase_order_page.schema.json", page)
            return httpx.Response(200, json=page)
        return _error(404, "NOT_FOUND", "unknown path")

    def _create_po(self, request: httpx.Request) -> httpx.Response:
        """Feature 002's draft-PO rules: auth, key, content hash, lock and lookup, validate,
        create. `fail["create_po"]` can be a status, "timeout", "timeout_after_commit" or
        "garbage_2xx"."""
        self.posts.append(request)
        mode = self.fail.get("create_po")
        if mode == "timeout":
            raise httpx.ReadTimeout("fake timeout before commit")
        if isinstance(mode, int):
            codes = {
                401: "UNAUTHORIZED",
                403: "FORBIDDEN",
                409: "IDEMPOTENCY_CONFLICT",
                422: "VALIDATION_ERROR",
            }
            return _error(mode, codes.get(mode, "INTERNAL_ERROR"), f"fake {mode}")
        key = request.headers.get("idempotency-key", "")
        try:
            uuid.UUID(key)
        except ValueError:
            return _error(422, "VALIDATION_ERROR", "Idempotency-Key must be a UUID")
        try:
            parsed = json.loads(request.content)
            content = hashlib.sha256(
                json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        except ValueError:
            return _error(422, "VALIDATION_ERROR", "body: must be JSON")
        with self._po_lock:
            known = self.idempotency.get(key)
            if known is not None:
                if known[0] != content:
                    return _error(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "This Idempotency-Key was already used with a different request body",
                    )
                return self._answer(200, known[1], mode)
            try:
                validate("canonical/create_draft_po_request.schema.json", parsed)
            except Exception as exc:  # noqa: BLE001
                return _error(422, "VALIDATION_ERROR", f"body: {str(exc).splitlines()[0]}")
            if parsed["approval"]["proposal_id"] != key:
                return _error(
                    422, "VALIDATION_ERROR", "approval.proposal_id must equal the Idempotency-Key"
                )
            stamp = z(self._now())
            order = {
                "schema": "canonical.PurchaseOrder",
                "version": "1.0",
                "purchase_order_id": self._next_po,
                "supplier_id": parsed["supplier_id"],
                "status": "draft",
                "lines": [
                    {
                        "product_id": line["product_id"],
                        "ordered_qty": line["quantity"],
                        "received_qty": 0,
                        "open_qty": line["quantity"],
                    }
                    for line in parsed["lines"]
                ],
                "created_by": "agent",
                "approval": parsed["approval"],
                "created_at": stamp,
                "updated_at": stamp,
            }
            validate("canonical/purchase_order.schema.json", order)
            self._next_po += 1
            self.open_orders.append(order)
            self.idempotency[key] = (content, order)
        if mode == "timeout_after_commit":
            raise httpx.ReadTimeout("fake timeout after commit")
        return self._answer(201, order, mode)

    @staticmethod
    def _answer(status: int, order: dict[str, Any], mode: Any) -> httpx.Response:
        if mode == "garbage_2xx":
            return httpx.Response(status, content=b"<html>not json</html>")
        return httpx.Response(status, json=order)

    def _sales(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if "cursor" not in params:
            self._sales_page_count = 0
        self._sales_page_count += 1
        failed = self._failure("sales") or self._failure(f"sales_page_{self._sales_page_count}")
        if failed is not None:
            return failed
        lo, hi = params["from"], params["to"]
        since = params.get("updated_since")
        since_dt = datetime.fromisoformat(since) if since else None
        rows = sorted(
            (
                r
                for r in self.sales.values()
                if lo <= r["business_date"] <= hi
                and (since_dt is None or datetime.fromisoformat(r["updated_at"]) > since_dt)
            ),
            key=lambda r: (r["updated_at"], r["product_id"], r["business_date"]),
        )
        limit = int(params.get("limit", 200))
        if "cursor" in params:
            state = json.loads(base64.urlsafe_b64decode(params["cursor"]))
            offset, watermark = state["o"], state["w"]
        else:
            offset, watermark = 0, z(self._now())
        chunk = rows[offset : offset + limit]
        more = offset + limit < len(rows)
        cursor = (
            base64.urlsafe_b64encode(
                json.dumps({"o": offset + limit, "w": watermark}).encode()
            ).decode()
            if more
            else None
        )
        page = {
            "schema": "canonical.SalesPage",
            "version": "1.0",
            "items": chunk,
            "next_cursor": cursor,
            "high_watermark": watermark,
        }
        validate("canonical/sales_page.schema.json", page)
        return httpx.Response(200, json=page)
