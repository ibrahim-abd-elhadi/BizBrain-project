"""The Canonical client (FR-001, research R-02). Written before the implementation."""

import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from brain.canonical.client import CanonicalClient, CanonicalNotFound, CanonicalUnavailable

from fakes import TOKEN, FakeCanonical, purchase_order, sales_row

TODAY = date(2026, 11, 18)


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "brain_service_token"
    path.write_text(TOKEN + "\n", encoding="utf-8")
    return path


@pytest.fixture
def fake() -> FakeCanonical:
    fake = FakeCanonical(now=lambda: datetime(2026, 11, 18, 8, 0, tzinfo=UTC))
    return fake.load_seed(TODAY, datetime(2026, 11, 17, 18, 0, tzinfo=UTC))


def _client(fake: FakeCanonical, token_file: Path) -> CanonicalClient:
    return CanonicalClient("http://erp.test", token_file, timeout=10, transport=fake.transport())


def test_each_call_sends_the_token_and_parses_the_document(
    fake: FakeCanonical, token_file: Path
) -> None:
    fake.open_orders.append(purchase_order(7, "S004", {"P003": 24}))
    client = _client(fake, token_file)
    page = client.sales_page(TODAY.replace(day=1), TODAY, None, None, 5)
    assert len(page.items) == 5 and page.next_cursor is not None
    assert client.product("P003").pack_multiple == 12
    assert client.inventory("P003").available == client.inventory("P003").on_hand
    assert client.supplier("S004").lead_time_days == 7
    assert client.open_purchase_orders("P003") == 24
    assert client.open_purchase_orders("P001") == 0
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in fake.requests)


def test_the_token_file_is_read_when_the_client_is_created(
    fake: FakeCanonical, token_file: Path
) -> None:
    token_file.write_text("old-token", encoding="utf-8")
    with pytest.raises(CanonicalUnavailable, match="401"):
        _client(fake, token_file).product("P003")
    token_file.write_text(TOKEN, encoding="utf-8")
    assert _client(fake, token_file).product("P003").product_id == "P003"


def test_a_missing_token_file_is_named_not_read(fake: FakeCanonical, tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "brain_service_token"
    with pytest.raises(CanonicalUnavailable, match=str(missing).replace("\\", "\\\\")):
        _client(fake, missing)
    assert fake.requests == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "401"), (503, "503"), ("timeout", "timeout")],
)
def test_failures_name_the_operation_and_never_the_token(
    fake: FakeCanonical, token_file: Path, caplog, status, expected
) -> None:
    fake.fail["supplier"] = status
    with caplog.at_level(logging.DEBUG), pytest.raises(CanonicalUnavailable) as caught:
        _client(fake, token_file).supplier("S004")
    assert "GET /suppliers" in str(caught.value) and expected in str(caught.value)
    assert TOKEN not in str(caught.value)
    assert TOKEN not in caplog.text


def test_not_found_is_its_own_error(fake: FakeCanonical, token_file: Path) -> None:
    with pytest.raises(CanonicalNotFound):
        _client(fake, token_file).product("P999")


def test_sales_rows_are_parsed(fake: FakeCanonical, token_file: Path) -> None:
    fake.put_sales(sales_row("P001", TODAY, 9, 1, "open", datetime(2026, 11, 18, 7, tzinfo=UTC)))
    page = _client(fake, token_file).sales_page(TODAY, TODAY, None, None, 500)
    assert [(r.product_id, r.net_units, r.day_status) for r in page.items] == [("P001", 8, "open")]
    assert page.high_watermark == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
