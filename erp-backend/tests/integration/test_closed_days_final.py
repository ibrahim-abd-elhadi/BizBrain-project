"""SC-006: once a day is closed, its units never change again, before or after Cairo midnight."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.models import DailySales

BASE = "/api/v1/erp"
HEADER = "business_date,product_id,units_sold,units_returned"
SEEDED_AT = "2026-11-18T10:00"  # history ends 2026-11-17
AFTER_MIDNIGHT = "2026-11-19T00:05"


def closed_rows(db: Session) -> dict[tuple[str, date], tuple[int, int]]:
    db.expire_all()
    rows = db.scalars(select(DailySales).where(DailySales.day_status == "closed"))
    return {(r.product_id, r.business_date): (r.units_sold, r.units_returned) for r in rows}


def hammer(client: TestClient, headers: dict[str, str], dates: list[str]) -> None:
    """Everything a manager can do to daily totals: simulate (with a spike), upload past dates."""
    assert client.post(f"{BASE}/sales/simulate", json={}, headers=headers).status_code == 200
    spike = client.post(
        f"{BASE}/sales/simulate", json={"spike_product_id": "P001"}, headers=headers
    )
    assert spike.status_code == 200
    csv = "\n".join([HEADER, *(f"{d},{p},999,0" for d in dates for p in ("P001", "P002", "P003"))])
    result = client.post(
        f"{BASE}/sales/upload", files={"file": ("t.csv", csv.encode(), "text/csv")}, headers=headers
    ).json()
    assert {r["code"] for r in result["refused"]} == {"DAY_CLOSED"}
    assert result["accepted"] == []


def test_closed_rows_never_change(client: TestClient, db: Session, at_cairo, seed, login) -> None:
    with at_cairo(SEEDED_AT):
        seed()
        first = closed_rows(db)
        assert len(first) == 1800

        headers = login()
        hammer(client, headers, ["2026-11-17", "2026-11-10", "2026-08-20"])
        assert first.items() <= closed_rows(db).items()

    # Past Cairo midnight: today's open rows (2026-11-18) become closed, and are then final too.
    with at_cairo(AFTER_MIDNIGHT):
        headers = login()
        client.get(f"{BASE}/sales", headers=headers)  # closing happens on first access
        second = closed_rows(db)
        assert first.items() <= second.items()
        assert any(day == date(2026, 11, 18) for _, day in second), "yesterday should now be closed"

        hammer(client, headers, ["2026-11-18", "2026-11-17"])
        after = closed_rows(db)
        assert second.items() <= after.items()
        assert first.items() <= after.items()
        # The only closed rows that appeared are for days that ended; no 11-19 row is closed.
        assert not any(day == date(2026, 11, 19) for _, day in after)
