"""Seed step 3: 90 closed days of sales history ending yesterday (Cairo), with planted events.

The history is written straight into daily_sales as `closed` rows. It never touches stock: the
catalog step already set the starting stock (FR-025). The random seed is fixed, so every reseed on
the same date gives the same data.
"""

import math
import random
import statistics
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import insert
from sqlalchemy.orm import Session

from erp.clock import now_utc, today_cairo
from erp.config import Settings
from erp.models import DailySales
from erp.seed.catalog import PRODUCT_SPECS, product_id_for
from erp.services.sampling import binomial, poisson

HISTORY_DAYS = 90
RETURN_RATE = 0.02
SPIKE_SD = 6  # planted spikes reach mean + 6 x sd: well past the Brain's z = 4 threshold

# Python's weekday(): Monday is 0. Fridays and Saturdays are slower (README Section 4.7 seed notes).
WEEKDAY_MULTIPLIER = {0: 1.1, 1: 1.0, 2: 1.0, 3: 1.05, 4: 0.8, 5: 0.9, 6: 1.1}


@dataclass(frozen=True)
class PlantedEvent:
    product_id: str
    kind: Literal["spike", "drop"]
    day_index: int  # 1-based: day 1 is the oldest day, day 90 is yesterday


# Every event sits on day 29-89, so the 28 days before it exist. All five are on different
# products, so no event disturbs another one's baseline. The drops are on products with a base
# demand of 30 or more, so a drop to 0 is far below the previous 28 days.
PLANTED_EVENTS: list[PlantedEvent] = [
    PlantedEvent("P004", "spike", 45),
    PlantedEvent("P008", "spike", 63),
    PlantedEvent("P013", "spike", 80),
    PlantedEvent("P001", "drop", 52),
    PlantedEvent("P016", "drop", 71),
]


def _spike_net(previous: list[int]) -> int:
    sd = statistics.stdev(previous) or 1
    return math.ceil(statistics.mean(previous) + SPIKE_SD * sd)


def seed_history(session: Session, settings: Settings) -> None:
    rng = random.Random(settings.erp_seed_random_seed)
    first_day = today_cairo() - timedelta(days=HISTORY_DAYS)  # yesterday - 89
    updated_at = now_utc()
    events = {(e.product_id, e.day_index): e for e in PLANTED_EVENTS}

    rows: list[dict] = []
    for index, spec in enumerate(PRODUCT_SPECS):
        product_id = product_id_for(index)
        nets: list[int] = []
        for day_index in range(1, HISTORY_DAYS + 1):
            business_date = first_day + timedelta(days=day_index - 1)
            event = events.get((product_id, day_index))
            if event is not None and event.kind == "spike":
                sold, returned = _spike_net(nets[-28:]), 0
            elif event is not None:  # a drop: nothing sold that day
                sold, returned = 0, 0
            else:
                mean = spec.base_daily_demand * WEEKDAY_MULTIPLIER[business_date.weekday()]
                sold = poisson(rng, mean)
                returned = binomial(rng, sold, RETURN_RATE)
            nets.append(sold - returned)
            rows.append(
                {
                    "product_id": product_id,
                    "business_date": business_date,
                    "units_sold": sold,
                    "units_returned": returned,
                    "day_status": "closed",
                    "updated_at": updated_at,
                }
            )
    session.execute(insert(DailySales), rows)
    session.flush()
