"""The seed: 90 closed days ending yesterday, planted events, starting stock (FR-010, FR-025).

Written before the implementation.
"""

import math
import statistics
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.config import get_settings
from erp.models import DailySales, Product, Stock, Supplier
from erp.seed.__main__ import SeedRefused, main, run_seed
from erp.seed.catalog import PRODUCT_SPECS, product_id_for
from erp.seed.history import PLANTED_EVENTS

NOW = "2026-11-18T10:00"
YESTERDAY = date(2026, 11, 17)
FIRST_DAY = YESTERDAY - timedelta(days=89)  # 2026-08-20


def _series(db: Session, product_id: str) -> list[int]:
    return list(
        db.scalars(
            select(DailySales.net_units)
            .where(DailySales.product_id == product_id)
            .order_by(DailySales.business_date)
        )
    )


def test_seed_loads_catalog_and_90_closed_days(db: Session, at_cairo, seed) -> None:
    with at_cairo(NOW):
        seed()

    assert db.scalar(select(func.count()).select_from(Product)) == 20
    assert db.scalar(select(func.count()).select_from(Supplier)) == 4
    assert db.scalar(select(func.count()).select_from(DailySales)) == 1800
    assert set(db.scalars(select(DailySales.day_status))) == {"closed"}
    assert db.scalar(select(func.min(DailySales.business_date))) == FIRST_DAY == date(2026, 8, 20)
    assert db.scalar(select(func.max(DailySales.business_date))) == YESTERDAY
    assert (
        db.scalar(select(func.count()).where(DailySales.business_date >= date(2026, 11, 18))) == 0
    )
    per_product = db.execute(
        select(DailySales.product_id, func.count()).group_by(DailySales.product_id)
    ).all()
    assert len(per_product) == 20
    assert {count for _, count in per_product} == {90}


def test_seeding_history_does_not_move_stock(db: Session, at_cairo, seed) -> None:
    with at_cairo(NOW):
        seed()

    for index, spec in enumerate(PRODUCT_SPECS):
        on_hand = db.scalar(select(Stock.on_hand).where(Stock.product_id == product_id_for(index)))
        assert on_hand == math.ceil(spec.base_daily_demand * spec.starting_cover_days), spec.name


def test_planted_events_sit_on_days_29_to_89_and_clear_the_threshold(
    db: Session, at_cairo, seed
) -> None:
    with at_cairo(NOW):
        seed()

    spikes = [e for e in PLANTED_EVENTS if e.kind == "spike"]
    drops = [e for e in PLANTED_EVENTS if e.kind == "drop"]
    assert (len(spikes), len(drops)) == (3, 2)

    for event in PLANTED_EVENTS:
        assert 29 <= event.day_index <= 89, event
        series = _series(db, event.product_id)
        assert len(series) == 90
        previous = series[event.day_index - 29 : event.day_index - 1]  # the 28 days before
        assert len(previous) == 28
        mean, sd = statistics.mean(previous), statistics.stdev(previous)
        net = series[event.day_index - 1]
        if event.kind == "spike":
            assert net >= mean + 4 * sd, (event, net, mean, sd)
        else:
            spec = PRODUCT_SPECS[int(event.product_id[1:]) - 1]
            assert spec.base_daily_demand >= 30
            assert (net - mean) / sd <= -4, (event, net, mean, sd)


def test_seed_refuses_to_run_twice_unless_reset(db: Session, at_cairo, seed) -> None:
    with at_cairo(NOW):
        seed()

        try:
            run_seed(db, get_settings(), reset=False)
        except SeedRefused:
            db.rollback()
        else:
            raise AssertionError("a second seed without --reset must be refused")

        assert main([]) == 1  # the command exits with code 1
        assert main(["--reset"]) == 0
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(DailySales)) == 1800


def test_same_seed_gives_the_same_history(db: Session, at_cairo, seed) -> None:
    runs: list[list[int]] = []
    for _ in range(2):
        with at_cairo(NOW):
            seed()
        db.expire_all()
        runs.append(_series(db, "P001"))
    assert runs[0] == runs[1]
