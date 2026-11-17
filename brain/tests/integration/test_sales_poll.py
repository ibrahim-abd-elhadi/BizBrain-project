"""The sales poll (US1 scenarios 1-8; README 3.2; FR-005 to FR-008). Written before the code."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from brain.clock import today_cairo

from fakes import TOKEN, FakeCanonical, sales_row


@pytest.fixture
def clock_now() -> dict[str, datetime]:
    return {"now": datetime.now(UTC).replace(microsecond=0)}


@pytest.fixture
def fake(pg, clock_now, monkeypatch) -> FakeCanonical:
    fake = FakeCanonical(now=lambda: clock_now["now"])
    fake.load_seed(today_cairo(), clock_now["now"] - timedelta(hours=1))
    monkeypatch.setattr("brain.canonical.client.TEST_TRANSPORT", fake.transport())
    return fake


def _rows(session):
    from brain.models import SalesDaily

    session.expire_all()
    return {(r.product_id, r.business_date): r for r in session.scalars(select(SalesDaily))}


def _watermark(session):
    from brain.models import PollState

    session.expire_all()
    state = session.get(PollState, 1)
    return state.high_watermark if state else None


def _poll() -> int:
    from brain.jobs.registry import run_job

    return run_job("sales-poll", trigger="manual")


def test_the_first_poll_copies_the_whole_window(fake, worker_session, clock_now) -> None:
    assert _poll() == 0
    rows = _rows(worker_session)
    assert len(rows) == 1800
    first = fake.sales_queries()[0]
    assert first["from"] == (today_cairo() - timedelta(days=120)).isoformat()
    assert "updated_since" not in first
    sample = rows[("P003", today_cairo() - timedelta(days=1))]
    erp = fake.sales[("P003", (today_cairo() - timedelta(days=1)).isoformat())]
    assert (sample.units_sold, sample.units_returned, sample.net_units, sample.day_status) == (
        erp["units_sold"],
        erp["units_returned"],
        erp["net_units"],
        "closed",
    )
    assert _watermark(worker_session) == clock_now["now"]


def test_the_next_poll_asks_from_the_watermark_minus_120_s(fake, worker_session, clock_now) -> None:
    assert _poll() == 0
    watermark = _watermark(worker_session)
    fake.requests.clear()
    clock_now["now"] += timedelta(minutes=5)
    assert _poll() == 0
    since = datetime.fromisoformat(fake.sales_queries()[0]["updated_since"])
    assert since == watermark - timedelta(seconds=120)


def test_totals_are_replaced_not_added_and_older_never_wins(fake, worker_session, clock_now) -> None:
    today = today_cairo()
    t1 = clock_now["now"]
    fake.put_sales(sales_row("P001", today, 10, 1, "open", t1))
    assert _poll() == 0
    first = _rows(worker_session)[("P001", today)]
    first_changed = first.changed_at

    clock_now["now"] += timedelta(minutes=5)
    fake.put_sales(sales_row("P001", today, 25, 2, "open", t1 + timedelta(minutes=3)))
    assert _poll() == 0
    row = _rows(worker_session)[("P001", today)]
    assert (row.units_sold, row.units_returned, row.net_units) == (25, 2, 23)
    assert row.changed_at > first_changed

    # A re-read of the same version changes nothing; an older version never overwrites.
    clock_now["now"] += timedelta(minutes=5)
    fake.put_sales(sales_row("P001", today, 99, 0, "open", t1 + timedelta(minutes=1)))
    fake.sales[("P001", today.isoformat())]["updated_at"] = (t1 + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    assert _poll() == 0
    again = _rows(worker_session)[("P001", today)]
    assert (again.units_sold, again.changed_at) == (25, row.changed_at)


def test_a_poll_that_fails_halfway_keeps_the_old_watermark(fake, worker_session, clock_now, settings_override) -> None:
    settings_override(BRAIN_POLL_PAGE_LIMIT="500")
    fake.fail["sales_page_2"] = 503
    assert _poll() == 1
    assert _watermark(worker_session) is None
    assert len(_rows(worker_session)) == 500  # page 1 was stored
    fake.fail.clear()
    fake.requests.clear()
    assert _poll() == 0
    assert "updated_since" not in fake.sales_queries()[0]  # started from the old (no) watermark
    assert len(_rows(worker_session)) == 1800


def test_a_closed_day_arrives_closed(fake, worker_session, clock_now) -> None:
    today = today_cairo()
    fake.put_sales(sales_row("P002", today, 5, 0, "open", clock_now["now"] - timedelta(minutes=10)))
    assert _poll() == 0
    clock_now["now"] += timedelta(minutes=5)
    fake.put_sales(sales_row("P002", today, 5, 0, "closed", clock_now["now"] - timedelta(seconds=30)))
    assert _poll() == 0
    assert _rows(worker_session)[("P002", today)].day_status == "closed"


def test_a_refused_token_stores_nothing(fake, worker_session, caplog, tmp_path: Path, settings_override) -> None:
    from brain.models import JobRun

    bad = tmp_path / "token"
    bad.write_text("expired-token", encoding="utf-8")
    settings_override(BRAIN_ERP_SERVICE_TOKEN_FILE=str(bad))
    assert _poll() == 1
    assert _rows(worker_session) == {} and _watermark(worker_session) is None
    run = worker_session.scalars(select(JobRun)).one()
    assert run.status == "failed" and "GET /sales" in run.summary["error"] and "401" in run.summary["error"]
    assert "expired-token" not in caplog.text and TOKEN not in caplog.text


def test_a_missing_token_file_sends_nothing_and_recovers(fake, worker_session, tmp_path: Path, settings_override) -> None:
    from brain.models import JobRun

    missing = tmp_path / "gone" / "brain_service_token"
    settings_override(BRAIN_ERP_SERVICE_TOKEN_FILE=str(missing))
    assert _poll() == 1
    assert fake.requests == []
    run = worker_session.scalars(select(JobRun)).one()
    assert str(missing) in run.summary["error"]
    missing.parent.mkdir()
    missing.write_text(TOKEN, encoding="utf-8")
    assert _poll() == 0
    assert worker_session.scalar(select(func.count()).select_from(JobRun)) == 2


def test_the_summary_counts_only_rows_that_changed(fake, worker_session, clock_now) -> None:
    from brain.canonical.client import CanonicalClient
    from brain.config import get_settings
    from brain.sales.poll import poll_sales

    settings = get_settings()
    with CanonicalClient.from_settings(settings) as client:
        first = poll_sales(client, settings)
        assert (first["rows"], first["changed"]) == (1800, 1800)
        # The next poll re-reads inside the 120 s overlap; only the new open total changes.
        clock_now["now"] += timedelta(seconds=30)
        fake.put_sales(sales_row("P002", today_cairo(), 4, 0, "open", clock_now["now"]))
        second = poll_sales(client, settings)
        assert second["changed"] == 1
