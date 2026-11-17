"""Simulate Sales (FR-011, FR-012, FR-023; research R-15 and R-16).

Adds a realistic batch to today's daily totals only, moves stock by the net units added, and never
lets stock fall below 0. An optional spike pushes one product's net units for today to at least
ceil(mean28 + z x sd28) of its last 28 closed days (a no-sale day counting as 0), capped by
stock.
"""

import math
import random
import statistics
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.clock import now_utc, today_cairo
from erp.config import Settings
from erp.errors import ErpError
from erp.models import DailySales, Product
from erp.schemas.simulate import ProductBatch, SimulateResult, SpikeResult
from erp.services import stock
from erp.services.day_close import close_past_days
from erp.services.sampling import binomial, poisson

HISTORY_DAYS = 28  # the Brain's look-back window (README Section 4.7)

__all__ = [
    "HISTORY_DAYS",
    "SpikeNeedsHistory",
    "baseline",
    "binomial",
    "closed_history",
    "poisson",
    "run_simulation",
    "spike_target",
]


class SpikeNeedsHistory(ErpError):
    """A spike needs 28 closed days: the Brain can't check anomalies on a younger product."""

    def __init__(self, have: int, product_id: str | None = None) -> None:
        who = f"Product {product_id}" if product_id else "This product"
        super().__init__(
            422,
            "SPIKE_NEEDS_HISTORY",
            f"{who} has {have} closed days of sales; a spike needs {HISTORY_DAYS}, "
            "because the Brain can't check anomalies on a younger product yet",
        )
        self.have = have


def closed_history(
    session: Session, product_id: str, today: date, days: int = HISTORY_DAYS
) -> list[int]:
    """Net units of the product's last `days` closed days before today, oldest first.

    These are calendar days: a closed day with no sales row counts as 0 (Simulate Sales writes no
    row for a product that sold nothing), exactly as the Brain counts it (feature 003, research
    R-13). A product whose first sales row is fewer than `days` days ago gets only the days since
    that row, so a young product still can't be spiked.
    """
    first = session.scalar(
        select(func.min(DailySales.business_date)).where(DailySales.product_id == product_id)
    )
    if first is None or first >= today:
        return []
    start = max(first, today - timedelta(days=days))
    rows = session.execute(
        select(DailySales.business_date, DailySales.net_units).where(
            DailySales.product_id == product_id,
            DailySales.day_status == "closed",
            DailySales.business_date >= start,
            DailySales.business_date < today,
        )
    ).all()
    by_day = {day: net for day, net in rows}
    return [by_day.get(start + timedelta(days=i), 0) for i in range((today - start).days)]


def baseline(values: list[int]) -> float:
    """The product's normal daily level: the mean of its history, never below 1."""
    if not values:
        return 1.0
    return max(1.0, statistics.mean(values))


def spike_target(values: list[int], z: float) -> int:
    """ceil(mean + z x sample sd). An all-equal history uses sd = 1 so the spike is still a jump."""
    if len(values) < HISTORY_DAYS:
        raise SpikeNeedsHistory(len(values))
    sd = statistics.stdev(values) or 1
    return math.ceil(statistics.mean(values) + z * sd)


def run_simulation(
    session: Session, settings: Settings, spike_product_id: str | None, rng: random.Random
) -> SimulateResult:
    close_past_days(session)
    today = today_cairo()

    # Check the spike product first: nothing is written unless it can be honoured.
    target: int | None = None
    if spike_product_id is not None:
        if session.get(Product, spike_product_id) is None:
            raise ErpError(404, "NOT_FOUND", f"Product {spike_product_id} not found")
        history = closed_history(session, spike_product_id, today)
        try:
            target = spike_target(history, settings.erp_spike_z)
        except SpikeNeedsHistory as short:
            raise SpikeNeedsHistory(short.have, spike_product_id) from None

    batches: list[ProductBatch] = []
    spike: SpikeResult | None = None

    for product_id in session.scalars(select(Product.product_id).order_by(Product.product_id)):
        on_hand = stock.lock_stock(session, product_id).on_hand
        today_row = session.get(DailySales, (product_id, today))
        current_net = (
            today_row.units_sold - today_row.units_returned if today_row is not None else 0
        )

        mean = baseline(closed_history(session, product_id, today))
        sold = poisson(rng, mean * settings.erp_simulate_batch_fraction)
        returned = binomial(rng, sold, settings.erp_simulate_return_rate)

        # Stock can't cover the batch: cut the units sold until net units fit (FR-023).
        capped = False
        if sold - returned > on_hand:
            capped = True
            sold = returned + on_hand
            if sold == returned:  # nothing at all could be sold: no sale and no return
                sold = returned = 0

        if product_id == spike_product_id and target is not None:
            extra = max(0, target - (current_net + sold - returned))
            added = min(extra, on_hand - (sold - returned))
            sold += added
            spike_capped = added < extra
            capped = capped or spike_capped
            spike = SpikeResult(
                product_id=product_id,
                target_net_units=target,
                achieved_net_units=current_net + sold - returned,
                capped_by_stock=spike_capped,
            )

        if sold or returned:
            if today_row is None:
                today_row = DailySales(
                    product_id=product_id,
                    business_date=today,
                    units_sold=0,
                    units_returned=0,
                    day_status="open",
                )
                session.add(today_row)
            today_row.units_sold += sold
            today_row.units_returned += returned
            today_row.updated_at = now_utc()
            session.flush()
            stock.apply_net_change(session, product_id, sold - returned)

        if sold or returned or capped:
            batches.append(
                ProductBatch(
                    product_id=product_id,
                    units_sold_added=sold,
                    units_returned_added=returned,
                    capped_by_stock=capped,
                )
            )

    return SimulateResult(business_date=today, products=batches, spike=spike)
