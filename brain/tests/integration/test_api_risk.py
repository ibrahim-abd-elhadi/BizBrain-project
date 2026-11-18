"""GET /api/v1/brain/risk (US4 scenarios 1-6; research R-17). Written before the implementation."""

from datetime import UTC, datetime

from brain.clock import today_cairo

from fakes import sales_row
from series import spike_target

RISK_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3}
LOW_STOCK = {"P003", "P011", "P017"}


def _risk(api_client, manager) -> dict:
    response = api_client.get("/api/v1/brain/risk", headers=manager)
    assert response.status_code == 200
    return response.json()


def _sort_key(row: dict):
    cover = row["days_of_cover"]
    return (RISK_ORDER[row["risk"]], cover is None, cover or 0, row["product_id"])


def test_before_any_night_there_are_no_results(api_client, manager) -> None:
    body = _risk(api_client, manager)
    assert body == {"synthetic": True, "results_exist": False, "last_end_of_day": None, "items": []}


def test_the_list_after_the_first_night(first_night, api_client, manager, worker_session) -> None:
    from sqlalchemy import select

    from brain.models import JobRun

    body = _risk(api_client, manager)
    items = body["items"]
    assert body["results_exist"] and len(items) == 20
    assert items == sorted(items, key=_sort_key)
    assert {r["product_id"] for r in items[:3]} == LOW_STOCK
    assert all(r["risk"] == "low" for r in items[3:])

    run = worker_session.scalars(select(JobRun).where(JobRun.job == "end-of-day")).one()
    assert datetime.fromisoformat(body["last_end_of_day"]) == run.finished_at
    p003 = next(r for r in items if r["product_id"] == "P003")
    assert p003["product_name"] == "Amoxicillin 500 mg capsules"
    assert p003["risk"] == "high" and p003["lead_time_days"] == 7 and p003["available"] == 60
    assert p003["open_po_qty"] == 0 and p003["reason_code"] is None and p003["order_qty"] > 0
    inputs = p003["inputs"]
    assert inputs["forecast_run_date"] == run.business_date.isoformat()
    assert inputs["pack_multiple"] == 12 and inputs["max_order_qty"] == 240
    assert inputs["target"] - p003["available"] - p003["open_po_qty"] == inputs["raw"]

    anomalies = {r["product_id"]: r["latest_anomaly"] for r in items if r["latest_anomaly"]}
    assert {
        p: (a["kind"], a["scope"], a["raised_risk"]) for p, a in anomalies.items() if p != "P020"
    } == {
        "P004": ("spike", "closed", False),
        "P001": ("drop", "closed", False),
        "P008": ("spike", "closed", False),
        "P016": ("drop", "closed", False),
        "P013": ("spike", "closed", False),
    }
    assert anomalies["P004"]["z"] >= 4 and anomalies["P001"]["z"] <= -4


def test_only_the_newest_result_per_product(first_night, api_client, manager) -> None:
    from brain.jobs.registry import run_job

    fake = first_night
    today = today_cairo()
    window = [
        (fake.sales.get(("P005", d.isoformat())) or {"net_units": 0})["net_units"]
        for d in (today.fromordinal(today.toordinal() - back) for back in range(28, 0, -1))
    ]
    fake.put_sales(sales_row("P005", today, spike_target(window), 0, "open", datetime.now(UTC)))
    assert run_job("sales-poll", "manual") == 0
    assert run_job("hourly-window", "manual") == 0
    items = _risk(api_client, manager)["items"]
    assert len(items) == 20
    p005 = next(r for r in items if r["product_id"] == "P005")
    assert p005["risk"] == "medium" and p005["base_risk"] == "low" and p005["raised_by_spike"]
    assert p005["latest_anomaly"]["scope"] == "intraday" and p005["latest_anomaly"]["raised_risk"]
    assert p005["latest_anomaly"]["business_date"] == today.isoformat()
    assert items == sorted(items, key=_sort_key)


def test_reason_codes_and_missing_quantities_pass_through(fake_erp, api_client, manager) -> None:
    from brain.jobs.registry import run_job

    fake_erp.fail["purchase_orders"] = 503
    fake_erp.suppliers["S004"] = dict(fake_erp.suppliers["S004"], lead_time_days=None)
    assert run_job("end-of-day", "manual") == 0
    items = _risk(api_client, manager)["items"]
    assert items == sorted(items, key=_sort_key)
    no_lead = [r for r in items if r["risk"] is None]
    assert no_lead and items[-len(no_lead) :] == no_lead  # rows with no risk come last
    for row in items:
        assert row["order_qty"] is None and row["reason_code"] in (
            "NO_SUPPLIER",
            "OPEN_PO_UNAVAILABLE",
        )
        if row["reason_code"] == "OPEN_PO_UNAVAILABLE":
            assert row["open_po_qty"] is None and row["risk"] is not None
    p003 = next(r for r in items if r["product_id"] == "P003")
    assert p003["reason_code"] == "NO_SUPPLIER" and p003["inputs"]["forecast_over_lead"] is None
