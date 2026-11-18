"""Risk and the order recommendation (US3 scenarios 1-10; SC-006 to SC-008; research R-14), on the
seed fixture through the fake Canonical API. Written before the implementation.

Every quantity is recomputed here from the inputs stored on its row (FR-028), with plain
arithmetic rather than the Brain's own functions.
"""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import func, select

from brain.clock import today_cairo

from fakes import FakeCanonical, purchase_order, sales_row
from series import seed_date, spike_target

LOW_STOCK = {"P003", "P011", "P017"}
LEVELS = ["low", "medium", "high"]


@pytest.fixture
def fake(pg, monkeypatch) -> FakeCanonical:
    fake = FakeCanonical()
    fake.load_seed(today_cairo(), datetime.now(UTC) - timedelta(hours=2))
    monkeypatch.setattr("brain.canonical.client.TEST_TRANSPORT", fake.transport())
    return fake


def _run(job: str) -> int:
    from brain.jobs.registry import run_job

    return run_job(job, trigger="manual")


def _latest_run(session, job: str):
    from brain.models import JobRun

    session.expire_all()
    return session.scalars(
        select(JobRun).where(JobRun.job == job).order_by(JobRun.id.desc())
    ).first()


def _newest(session) -> dict:
    from brain.models import RiskResult

    session.expire_all()
    rows = session.scalars(select(RiskResult).order_by(RiskResult.computed_at, RiskResult.id))
    return {r.product_id: r for r in rows}  # the last one per product wins


def _all_results(session, run_id: int) -> dict:
    from brain.models import RiskResult

    session.expire_all()
    return {
        r.product_id: r
        for r in session.scalars(select(RiskResult).where(RiskResult.job_run_id == run_id))
    }


def _forecast(session, run_id: int, product: str, today: date) -> list[float]:
    from brain.models import Forecast

    rows = session.scalars(
        select(Forecast)
        .where(
            Forecast.job_run_id == run_id,
            Forecast.product_id == product,
            Forecast.target_date >= today,
        )
        .order_by(Forecast.target_date)
    )
    return [float(f.yhat) for f in rows]


def _cover_by_hand(available: int, forecast: list[float]) -> float | None:
    stock = float(available)
    days = 0.0
    for f in forecast:
        if stock >= f:
            stock -= f
            days += 1
        else:
            return days + stock / f
    mean = sum(forecast) / len(forecast)
    return None if mean == 0 else days + stock / mean


def _level_by_hand(cover: float | None, lead: int) -> str:
    if cover is None:
        return "low"
    return "high" if cover < lead else "medium" if cover < lead + 2 else "low"


def _check_by_hand(session, row, today: date) -> None:
    """Recompute every number on a risk_result row from its stored inputs (SC-006)."""
    forecast = _forecast(session, row.forecast_run_id, row.product_id, today)
    cover = _cover_by_hand(row.available, forecast)
    if cover is None:
        assert row.days_of_cover is None
    else:
        assert float(row.days_of_cover) == pytest.approx(cover, abs=0.01)
    lead = row.lead_time_days
    assert row.base_risk == _level_by_hand(cover, lead)
    expected = (
        LEVELS[min(LEVELS.index(row.base_risk) + 1, 2)] if row.raised_by_spike else row.base_risk
    )
    assert row.risk == expected

    days = lead + row.review_period_days
    mean14 = sum(forecast) / len(forecast)
    fol = sum(forecast[:days]) + max(days - len(forecast), 0) * mean14
    assert float(row.forecast_over_lead) == pytest.approx(fol, abs=0.001)
    sd, mean = float(row.sd_28), float(row.mean_28)
    ss = math.ceil(1.65 * sd * math.sqrt(lead)) if sd > 0 else math.ceil(mean)
    assert row.safety_stock == ss
    target = math.ceil(float(row.forecast_over_lead) + ss)
    raw = target - row.available - row.open_po_qty
    order = 0 if raw <= 0 else math.ceil(raw / row.pack_multiple) * row.pack_multiple
    if row.max_order_qty is not None:
        order = min(order, row.max_order_qty)
    assert (row.target, row.raw, row.order_qty) == (target, raw, order)
    assert row.reason_code is None


# ---------------------------------------------------------------- the first night


