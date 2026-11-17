"""Simulate Sales (FR-011, FR-012, FR-023, research R-15, R-16). Written before the implementation.

Each test seeds the real dataset (90 closed days ending yesterday) with the clock frozen in Cairo.
Where an exact number matters the random draws are replaced by fixed ones.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from erp.config import get_settings
from erp.models import DailySales, Product, Stock

BASE = "/api/v1/erp"
NOW = "2026-11-18T12:00"  # Cairo; the seeded history ends 2026-11-17


@pytest.fixture
def force_draws(monkeypatch: pytest.MonkeyPatch) -> Callable[[int, int], None]:
    """force_draws(sold, returned): every product's batch becomes exactly that."""

    def _force(sold: int, returned: int) -> None:
        monkeypatch.setattr("erp.services.simulate.poisson", lambda rng, lam: sold)
        monkeypatch.setattr("erp.services.simulate.binomial", lambda rng, n, p: returned)

    return _force


@pytest.fixture
def spike_z(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    """spike_z("3") sets ERP_SPIKE_Z and reloads the settings; the original is restored after."""

    def _set(value: str) -> None:
        monkeypatch.setenv("ERP_SPIKE_Z", value)
        get_settings.cache_clear()

    yield _set
    monkeypatch.undo()
    get_settings.cache_clear()


def _set_stock(db: Session, product_id: str, on_hand: int) -> None:
    db.execute(update(Stock).where(Stock.product_id == product_id).values(on_hand=on_hand))
    db.commit()


def _on_hand(db: Session, product_id: str) -> int:
    db.expire_all()
    return db.scalar(select(Stock.on_hand).where(Stock.product_id == product_id))  # type: ignore[return-value]


def _today_row(db: Session, product_id: str, today: date) -> DailySales | None:
    db.expire_all()
    return db.scalars(
        select(DailySales).where(
            DailySales.product_id == product_id, DailySales.business_date == today
        )
    ).one_or_none()


def _entry(result: dict, product_id: str) -> dict:
    return next(p for p in result["products"] if p["product_id"] == product_id)


def test_only_todays_rows_change_and_they_are_open(
    client: TestClient, db: Session, at_cairo, seed, login
) -> None:
    with at_cairo(NOW):
        seed()
        before = {
            (r.product_id, r.business_date): (r.units_sold, r.units_returned, r.updated_at)
            for r in db.scalars(select(DailySales))
        }
        response = client.post(f"{BASE}/sales/simulate", json={}, headers=login())

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["business_date"] == "2026-11-18"
    assert result["spike"] is None

    db.expire_all()
    today = date(2026, 11, 18)
    changed = [r for r in db.scalars(select(DailySales)) if r.business_date == today]
    assert changed, "the batch should add something for today"
    assert {r.day_status for r in changed} == {"open"}
    for r in db.scalars(select(DailySales)):
        if r.business_date != today:
            assert (r.units_sold, r.units_returned, r.updated_at) == before[
                (r.product_id, r.business_date)
            ]
    assert len(before) == 1800


def test_stock_falls_by_the_net_units_added(
    client: TestClient, db: Session, at_cairo, seed, login, force_draws
) -> None:
    force_draws(12, 2)
    with at_cairo(NOW):
        seed()
        _set_stock(db, "P001", 30)
        result = client.post(f"{BASE}/sales/simulate", json={}, headers=login()).json()

    entry = _entry(result, "P001")
    assert (entry["units_sold_added"], entry["units_returned_added"]) == (12, 2)
    assert entry["capped_by_stock"] is False
    assert _on_hand(db, "P001") == 20  # 30 - (12 - 2)
    row = _today_row(db, "P001", date(2026, 11, 18))
    assert (row.units_sold, row.units_returned, row.net_units) == (12, 2, 10)  # type: ignore[union-attr]


def test_a_second_run_adds_to_todays_totals(
    client: TestClient, db: Session, at_cairo, seed, login, force_draws
) -> None:
    force_draws(12, 2)
    with at_cairo(NOW):
        seed()
        _set_stock(db, "P001", 100)
        headers = login()
        client.post(f"{BASE}/sales/simulate", json={}, headers=headers)
        client.post(f"{BASE}/sales/simulate", json={}, headers=headers)

    row = _today_row(db, "P001", date(2026, 11, 18))
    assert (row.units_sold, row.units_returned) == (24, 4)  # type: ignore[union-attr]
    assert _on_hand(db, "P001") == 80


def test_low_stock_cuts_the_batch_and_stock_never_goes_below_zero(
    client: TestClient, db: Session, at_cairo, seed, login, force_draws
) -> None:
    force_draws(12, 2)
    with at_cairo(NOW):
        seed()
        _set_stock(db, "P001", 5)
        _set_stock(db, "P002", 0)
        result = client.post(f"{BASE}/sales/simulate", json={}, headers=login()).json()

    p1 = _entry(result, "P001")
    assert p1["capped_by_stock"] is True
    assert p1["units_sold_added"] - p1["units_returned_added"] <= 5
    assert _on_hand(db, "P001") == 5 - (p1["units_sold_added"] - p1["units_returned_added"])

    # With nothing in stock, nothing is sold.
    assert _on_hand(db, "P002") == 0
    assert _today_row(db, "P002", date(2026, 11, 18)) is None
    assert db.scalar(select(func.min(Stock.on_hand))) >= 0


def test_a_spike_reaches_its_target_when_stock_allows(
    client: TestClient, db: Session, at_cairo, seed, login
) -> None:
    with at_cairo(NOW):
        seed()
        _set_stock(db, "P002", 100_000)
        result = client.post(
            f"{BASE}/sales/simulate", json={"spike_product_id": "P002"}, headers=login()
        ).json()

    spike = result["spike"]
    assert spike["product_id"] == "P002"
    assert spike["achieved_net_units"] >= spike["target_net_units"]
    assert spike["capped_by_stock"] is False
    row = _today_row(db, "P002", date(2026, 11, 18))
    assert row.net_units == spike["achieved_net_units"]  # type: ignore[union-attr]


def test_a_spike_is_capped_and_reported_when_stock_is_low(
    client: TestClient, db: Session, at_cairo, seed, login
) -> None:
    with at_cairo(NOW):
        seed()
        _set_stock(db, "P002", 3)
        result = client.post(
            f"{BASE}/sales/simulate", json={"spike_product_id": "P002"}, headers=login()
        ).json()

    spike = result["spike"]
    assert spike["capped_by_stock"] is True
    assert spike["achieved_net_units"] < spike["target_net_units"]
    assert spike["achieved_net_units"] <= 3
    assert _on_hand(db, "P002") >= 0


def test_a_spike_on_a_product_with_under_28_closed_days_changes_nothing(
    client: TestClient, db: Session, at_cairo, seed, login
) -> None:
    with at_cairo(NOW):
        seed()
        headers = login()
        created = client.post(
            f"{BASE}/products",
            json={
                "name": "Brand new product",
                "preferred_supplier_id": "S001",
                "pack_multiple": 10,
                "max_order_qty": 200,
                "starting_stock": 50,
            },
            headers=headers,
        )
        assert created.status_code == 201
        new_id = created.json()["product_id"]
        stock_before = {p: _on_hand(db, p) for p in db.scalars(select(Product.product_id)).all()}

        response = client.post(
            f"{BASE}/sales/simulate", json={"spike_product_id": new_id}, headers=headers
        )

    assert response.status_code == 422
    assert response.json()["code"] == "SPIKE_NEEDS_HISTORY"
    assert {p: _on_hand(db, p) for p in stock_before} == stock_before
    db.expire_all()
    assert (
        db.scalar(select(func.count()).where(DailySales.business_date == date(2026, 11, 18))) == 0
    )


def test_unknown_spike_product_is_not_found(
    client: TestClient, db: Session, at_cairo, seed, login
) -> None:
    with at_cairo(NOW):
        seed()
        response = client.post(
            f"{BASE}/sales/simulate", json={"spike_product_id": "P099"}, headers=login()
        )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_just_before_cairo_midnight_utc_the_rows_are_already_tomorrows(
    client: TestClient, db: Session, seed, login, force_draws
) -> None:
    force_draws(5, 0)
    moment = datetime(2026, 11, 17, 23, 30, tzinfo=UTC)  # 01:30 on 2026-11-18 in Cairo
    with time_machine.travel(moment, tick=False):
        seed()  # history therefore ends 2026-11-17
        result = client.post(f"{BASE}/sales/simulate", json={}, headers=login()).json()

    assert result["business_date"] == "2026-11-18"
    db.expire_all()
    dates = set(db.scalars(select(DailySales.business_date).where(DailySales.day_status == "open")))
    assert dates == {date(2026, 11, 18)}


def test_a_lower_spike_z_gives_a_lower_target(
    client: TestClient, db: Session, at_cairo, seed, login, spike_z
) -> None:
    with at_cairo(NOW):
        seed()
        _set_stock(db, "P002", 100_000)
        headers = login()
        default = client.post(
            f"{BASE}/sales/simulate", json={"spike_product_id": "P002"}, headers=headers
        ).json()["spike"]
        spike_z("3")
        lower = client.post(
            f"{BASE}/sales/simulate", json={"spike_product_id": "P002"}, headers=headers
        ).json()["spike"]

    assert lower["target_net_units"] < default["target_net_units"]


def test_on_the_autumn_clock_change_night_the_rows_stay_on_the_same_cairo_day(
    client: TestClient, db: Session, seed, login, force_draws
) -> None:
    force_draws(5, 0)
    # 2026-10-29: Cairo's clocks go back at 21:00 UTC. 21:30 UTC is 23:30 Cairo (UTC+2): still the 29th.
    moment = datetime(2026, 10, 29, 21, 30, tzinfo=UTC)
    with time_machine.travel(moment, tick=False):
        seed()
        result = client.post(f"{BASE}/sales/simulate", json={}, headers=login()).json()

    assert result["business_date"] == "2026-10-29"
    db.expire_all()
    dates = set(db.scalars(select(DailySales.business_date).where(DailySales.day_status == "open")))
    assert dates == {date(2026, 10, 29)}


def test_simulate_needs_a_token(client: TestClient, manager: str) -> None:
    response = client.post(f"{BASE}/sales/simulate", json={})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


# ---- Feature 003 (T040): one zero-fill rule. "The product's last 28 closed days" (feature 001
# spec) are the 28 calendar days before today; a closed day with no sales row counts as 0, exactly
# as the Brain counts it, so an ERP spike always reaches z = 4 in the Brain.

TODAY_003 = date(2026, 11, 18)
NO_SALE_DAYS = (2, 5, 9, 14, 20)  # days back from today with their P020 rows removed


def _drop_p020_rows(db: Session) -> None:
    from datetime import timedelta

    from sqlalchemy import delete

    for back in NO_SALE_DAYS:
        db.execute(
            delete(DailySales).where(
                DailySales.product_id == "P020",
                DailySales.business_date == TODAY_003 - timedelta(days=back),
            )
        )
    db.commit()


def _zero_filled_window(db: Session, product_id: str) -> list[int]:
    from datetime import timedelta

    db.expire_all()
    by_day = {
        r.business_date: r.units_sold - r.units_returned
        for r in db.scalars(select(DailySales).where(DailySales.product_id == product_id))
    }
    return [by_day.get(TODAY_003 - timedelta(days=back), 0) for back in range(28, 0, -1)]


def test_closed_history_counts_no_sale_days_as_zero(db: Session, at_cairo, seed) -> None:
    from erp.services.simulate import closed_history

    with at_cairo(NOW):
        seed()
        _drop_p020_rows(db)
        history = closed_history(db, "P020", TODAY_003)
    assert len(history) == 28
    assert history == _zero_filled_window(db, "P020")
    assert history.count(0) >= len(NO_SALE_DAYS)


def test_closed_history_of_a_young_product_covers_only_its_days(db: Session, at_cairo, seed) -> None:
    from datetime import timedelta

    from sqlalchemy import delete

    from erp.services.simulate import closed_history

    with at_cairo(NOW):
        seed()
        db.execute(
            delete(DailySales).where(
                DailySales.product_id == "P019",
                DailySales.business_date < TODAY_003 - timedelta(days=20),
            )
        )
        db.commit()
        history = closed_history(db, "P019", TODAY_003)
    assert len(history) == 20


def test_a_slow_sellers_spike_uses_the_zero_filled_window(
    client: TestClient, db: Session, at_cairo, seed, login
) -> None:
    import math
    import statistics

    with at_cairo(NOW):
        seed()
        _drop_p020_rows(db)
        _set_stock(db, "P020", 100_000)
        window = _zero_filled_window(db, "P020")
        result = client.post(
            f"{BASE}/sales/simulate", json={"spike_product_id": "P020"}, headers=login()
        ).json()
    sd = statistics.stdev(window) or 1
    expected = math.ceil(statistics.mean(window) + 4 * sd)
    assert result["spike"]["target_net_units"] == expected
    assert result["spike"]["achieved_net_units"] >= expected
    # So the Brain, counting no-sale days as 0 too, sees z >= 4.
    assert (result["spike"]["achieved_net_units"] - statistics.mean(window)) / sd >= 4


def test_the_simulate_baseline_uses_the_same_window(
    client: TestClient, db: Session, at_cairo, seed, login, monkeypatch: pytest.MonkeyPatch
) -> None:
    import statistics

    lambdas: list[float] = []

    def record(rng, lam):  # noqa: ANN001
        lambdas.append(lam)
        return 0

    with at_cairo(NOW):
        seed()
        _drop_p020_rows(db)
        window = _zero_filled_window(db, "P020")
        monkeypatch.setattr("erp.services.simulate.poisson", record)
        assert client.post(f"{BASE}/sales/simulate", json={}, headers=login()).status_code == 200
    fraction = get_settings().erp_simulate_batch_fraction
    # Products are simulated in ID order, so P020 (the 20th) is the last draw.
    assert lambdas[-1] == pytest.approx(max(1.0, statistics.mean(window)) * fraction)
