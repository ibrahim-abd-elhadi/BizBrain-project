"""US2 pieces that use the database: artifacts (T026), evaluation and degradation (T027), and the
anomaly scan (T028). Written before the implementation."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import lightgbm as lgb
import numpy as np
import pytest
from sqlalchemy import select

from brain.clock import CAIRO, today_cairo
from brain.config import Settings

from series import load_seed_into_db, seed_date

SETTINGS = Settings()


def _run(session, job="end-of-day", day: date | None = None) -> int:
    from brain.models import JobRun

    run = JobRun(
        job=job,
        trigger="manual",
        business_date=day or today_cairo(),
        started_at=datetime.now(CAIRO),
        finished_at=datetime.now(CAIRO),
        status="succeeded",
        summary={},
    )
    session.add(run)
    session.flush()
    return run.id


# ---------------------------------------------------------------- T026 artifacts


def _tiny_booster() -> lgb.Booster:
    X = np.array([[i % 7, i] for i in range(60)], dtype=float)
    y = X[:, 0] * 2 + 1
    params = {"objective": "l2", "verbose": -1, "deterministic": True, "num_threads": 1, "seed": 1}
    return lgb.train(params, lgb.Dataset(X, y, feature_name=["a", "b"]), num_boost_round=5)


def test_an_artifact_round_trips_and_refuses_tampering(worker_session) -> None:
    from brain.forecasting import artifacts
    from brain.models import ModelArtifact

    run_id = _run(worker_session)
    booster = _tiny_booster()
    artifacts.save(worker_session, booster, run_id, date(2026, 11, 17), {"x": 1})
    worker_session.commit()
    row = worker_session.scalars(select(ModelArtifact)).one()
    assert row.format == "lightgbm-text" and len(row.sha256) == 64
    loaded = artifacts.load(row, expected_features=["a", "b"])
    X = np.array([[3.0, 10.0]])
    assert loaded.predict(X).tolist() == booster.predict(X).tolist()

    for tamper in (
        {"body": row.body.replace("Tree=0", "Tree=00", 1)},
        {"lightgbm_version": "0.0.1"},
    ):
        bad = ModelArtifact(**{**{c.name: getattr(row, c.name) for c in ModelArtifact.__table__.columns}, **tamper})
        with pytest.raises(artifacts.ArtifactRefused):
            artifacts.load(bad, expected_features=["a", "b"])
    with pytest.raises(artifacts.ArtifactRefused):
        artifacts.load(row, expected_features=["a", "c"])


def test_old_artifacts_are_pruned(worker_session) -> None:
    from brain.forecasting import artifacts
    from brain.models import ModelArtifact

    today = today_cairo()
    for back in (20, 15, 13, 0):
        run_id = _run(worker_session, day=today - timedelta(days=back))
        artifacts.save(worker_session, _tiny_booster(), run_id, today - timedelta(days=back + 1), {})
    artifacts.prune(worker_session, keep_nights=14, today=today)
    worker_session.commit()
    kept = sorted(r.trained_through for r in worker_session.scalars(select(ModelArtifact)))
    assert kept == [today - timedelta(days=14), today - timedelta(days=1)]


# ---------------------------------------------------------------- T027 evaluation


def _evaluate(session, product, model, day, forecast, actual, backtest_wape):
    from brain.forecasting import evaluation
    from brain.models import ForecastEvaluation

    run_id = _run(session, day=day)
    session.add(
        ForecastEvaluation(
            product_id=product, business_date=day, job_run_id=run_id, model=model,
            forecast=Decimal(forecast), actual=actual,
        )
    )
    session.flush()
    return evaluation.update_health(session, product, model, day, backtest_wape, SETTINGS)


def test_degradation_needs_7_days_and_replaces_lightgbm_the_next_night(worker_session) -> None:
    from brain.forecasting import evaluation

    start = date(2026, 11, 1)
    # Six terrible days: not judged yet (needs 7).
    for i in range(6):
        health = _evaluate(worker_session, "P001", "lightgbm", start + timedelta(days=i), 30, 10, 0.2)
        assert health.live_wape is None and not health.degraded
    seventh = start + timedelta(days=6)
    health = _evaluate(worker_session, "P001", "lightgbm", seventh, 30, 10, 0.2)
    assert health.evaluated_days == 7
    assert float(health.live_wape) == pytest.approx(2.0) and health.degraded
    assert health.degraded_on == seventh
    assert evaluation.replaced_tonight([health], seventh) == {"P001"}
    # The night after, normal choice resumes (nothing is replaced any more).
    assert evaluation.replaced_tonight([health], seventh + timedelta(days=1)) == set()


def test_a_switch_of_model_kind_starts_a_new_window(worker_session) -> None:
    start = date(2026, 11, 1)
    for i in range(8):
        _evaluate(worker_session, "P002", "lightgbm", start + timedelta(days=i), 30, 10, 0.2)
    health = _evaluate(worker_session, "P002", "seasonal_naive", start + timedelta(days=8), 10, 10, 0.3)
    assert health.model == "seasonal_naive" and health.evaluated_days == 1
    assert not health.degraded and health.window_started == start + timedelta(days=8)


def test_the_window_is_at_most_28_days(worker_session) -> None:
    start = date(2026, 10, 1)
    for i in range(35):
        health = _evaluate(worker_session, "P003", "seasonal_naive", start + timedelta(days=i), 11, 10, 0.5)
    assert health.evaluated_days == 28 and float(health.live_wape) == pytest.approx(0.1)


# ---------------------------------------------------------------- T028 anomalies


def test_z_score_rule() -> None:
    from brain.anomalies import zscore

    z, mean, sd = zscore([10.0] * 28, 14.0)
    assert (mean, sd, z) == (10.0, 1.0, 4.0)  # sd = 0 counts as 1
    window = [8, 12] * 14
    z, mean, sd = zscore([float(v) for v in window], 20.0)
    assert mean == 10.0 and sd == pytest.approx(np.std(window, ddof=1)) and z == pytest.approx(10 / sd)


def test_the_first_scan_finds_the_five_planted_events_and_one_natural_spike(worker_session) -> None:
    from brain.anomalies import scan_closed_days
    from brain.forecasting.series import load_series
    from brain.models import Anomaly, AnomalyScanProgress

    today = today_cairo()
    load_seed_into_db(worker_session, today)
    end, series = load_series(worker_session, today)
    run_id = _run(worker_session)
    found = scan_closed_days(worker_session, series, end, run_id, SETTINGS)
    worker_session.commit()
    rows = sorted(
        (a.product_id, a.kind, a.business_date, a.raised_risk)
        for a in worker_session.scalars(select(Anomaly))
    )
    expected = sorted(
        [
            ("P004", "spike", seed_date(today, 45), False),
            ("P001", "drop", seed_date(today, 52), False),
            ("P008", "spike", seed_date(today, 63), False),
            ("P016", "drop", seed_date(today, 71), False),
            ("P013", "spike", seed_date(today, 80), False),
            # Not planted: P020 sells about 4 a day, and its seed day 64 happens to clear z = 4.
            # The ERP's seed test checks only that the planted events clear the threshold.
            ("P020", "spike", seed_date(today, 64), False),
        ]
    )
    assert rows == expected and found == 6
    progress = {p.product_id: p.scanned_through for p in worker_session.scalars(select(AnomalyScanProgress))}
    assert set(progress.values()) == {end} and len(progress) == 20

    # The next night scans only the new day; a spike on it raises risk; a drop never does.
    from series import add_days

    tomorrow_end = end + timedelta(days=1)
    add_days(worker_session, "P005", [500], tomorrow_end)
    add_days(worker_session, "P001", [0], tomorrow_end)
    end2, series2 = load_series(worker_session, tomorrow_end + timedelta(days=1))
    assert end2 == tomorrow_end
    found = scan_closed_days(worker_session, series2, end2, _run(worker_session), SETTINGS)
    worker_session.commit()
    new = {(a.product_id, a.kind, a.raised_risk) for a in worker_session.scalars(select(Anomaly)) if a.business_date == tomorrow_end}
    assert ("P005", "spike", True) in new
    assert all(not (kind == "drop" and raised) for _, kind, raised in new)
    assert found == len(new)