def test_the_first_night_sets_risk_and_a_quantity_for_every_product(fake, worker_session) -> None:
    from brain.models import ProductRef

    assert _run("end-of-day") == 0
    run = _latest_run(worker_session, "end-of-day")
    results = _all_results(worker_session, run.id)
    assert len(results) == 20
    today = today_cairo()
    for product, row in results.items():
        assert row.forecast_run_id == run.id
        assert row.risk == ("high" if product in LOW_STOCK else "low"), product
        _check_by_hand(worker_session, row, today)
    for product in LOW_STOCK:
        assert results[product].order_qty > 0
    assert run.summary["risk_computed"] == 20 and run.summary["risk_kept"] == 0

    refs = {r.product_id: r for r in worker_session.scalars(select(ProductRef))}
    assert len(refs) == 20
    p003 = refs["P003"]
    assert (p003.name, p003.preferred_supplier_id, p003.pack_multiple, p003.max_order_qty) == (
        "Amoxicillin 500 mg capsules",
        "S004",
        12,
        240,
    )
    assert (p003.supplier_name, p003.lead_time_days) == ("Delta Health Trading", 7)
    assert p003.product_read_at is not None and p003.supplier_read_at is not None


def test_a_draft_order_lowers_the_quantity(fake, worker_session) -> None:
    assert _run("end-of-day") == 0
    before = _newest(worker_session)["P003"]
    assert before.open_po_qty == 0
    fake.open_orders.append(purchase_order(1, "S004", {"P003": 24}))
    assert _run("end-of-day") == 0
    after = _newest(worker_session)["P003"]
    assert after.id != before.id and after.open_po_qty == 24
    assert after.raw == before.raw - 24
    _check_by_hand(worker_session, after, today_cairo())
    assert after.order_qty < before.order_qty


# ---------------------------------------------------------------- failed reads


def test_open_orders_unavailable_gives_no_quantity_for_every_product(fake, worker_session) -> None:
    fake.fail["purchase_orders"] = 503
    assert _run("end-of-day") == 0
    results = _all_results(worker_session, _latest_run(worker_session, "end-of-day").id)
    assert len(results) == 20
    for product, row in results.items():
        assert row.reason_code == "OPEN_PO_UNAVAILABLE" and row.order_qty is None
        assert row.open_po_qty is None and row.target is None and row.raw is None
        assert row.risk == ("high" if product in LOW_STOCK else "low")  # risk still set


def test_supplier_unavailable_gives_no_supplier(fake, worker_session) -> None:
    # No earlier supplier read: no lead time, so no risk level either.
    fake.fail["supplier"] = 503
    assert _run("end-of-day") == 0
    first = _all_results(worker_session, _latest_run(worker_session, "end-of-day").id)
    assert len(first) == 20
    for row in first.values():
        assert row.reason_code == "NO_SUPPLIER" and row.order_qty is None
        assert row.lead_time_days is None and row.risk is None and row.base_risk is None

    # With a lead time from an earlier successful read, the risk is still set.
    del fake.fail["supplier"]
    assert _run("end-of-day") == 0
    fake.fail["supplier"] = 503
    assert _run("end-of-day") == 0
    third = _all_results(worker_session, _latest_run(worker_session, "end-of-day").id)
    for product, row in third.items():
        assert row.reason_code == "NO_SUPPLIER" and row.order_qty is None
        assert row.lead_time_days is not None
        assert row.risk == ("high" if product in LOW_STOCK else "low")


@pytest.mark.parametrize("failing", ["product", "inventory"])
def test_a_failed_product_or_stock_read_keeps_the_previous_result(
    fake, worker_session, failing
) -> None:
    assert _run("end-of-day") == 0
    first = _latest_run(worker_session, "end-of-day").id
    fake.fail[failing] = 503
    assert _run("end-of-day") == 0
    run = _latest_run(worker_session, "end-of-day")
    assert run.summary["risk_kept"] == 20 and run.summary["risk_computed"] == 0
    assert _all_results(worker_session, run.id) == {}
    newest = _newest(worker_session)
    assert len(newest) == 20 and {r.job_run_id for r in newest.values()} == {first}


# ---------------------------------------------------------------- the hourly window


def _spike_today(fake: FakeCanonical, product: str, today: date) -> int:
    """A fake Simulate Sales spike: today's open net = ceil(mean28 + 4 × sd28), the last 28 days
    before today counted with 0 for a day that has no row (the ERP rule after T041)."""
    window = []
    for back in range(28, 0, -1):
        row = fake.sales.get((product, (today - timedelta(days=back)).isoformat()))
        window.append(row["net_units"] if row else 0)
    net = spike_target(window)
    fake.put_sales(sales_row(product, today, net, 0, "open", datetime.now(UTC)))
    return net


