"""Risk and the order recommendation (README 4.3, 4.4, 4.7; FR-021 to FR-028; research R-14).

The pure functions hold every rule; `recommend` does the live Canonical reads in the R-14 order
and appends one `risk_result` row with every input, so each number can be checked by hand.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from brain.canonical.client import CanonicalClient, CanonicalNotFound, CanonicalUnavailable
from brain.clock import now_utc
from brain.config import Settings
from brain.models import ProductRef, RiskResult

LEVELS = ("low", "medium", "high")
COVER_MAX = 99_999_999.99  # the column's limit; cover this long is effectively unlimited

Outcome = Literal["computed", "kept"]


def days_of_cover(available: float, forecast: list[float]) -> float | None:
    """FR-022a: walk the forecast from today; the day the stock runs out adds the covered
    fraction. Stock left after the last forecast day is divided by the forecast's daily mean.
    An all-zero forecast means unlimited cover (None)."""
    if not forecast or not any(f > 0 for f in forecast):
        return None
    stock = max(float(available), 0.0)
    days = 0.0
    for f in forecast:
        if stock >= f:
            stock -= f
            days += 1
        else:
            return days + stock / f
    return days + stock / (sum(forecast) / len(forecast))


def risk_level(cover: float | None, lead: int | None) -> str | None:
    """FR-022: high if cover < lead, medium if cover < lead + 2, else low. No lead time, no level;
    unlimited cover is low."""
    if lead is None:
        return None
    if cover is None:
        return "low"
    if cover < lead:
        return "high"
    if cover < lead + 2:
        return "medium"
    return "low"


def raise_level(level: str) -> str:
    """FR-021: a spike on the day checked raises one level, never above high."""
    return LEVELS[min(LEVELS.index(level) + 1, len(LEVELS) - 1)]


def safety_stock(sd: float, mean: float, lead: int, z: float, days: int) -> int:
    """FR-023: ceil(z × sd × √lead); with fewer than 2 days (no sd), one day of mean demand."""
    if days < 2:
        return math.ceil(mean)
    return math.ceil(z * sd * math.sqrt(lead))


def forecast_over(forecast: list[float], days: int) -> float:
    """FR-023: the forecast summed over `days` days from today; days past the forecast use its
    daily mean."""
    if days <= 0 or not forecast:
        return 0.0
    covered = forecast[:days]
    extra = days - len(covered)
    return float(sum(covered)) + extra * (sum(forecast) / len(forecast))


@dataclass(frozen=True)
class Quantity:
    target: int
    raw: int
    order: int


def order_quantity(
    fol: float,
    ss: int,
    available: int,
    open_po: int,
    pack: int | None,
    maximum: int | None,
    default_pack: int = 1,
) -> Quantity:
    """README 4.4: target = ceil(forecast over lead + safety stock); raw = target − available −
    open orders; order 0 if raw ≤ 0, else raw rounded up to the pack and capped at the maximum."""
    target = math.ceil(fol + ss)
    raw = target - available - open_po
    if raw <= 0:
        return Quantity(target, raw, 0)
    pack = pack or default_pack
    order = math.ceil(raw / pack) * pack
    if maximum is not None:
        order = min(order, maximum)
    return Quantity(target, raw, order)


# ---------------------------------------------------------------- live reads (R-14)


def _dec(value: float | None, places: str) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal(places))


def recommend(
    session: Session,
    client: CanonicalClient,
    *,
    product_id: str,
    forecast: list[float],
    spike: bool,
    sd_28: float,
    mean_28: float,
    window_days: int,
    run_id: int,
    forecast_run_id: int,
    settings: Settings,
) -> Outcome:
    """One product's risk and recommendation. Returns "kept" if the product or its stock can't be
    read (the previous result stays the newest), else appends a `risk_result` and returns
    "computed"."""
    # 1. The product and its stock.
    try:
        product = client.product(product_id)
        stock = client.inventory(product_id)
    except (CanonicalUnavailable, CanonicalNotFound):
        return "kept"
    now = now_utc()
    ref = session.get(ProductRef, product_id)
    if ref is None:
        ref = ProductRef(product_id=product_id, name=product.name, product_read_at=now)
        session.add(ref)
    ref.name = product.name
    ref.preferred_supplier_id = product.preferred_supplier_id
    ref.pack_multiple = product.pack_multiple
    ref.max_order_qty = product.max_order_qty
    ref.product_read_at = now

    # 2. The preferred supplier only (FR-024); failing → NO_SUPPLIER (FR-026).
    reason: str | None = None
    lead: int | None = None
    try:
        if product.preferred_supplier_id is None:
            raise CanonicalNotFound("no preferred supplier")
        supplier = client.supplier(product.preferred_supplier_id)
        lead = supplier.lead_time_days
        ref.supplier_name = supplier.name
        ref.lead_time_days = supplier.lead_time_days
        ref.supplier_read_at = now
    except (CanonicalUnavailable, CanonicalNotFound):
        reason = "NO_SUPPLIER"
        lead = ref.lead_time_days if ref.supplier_read_at is not None else None
    if lead is None and reason is None:
        reason = "NO_SUPPLIER"  # a supplier without a lead time can't be planned for

    # 3-4. Days of cover and risk, raised one level for a spike on the day checked.
    cover = days_of_cover(stock.available, forecast)
    base = risk_level(cover, lead)
    risk = raise_level(base) if (base is not None and spike) else base

    # 5. Open purchase orders, live (FR-025).
    open_po: int | None = None
    if reason is None:
        try:
            open_po = client.open_purchase_orders(product_id)
        except (CanonicalUnavailable, CanonicalNotFound):
            reason = "OPEN_PO_UNAVAILABLE"

    # 6. The quantity.
    review = settings.review_period_days
    fol = ss = None
    quantity: Quantity | None = None
    if lead is not None:
        fol = round(forecast_over(forecast, lead + review), 4)  # as stored, so it recomputes
        ss = safety_stock(sd_28, mean_28, lead, settings.safety_z, window_days)
    if reason is None and fol is not None and ss is not None and open_po is not None:
        quantity = order_quantity(
            fol,
            ss,
            stock.available,
            open_po,
            product.pack_multiple,
            product.max_order_qty,
            settings.default_pack_multiple,
        )

    # 7. One new row with every input (FR-028).
    session.add(
        RiskResult(
            product_id=product_id,
            job_run_id=run_id,
            forecast_run_id=forecast_run_id,
            computed_at=now,
            available=stock.available,
            lead_time_days=lead,
            days_of_cover=_dec(None if cover is None else min(cover, COVER_MAX), "0.01"),
            base_risk=base,
            risk=risk,
            raised_by_spike=bool(spike and base is not None),
            open_po_qty=open_po,
            forecast_over_lead=_dec(fol, "0.0001"),
            review_period_days=review,
            safety_stock=ss,
            sd_28=Decimal(str(sd_28)),
            mean_28=Decimal(str(mean_28)),
            target=quantity.target if quantity else None,
            raw=quantity.raw if quantity else None,
            pack_multiple=product.pack_multiple or settings.default_pack_multiple,
            max_order_qty=product.max_order_qty,
            order_qty=quantity.order if quantity else None,
            reason_code=reason,
        )
    )
    return "computed"
