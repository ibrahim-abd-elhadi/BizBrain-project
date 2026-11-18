"""GET /api/v1/brain/forecasts and /forecasts/{product_id} (US5 scenarios 1-4; research R-17).
Written before the implementation."""

from datetime import date, timedelta

from brain.clock import today_cairo

from series import seed_date


def _get(api_client, manager, path: str):
    return api_client.get(f"/api/v1/brain{path}", headers=manager)


def test_no_forecast_before_the_first_night(api_client, manager) -> None:
    assert _get(api_client, manager, "/forecasts").json() == []
    response = _get(api_client, manager, "/forecasts/P003")
    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


def test_the_product_list(first_night, api_client, manager, worker_session) -> None:
    from sqlalchemy import select

    from brain.models import ModelChoice

    body = _get(api_client, manager, "/forecasts").json()
    assert [p["product_id"] for p in body] == [f"P{i:03d}" for i in range(1, 21)]
    chosen = {c.product_id: c.chosen_model for c in worker_session.scalars(select(ModelChoice))}
    for p in body:
        assert p["chosen_model"] == chosen[p["product_id"]] and p["degraded"] is False
    assert body[2]["product_name"] == "Amoxicillin 500 mg capsules"


def test_one_products_forecast(first_night, api_client, manager) -> None:
    fake = first_night
    today = today_cairo()
    body = _get(api_client, manager, "/forecasts/P003").json()
    assert body["synthetic"] is True and body["product_id"] == "P003"
    assert body["product_name"] == "Amoxicillin 500 mg capsules"
    assert body["run_date"] == today.isoformat()

    history = body["history"]
    assert len(history) == 28
    expected_days = [today - timedelta(days=back) for back in range(28, 0, -1)]
    assert [date.fromisoformat(h["business_date"]) for h in history] == expected_days
    for h in history:
        row = fake.sales[("P003", h["business_date"])]
        assert h["y_units"] == max(row["net_units"], 0)

    forecast = body["forecast"]
    assert [f["target_date"] for f in forecast] == [
        (today + timedelta(days=i)).isoformat() for i in range(14)
    ]
    assert all(0 <= f["low"] <= f["yhat"] <= f["high"] for f in forecast)

    model = body["model"]
    assert model["chosen_model"] in ("seasonal_naive", "lightgbm")
    assert model["lgbm_eligible"] is True
    assert model["sn_backtest_wape"] is not None and model["lgbm_backtest_wape"] is not None
    assert model["degraded"] is False and model["live_wape"] is None
    assert body["anomalies"] == []


def test_anomalies_on_the_days_shown(first_night, api_client, manager) -> None:
    today = today_cairo()
    p013 = _get(api_client, manager, "/forecasts/P013").json()
    assert [(a["kind"], a["business_date"]) for a in p013["anomalies"]] == [
        ("spike", seed_date(today, 80).isoformat())
    ]
    # P004's spike (seed day 45) is older than the 28 days shown.
    assert _get(api_client, manager, "/forecasts/P004").json()["anomalies"] == []


def test_a_closed_day_without_a_row_shows_as_zero(fake_erp, api_client, manager) -> None:
    from brain.jobs.registry import run_job

    today = today_cairo()
    gap = seed_date(today, 85)
    fake_erp.remove_sales("P020", gap)
    assert run_job("end-of-day", "manual") == 0
    history = _get(api_client, manager, "/forecasts/P020").json()["history"]
    assert len(history) == 28
    assert {h["business_date"]: h["y_units"] for h in history}[gap.isoformat()] == 0


def test_unknown_and_malformed_product_ids(first_night, api_client, manager) -> None:
    missing = _get(api_client, manager, "/forecasts/P999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "No forecast for P999", "code": "NOT_FOUND"}
    for bad in ("p003", "P3", "X003"):
        response = _get(api_client, manager, f"/forecasts/{bad}")
        assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
