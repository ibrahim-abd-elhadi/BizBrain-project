"""The end-of-day run (US2 scenarios 1-7; SC-003 to SC-005; research R-06 to R-13), on the seed
fixture through the fake Canonical API. Written before the implementation."""

import time
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from sqlalchemy import func, select

from brain.clock import today_cairo

from fakes import FakeCanonical, sales_row
from series import seed_date


@pytest.fixture
def fake(pg, monkeypatch) -> FakeCanonical:
    fake = FakeCanonical()
    fake.load_seed(today_cairo(), datetime.now(UTC) - timedelta(hours=2))
    monkeypatch.setattr("brain.canonical.client.TEST_TRANSPORT", fake.transport())
    return fake


def _eod() -> int:
    from brain.jobs.registry import run_job

    return run_job("end-of-day", trigger="manual")


def _latest_run(session):
    from brain.models import JobRun

    session.expire_all()
    return session.scalars(
        select(JobRun).where(JobRun.job == "end-of-day").order_by(JobRun.id.desc())
    ).first()


def _forecasts(session, run_id):
    from brain.models import Forecast

    return {
        (f.product_id, f.target_date): (f.model, f.yhat, f.low, f.high)
        for f in session.scalars(select(Forecast).where(Forecast.job_run_id == run_id))
    }


def _choices(session, run_id):
    from brain.models import ModelChoice

    return {
        c.product_id: c
        for c in session.scalars(select(ModelChoice).where(ModelChoice.job_run_id == run_id))
    }


def test_the_first_night(fake, worker_session) -> None:
    from brain.models import ForecastEvaluation, ModelArtifact, SalesDaily

    started = time.perf_counter()
    assert _eod() == 0
    took = time.perf_counter() - started
    run = _latest_run(worker_session)
    today = today_cairo()
    # The run started with its own sales poll.
    assert worker_session.scalar(select(func.count()).select_from(SalesDaily)) == 1800
    assert run.summary["backtest_cuts"] == [seed_date(today, 62).isoformat(), seed_date(today, 76).isoformat()]
    assert run.summary["final_cut"] == seed_date(today, 90).isoformat()

    choices = _choices(worker_session, run.id)
    assert len(choices) == 20
    for c in choices.values():
        assert c.lgbm_eligible and c.history_days == 90  # 90 ≥ 56 (README 4.7)
        assert c.sn_backtest_wape is not None and c.lgbm_backtest_wape is not None
        wins = float(c.lgbm_backtest_wape) <= float(c.sn_backtest_wape) - 0.05
        assert c.chosen_model == ("lightgbm" if wins else "seasonal_naive")

    forecasts = _forecasts(worker_session, run.id)
    assert len(forecasts) == 20 * 14
    for product in choices:
        days = sorted(d for p, d in forecasts if p == product)
        assert days == [today + timedelta(days=i) for i in range(14)]
    for model, yhat, low, high in forecasts.values():
        assert 0 <= low <= yhat <= high
    assert worker_session.scalar(select(func.count()).select_from(ForecastEvaluation)) == 0
    assert worker_session.scalar(select(func.count()).select_from(ModelArtifact)) == 1
    assert run.summary["anomalies_found"] == 6  # 5 planted + P020 day 64 (natural)
    assert took < 600  # SC-003


def test_the_run_is_deterministic_and_ignores_the_open_day(fake, worker_session) -> None:
    from brain.models import ModelArtifact

    assert _eod() == 0
    first = _latest_run(worker_session).id
    fake.put_sales(sales_row("P003", today_cairo(), 9999, 0, "open", datetime.now(UTC)))
    assert _eod() == 0
    second = _latest_run(worker_session).id
    a, b = _forecasts(worker_session, first), _forecasts(worker_session, second)
    assert a == b
    ca, cb = _choices(worker_session, first), _choices(worker_session, second)
    assert {p: (c.chosen_model, c.sn_backtest_wape, c.lgbm_backtest_wape) for p, c in ca.items()} == {
        p: (c.chosen_model, c.sn_backtest_wape, c.lgbm_backtest_wape) for p, c in cb.items()
    }
    bodies = [r.body for r in worker_session.scalars(select(ModelArtifact).order_by(ModelArtifact.id))]
    assert len(bodies) == 2 and bodies[0] == bodies[1]


def test_eligibility_at_8_weeks_and_short_history(fake, worker_session) -> None:
    today = today_cairo()
    stamp = datetime.now(UTC) - timedelta(hours=2)
    for product, days in (("P021", 50), ("P022", 60), ("P023", 10)):
        for back in range(1, days + 1):
            fake.put_sales(sales_row(product, today - timedelta(days=back), 5 + back % 3, 0, "closed", stamp))
    assert _eod() == 0
    run = _latest_run(worker_session)
    choices = _choices(worker_session, run.id)
    assert not choices["P021"].lgbm_eligible and choices["P021"].chosen_model == "seasonal_naive"
    assert choices["P022"].lgbm_eligible and choices["P022"].lgbm_backtest_wape is not None
    short = choices["P023"]
    assert not short.lgbm_eligible and short.chosen_model == "seasonal_naive"
    assert short.sn_backtest_wape is None  # no errors: it didn't exist at either origin
    forecasts = {d: v for (p, d), v in _forecasts(worker_session, run.id).items() if p == "P023"}
    assert len(forecasts) == 14
    for model, yhat, low, high in forecasts.values():
        assert 0 <= low <= yhat <= high and high > yhat  # ± its standard deviation


def test_the_second_night_evaluates_yesterday(fake, worker_session) -> None:
    from brain.models import ForecastEvaluation

    assert _eod() == 0
    first = _latest_run(worker_session).id
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    today = today_cairo()
    for product in sorted({p for p, _ in fake.sales}):
        fake.put_sales(sales_row(product, today, 20, 0, "closed", datetime.now(UTC)))
    with time_machine.travel(tomorrow, tick=True):
        assert _eod() == 0
    evaluations = list(worker_session.scalars(select(ForecastEvaluation)))
    assert len(evaluations) == 20
    assert {e.business_date for e in evaluations} == {today}
    assert {e.job_run_id for e in evaluations} == {first}
    assert all(e.actual == 20 for e in evaluations)
