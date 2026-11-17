"""GET /api/v1/canonical/sales (US1 scenarios 1-6, FR-011 to FR-017, Edge Cases).

The clock: with tick=False, now_utc() returns one instant, so a row written in the same frozen
moment as a poll has updated_at == W. Tests therefore seed, then shift the clock forward by more
than 120 s before the first poll; that also keeps the seeded rows out of a later W - 120 s poll.

Written before the implementation.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from erp.models import DailySales

from canonical_support import CANON, assert_error, validate

NOW = "2026-11-18T10:00"
TODAY = date(2026, 11, 18)
FROM = TODAY - timedelta(days=90)
ERP = "/api/v1/erp"
FORBIDDEN_KEYS = {"complete", "coverage", "tenant_id", "location_id", "incomplete_dates"}
HEADER = "business_date,product_id,units_sold,units_returned"

Headers = dict[str, str]


def _get(client: TestClient, headers: Headers, **params: Any):
    params.setdefault("from", FROM.isoformat())
    params.setdefault("to", TODAY.isoformat())
    query = {
        k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in params.items()
    }
    return client.get(f"{CANON}/sales", params=query, headers=headers)


def page(client: TestClient, headers: Headers, **params: Any) -> dict[str, Any]:
    response = _get(client, headers, **params)
    assert response.status_code == 200, response.text
    body = response.json()
    validate("canonical/sales_page.schema.json", body)
    for item in body["items"]:
        assert not FORBIDDEN_KEYS & item.keys()
    assert not FORBIDDEN_KEYS & body.keys()
    return body


def read_all(client: TestClient, headers: Headers, **params: Any) -> list[dict[str, Any]]:
    pages = [page(client, headers, **params)]
    while pages[-1]["next_cursor"] is not None:
        pages.append(page(client, headers, **params, cursor=pages[-1]["next_cursor"]))
    return pages


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


def key(item: dict[str, Any]) -> tuple[datetime, str, str]:
    return instant(item["updated_at"]), item["product_id"], item["business_date"]


def test_full_read_of_the_seed(
    client: TestClient, db: Session, at_cairo, seed: Callable[[], None], service_token
) -> None:
    with at_cairo(NOW) as clock:
        seed()
        clock.shift(timedelta(minutes=5))
        headers = {"Authorization": f"Bearer {service_token()}"}
        pages = read_all(client, headers, limit=500)

    assert [len(p["items"]) for p in pages] == [500, 500, 500, 300]
    assert [p["next_cursor"] is None for p in pages] == [False, False, False, True]
    watermarks = {p["high_watermark"] for p in pages}
    assert len(watermarks) == 1
    watermark = instant(watermarks.pop())
    assert all(instant(i["updated_at"]) < watermark for i in pages[0]["items"])

    items = [item for p in pages for item in p["items"]]
    assert [key(i) for i in items] == sorted(key(i) for i in items)
    pairs = {(i["product_id"], i["business_date"]) for i in items}
    assert len(pairs) == len(items) == 1800

    table = {(r.product_id, r.business_date.isoformat()): r for r in db.scalars(select(DailySales))}
    for item in items:
        row = table[(item["product_id"], item["business_date"])]
        assert (item["units_sold"], item["units_returned"], item["net_units"]) == (
            row.units_sold,
            row.units_returned,
            row.net_units,
        )
        assert item["day_status"] == row.day_status == "closed"
        assert item["updated_at"].endswith("Z")
        assert instant(item["updated_at"]) == row.updated_at


def test_default_limit_is_200(client: TestClient, at_cairo, seed, service_token) -> None:
    with at_cairo(NOW) as clock:
        seed()
        clock.shift(timedelta(minutes=5))
        body = page(client, {"Authorization": f"Bearer {service_token()}"})
    assert len(body["items"]) == 200


def test_simulate_then_poll_returns_only_todays_open_totals(
    client: TestClient, at_cairo, seed, service_token, login
) -> None:
    with at_cairo(NOW) as clock:
        seed()
        clock.shift(timedelta(minutes=5))
        headers = {"Authorization": f"Bearer {service_token()}"}
        watermark = instant(read_all(client, headers, limit=500)[-1]["high_watermark"])
        clock.shift(timedelta(seconds=1))
        response = client.post(f"{ERP}/sales/simulate", json={}, headers=login())
        assert response.status_code == 200, response.text
        clock.shift(timedelta(seconds=1))
        pages = read_all(client, headers, updated_since=watermark - timedelta(seconds=120))

    items = [item for p in pages for item in p["items"]]
    assert items, "Simulate Sales changed nothing?"
    assert {i["business_date"] for i in items} == {TODAY.isoformat()}
    assert {i["day_status"] for i in items} == {"open"}
    simulated = {e["product_id"] for e in response.json()["products"]}
    assert {i["product_id"] for i in items} == simulated


def test_a_day_closing_at_cairo_midnight_reaches_the_next_poll(
    client: TestClient, db: Session, catalog: None, at_cairo, service_token
) -> None:
    with at_cairo("2026-11-17T23:50") as clock:
        db.add(
            DailySales(
                product_id="P001",
                business_date=date(2026, 11, 17),
                units_sold=8,
                units_returned=1,
                day_status="open",
            )
        )
        db.commit()
        clock.shift(timedelta(minutes=1))
        headers = {"Authorization": f"Bearer {service_token()}"}
        first = read_all(client, headers, **{"from": "2026-11-01", "to": "2026-11-18"})
        assert [i["day_status"] for i in first[0]["items"]] == ["open"]
        watermark = instant(first[-1]["high_watermark"])

        # Nobody uses the ERP across midnight; the next poll closes the day itself.
        clock.move_to(datetime(2026, 11, 17, 22, 5, tzinfo=UTC))  # 00:05 Cairo on the 18th
        later = read_all(
            client,
            headers,
            **{"from": "2026-11-01", "to": "2026-11-18"},
            updated_since=watermark - timedelta(seconds=120),
        )

    items = [i for p in later for i in p["items"]]
    assert len(items) == 1
    assert items[0]["day_status"] == "closed"
    assert instant(items[0]["updated_at"]) > watermark


def _upload(client: TestClient, headers: Headers, body: str):
    response = client.post(
        f"{ERP}/sales/upload",
        files={"file": ("totals.csv", body.encode(), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response


def test_a_csv_upload_is_reported_as_absolute_totals_even_when_net_is_negative(
    client: TestClient, catalog: None, manager: str, at_cairo, service_token, login
) -> None:
    with at_cairo(NOW) as clock:
        manager_headers = login()
        _upload(client, manager_headers, f"{HEADER}\n2026-11-18,P001,15,1\n")
        clock.shift(timedelta(minutes=5))
        headers = {"Authorization": f"Bearer {service_token()}"}
        watermark = instant(read_all(client, headers)[-1]["high_watermark"])
        clock.shift(timedelta(seconds=1))
        _upload(client, manager_headers, f"{HEADER}\n2026-11-18,P001,2,5\n")
        clock.shift(timedelta(seconds=1))
        items = [
            i
            for p in read_all(client, headers, updated_since=watermark - timedelta(seconds=120))
            for i in p["items"]
        ]
    assert [
        (i["product_id"], i["units_sold"], i["units_returned"], i["net_units"]) for i in items
    ] == [("P001", 2, 5, -3)]


def test_updated_since_is_exclusive_and_dates_bound_the_rows(
    client: TestClient, db: Session, catalog: None, at_cairo, service_token
) -> None:
    t0 = datetime(2026, 11, 18, 6, 0, 0, 123456, tzinfo=UTC)
    rows = [
        ("P001", date(2026, 11, 10), t0),
        ("P002", date(2026, 11, 10), t0 + timedelta(microseconds=1)),
        ("P001", date(2026, 7, 1), t0 + timedelta(seconds=1)),  # before `from`
    ]
    for product_id, day, updated_at in rows:
        db.add(
            DailySales(
                product_id=product_id,
                business_date=day,
                units_sold=3,
                units_returned=0,
                day_status="closed",
                updated_at=updated_at,
            )
        )
    db.commit()
    with at_cairo(NOW):
        items = page(client, {"Authorization": f"Bearer {service_token()}"}, updated_since=t0)[
            "items"
        ]
    assert [(i["product_id"], i["business_date"]) for i in items] == [("P002", "2026-11-10")]


def test_a_row_changed_during_paging_is_never_skipped(
    client: TestClient, db: Session, at_cairo, seed, service_token
) -> None:
    with at_cairo(NOW) as clock:
        seed()
        clock.shift(timedelta(minutes=5))
        headers = {"Authorization": f"Bearer {service_token()}"}
        first = page(client, headers, limit=500)
        changed = first["items"][10]
        clock.shift(timedelta(seconds=1))
        db.execute(
            update(DailySales)
            .where(
                DailySales.product_id == changed["product_id"],
                DailySales.business_date == date.fromisoformat(changed["business_date"]),
            )
            .values(units_sold=999)
        )
        db.commit()
        rest = [first]
        while rest[-1]["next_cursor"] is not None:
            rest.append(page(client, headers, limit=500, cursor=rest[-1]["next_cursor"]))

    items = [i for p in rest for i in p["items"]]
    assert len({(i["product_id"], i["business_date"]) for i in items}) == 1800
    seen = [
        i
        for i in items
        if (i["product_id"], i["business_date"])
        == (changed["product_id"], changed["business_date"])
    ]
    assert len(seen) == 2 and seen[-1]["units_sold"] == 999
    assert {p["high_watermark"] for p in rest} == {first["high_watermark"]}


def test_updated_since_in_the_future_gives_an_empty_page(
    client: TestClient, catalog: None, at_cairo, service_token
) -> None:
    with at_cairo(NOW):
        body = page(
            client,
            {"Authorization": f"Bearer {service_token()}"},
            updated_since=datetime(2027, 1, 1, tzinfo=UTC),
        )
    assert body["items"] == [] and body["next_cursor"] is None
    assert instant(body["high_watermark"]) == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": None}, "from"),
        ({"to": None}, "to"),
        ({"from": "2026-11-18", "to": "2026-11-17"}, "from"),
        ({"from": "2026-13-01"}, "from"),
        ({"updated_since": "2026-11-17T10:00:00"}, "updated_since"),
        ({"updated_since": "yesterday"}, "updated_since"),
        ({"limit": 0}, "limit"),
        ({"limit": 501}, "limit"),
        ({"cursor": "x" * 513}, "cursor"),
    ],
)
def test_invalid_parameters_are_refused_naming_the_field(
    client: TestClient, catalog: None, canon_headers: Headers, params: dict, field: str
) -> None:
    query = {"from": FROM.isoformat(), "to": TODAY.isoformat(), **params}
    query = {k: v for k, v in query.items() if v is not None}
    response = client.get(f"{CANON}/sales", params=query, headers=canon_headers)
    assert_error(response, 422, "VALIDATION_ERROR", field=field)


def test_tampered_or_reused_cursors_are_refused(
    client: TestClient, db: Session, catalog: None, at_cairo, service_token
) -> None:
    for day in (date(2026, 11, 10), date(2026, 11, 11)):
        db.add(
            DailySales(
                product_id="P001",
                business_date=day,
                units_sold=1,
                units_returned=0,
                day_status="closed",
            )
        )
    db.commit()
    with at_cairo(NOW):
        headers = {"Authorization": f"Bearer {service_token()}"}
        since = datetime(2026, 1, 1, tzinfo=UTC)
        cursor = page(client, headers, limit=1, updated_since=since)["next_cursor"]
        assert cursor is not None
        tampered = cursor[:5] + ("A" if cursor[5] != "A" else "B") + cursor[6:]
        cases = [
            {"cursor": tampered, "updated_since": since},
            {"cursor": cursor, "updated_since": since, "from": "2026-08-21"},
            {"cursor": cursor, "updated_since": since, "to": "2026-11-17"},
            {"cursor": cursor, "updated_since": since + timedelta(seconds=1)},
            {"cursor": cursor},
        ]
        for params in cases:
            assert_error(_get(client, headers, **params), 422, "VALIDATION_ERROR", field="cursor")
        # The same instant written with an offset instead of Z is the same filter.
        same = page(client, headers, cursor=cursor, updated_since="2026-01-01T02:00:00+02:00")
        assert len(same["items"]) == 1