def test_an_hourly_spike_raises_only_the_changed_product(fake, worker_session) -> None:
    from brain.models import Anomaly, RiskResult

    assert _run("end-of-day") == 0
    night = _newest(worker_session)
    today = today_cairo()
    net = _spike_today(fake, "P005", today)
    assert _run("sales-poll") == 0
    assert _run("hourly-window") == 0

    hourly = _latest_run(worker_session, "hourly-window")
    spikes = list(worker_session.scalars(select(Anomaly).where(Anomaly.scope == "intraday")))
    assert [
        (a.product_id, a.kind, a.business_date, a.net_units, a.raised_risk) for a in spikes
    ] == [("P005", "spike", today, net, True)]
    assert float(spikes[0].z) >= 4

    after = _newest(worker_session)
    p005 = after["P005"]
    assert p005.job_run_id == hourly.id and p005.forecast_run_id == night["P005"].forecast_run_id
    assert p005.raised_by_spike and p005.base_risk == night["P005"].base_risk
    assert p005.risk == LEVELS[min(LEVELS.index(p005.base_risk) + 1, 2)]
    _check_by_hand(worker_session, p005, today)
    # Only P005 was recomputed; every other product keeps last night's row.
    for product, row in after.items():
        if product != "P005":
            assert row.id == night[product].id and row.computed_at == night[product].computed_at
    assert (
        worker_session.scalar(
            select(func.count()).select_from(RiskResult).where(RiskResult.job_run_id == hourly.id)
        )
        == 1
    )
    assert hourly.summary["risk_computed"] == 1

    # A second window with nothing new recomputes nothing.
    assert _run("hourly-window") == 0
    assert _latest_run(worker_session, "hourly-window").summary["risk_computed"] == 0

    # The raise ends: the next night checks a newer closed day without a spike.
    for product in sorted({p for p, _ in fake.sales}):
        fake.put_sales(sales_row(product, today, 20, 0, "closed", datetime.now(UTC)))
    with time_machine.travel(datetime.now(UTC) + timedelta(days=1), tick=True):
        assert _run("end-of-day") == 0
        tomorrow = today_cairo()
    nxt = _newest(worker_session)["P005"]
    assert nxt.job_run_id == _latest_run(worker_session, "end-of-day").id
    assert not nxt.raised_by_spike and nxt.risk == nxt.base_risk
    _check_by_hand(worker_session, nxt, tomorrow)
    # The intraday spike stays visible as history.
    assert (
        worker_session.scalar(
            select(func.count()).select_from(Anomaly).where(Anomaly.scope == "intraday")
        )
        == 1
    )


def test_a_slow_sellers_spike_counts_missing_days_as_zero(fake, worker_session) -> None:
    """SC-007: P020 (about 4 a day) with five no-sale days that have no row."""
    from brain.models import Anomaly

    today = today_cairo()
    for index in (66, 70, 75, 81, 86):
        fake.remove_sales("P020", seed_date(today, index))
    assert _run("end-of-day") == 0
    net = _spike_today(fake, "P020", today)
    assert _run("sales-poll") == 0
    assert _run("hourly-window") == 0
    spike = worker_session.scalars(
        select(Anomaly).where(Anomaly.scope == "intraday", Anomaly.product_id == "P020")
    ).one()
    assert spike.kind == "spike" and spike.net_units == net and spike.raised_risk
    assert float(spike.z) >= 4
    assert _newest(worker_session)["P020"].raised_by_spike


def test_the_hourly_window_skips_a_product_without_a_forecast(fake, worker_session) -> None:
    from brain.models import RiskResult

    fake.put_sales(sales_row("P005", today_cairo(), 3, 0, "open", datetime.now(UTC)))
    assert _run("sales-poll") == 0
    assert _run("hourly-window") == 0
    assert worker_session.scalar(select(func.count()).select_from(RiskResult)) == 0
    assert _latest_run(worker_session, "hourly-window").summary["no_forecast"] >= 1


def test_a_supplier_without_a_lead_time_gives_no_supplier(fake, worker_session) -> None:
    """Spec Edge Cases: an empty lead_time_days means nothing to plan over."""
    from brain.models import ProductRef

    fake.suppliers["S004"] = dict(fake.suppliers["S004"], lead_time_days=None)  # P003's supplier
    assert _run("end-of-day") == 0
    results = _all_results(worker_session, _latest_run(worker_session, "end-of-day").id)
    p003 = results["P003"]
    assert p003.reason_code == "NO_SUPPLIER" and p003.order_qty is None
    assert p003.lead_time_days is None and p003.risk is None and p003.base_risk is None
    assert results["P011"].reason_code is None and results["P011"].risk == "high"  # S003 is fine
    ref = worker_session.get(ProductRef, "P003")
    assert ref.supplier_name == "Delta Health Trading" and ref.lead_time_days is None
