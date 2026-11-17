"""Polling never misses a change (SC-002, SC-003; research R-07, point 6; R-16).

The proof says a row the Brain misses committed after the first page's snapshot, so its
updated_at > W - T - d, where T is the transaction limit and d the first page's query time.
Any overlap larger than T + d is therefore enough. README fixes the overlap at 120 s for T = 60 s;
these tests scale both down (T = 1 s, overlap = 3 s) so that a run of a few seconds really
exercises the bound instead of hiding inside a 120-second window.

Written before the implementation.
"""

import os
import random
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from erp.clock import now_utc, today_cairo
from erp.models import DailySales

from canonical_support import CANON

OVERLAP = timedelta(seconds=3)
PRODUCTS = ("P001", "P002")


def _reset() -> None:
    from erp.config import get_settings
    from erp.db import reset_caches

    reset_caches()
    get_settings.cache_clear()


@contextmanager
def transaction_limit(seconds: int) -> Iterator[None]:
    old = os.environ.get("ERP_DB_TRANSACTION_TIMEOUT_SECONDS")
    os.environ["ERP_DB_TRANSACTION_TIMEOUT_SECONDS"] = str(seconds)
    _reset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("ERP_DB_TRANSACTION_TIMEOUT_SECONDS", None)
        else:
            os.environ["ERP_DB_TRANSACTION_TIMEOUT_SECONDS"] = old
        _reset()


def _window() -> dict[str, str]:
    today = today_cairo()
    return {"from": (today - timedelta(days=20)).isoformat(), "to": today.isoformat()}


class Brain:
    """A simulated polling client following README Section 3.2 (with the scaled overlap)."""

    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers
        self.copy: dict[tuple[str, str], dict[str, Any]] = {}
        self.saved: datetime | None = None

    def _page(self, params: dict[str, Any]) -> dict[str, Any]:
        response = self.client.get(f"{CANON}/sales", params=params, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()

    def _upsert(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            pair = (item["product_id"], item["business_date"])
            held = self.copy.get(pair)
            if held is None or datetime.fromisoformat(held["updated_at"]) <= datetime.fromisoformat(
                item["updated_at"]
            ):
                self.copy[pair] = item

    def poll(self, rng: random.Random | None = None, stop_after: int | None = None) -> bool:
        params: dict[str, Any] = {**_window(), "limit": 7}
        if self.saved is not None:
            params["updated_since"] = (self.saved - OVERLAP).isoformat()
        body = self._page(params)
        pages = 1
        while True:
            self._upsert(body["items"])
            if body["next_cursor"] is None:
                self.saved = datetime.fromisoformat(body["high_watermark"])  # after the last page
                return True
            if stop_after is not None and pages >= stop_after:
                return False  # interrupted: the watermark is not saved
            if rng is not None:
                time.sleep(rng.uniform(0, 0.02))
            body = self._page({**params, "cursor": body["next_cursor"]})
            pages += 1


def _writer(seed: int, stop: threading.Event, errors: list[BaseException]) -> None:
    from erp.db import get_sessionmaker

    rng = random.Random(seed)
    today = today_cairo()
    try:
        while not stop.is_set():
            with get_sessionmaker()() as session:
                day = today - timedelta(days=rng.randint(0, 20))
                session.execute(
                    text(
                        "INSERT INTO daily_sales "
                        "(product_id, business_date, units_sold, units_returned, day_status, updated_at) "
                        "VALUES (:p, :d, :s, 0, :status, :u) "
                        "ON CONFLICT (product_id, business_date) DO UPDATE SET "
                        "units_sold = EXCLUDED.units_sold, updated_at = EXCLUDED.updated_at"
                    ),
                    {
                        "p": rng.choice(PRODUCTS),
                        "d": day,
                        "s": rng.randint(0, 500),
                        "status": "open" if day == today else "closed",
                        "u": now_utc(),
                    },
                )
                time.sleep(rng.uniform(0, 0.4))  # a commit delay, well inside the 1 s limit
                session.commit()
            time.sleep(rng.uniform(0, 0.01))
    except BaseException as exc:  # noqa: BLE001  (reported by the test)
        errors.append(exc)


def test_fifty_interrupted_polls_miss_no_change(
    client: TestClient, db: Session, catalog: None, canon_headers: dict[str, str]
) -> None:
    rng = random.Random(20261202)
    brain = Brain(client, canon_headers)
    stop = threading.Event()
    errors: list[BaseException] = []
    with transaction_limit(1):
        # One writer: two writers racing on one row could commit an older updated_at over a
        # newer one, which the Brain (rightly) refuses to apply. That race is not under test.
        writers = [threading.Thread(target=_writer, args=(1, stop, errors))]
        for thread in writers:
            thread.start()
        try:
            interrupted = 0
            for _ in range(50):
                stop_after = rng.randint(1, 3) if rng.random() < 0.4 else None
                interrupted += not brain.poll(rng, stop_after)
                time.sleep(rng.uniform(0, 0.15))
        finally:
            stop.set()
            for thread in writers:
                thread.join()
        assert not errors, errors
        assert interrupted > 0
        # One more poll, resuming from the saved watermark like every other.
        assert brain.saved is not None
        assert brain.poll()

    db.expire_all()
    table = {(r.product_id, r.business_date.isoformat()): r for r in db.scalars(select(DailySales))}
    missed = [
        pair
        for pair, row in table.items()
        if pair not in brain.copy
        or brain.copy[pair]["units_sold"] != row.units_sold
        or datetime.fromisoformat(brain.copy[pair]["updated_at"]) != row.updated_at
    ]
    assert len(table) > 10
    assert missed == []


def test_a_write_held_open_past_the_watermark_is_returned_next_time(
    client: TestClient, db: Session, catalog: None, canon_headers: dict[str, str]
) -> None:
    from erp.db import get_sessionmaker

    today = today_cairo()
    db.add(
        DailySales(
            product_id="P001",
            business_date=today,
            units_sold=1,
            units_returned=0,
            day_status="open",
        )
    )
    db.commit()
    brain = Brain(client, canon_headers)
    assert brain.poll()

    writer = get_sessionmaker()()
    try:
        writer.execute(
            text(
                "UPDATE daily_sales SET units_sold = 42, updated_at = :u "
                "WHERE product_id = 'P001' AND business_date = :d"
            ),
            {"u": now_utc(), "d": today},
        )
        time.sleep(0.05)
        assert brain.poll()  # its watermark is later than the uncommitted updated_at
        assert brain.copy[("P001", today.isoformat())]["units_sold"] == 1
        writer.commit()
    finally:
        writer.close()

    assert brain.poll()
    assert brain.copy[("P001", today.isoformat())]["units_sold"] == 42


def test_every_page_of_a_poll_carries_the_first_pages_watermark(
    client: TestClient, db: Session, catalog: None, canon_headers: dict[str, str]
) -> None:
    today = today_cairo()
    for back in range(3):
        db.add(
            DailySales(
                product_id="P001",
                business_date=today - timedelta(days=back),
                units_sold=back,
                units_returned=0,
                day_status="open" if back == 0 else "closed",
            )
        )
    db.commit()
    params = {**_window(), "limit": 1}
    first = client.get(f"{CANON}/sales", params=params, headers=canon_headers).json()
    time.sleep(3)
    second = client.get(
        f"{CANON}/sales", params={**params, "cursor": first["next_cursor"]}, headers=canon_headers
    ).json()
    assert second["high_watermark"] == first["high_watermark"]
