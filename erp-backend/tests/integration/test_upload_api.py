"""Upload CSV: replace today's totals from a file (FR-013, FR-014, FR-026).

Written before the implementation. "Today" is 2026-11-18 in Cairo throughout.
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from erp.models import DailySales, Stock

BASE = "/api/v1/erp"
NOW = "2026-11-18T10:00"
TODAY = date(2026, 11, 18)
HEADER = "business_date,product_id,units_sold,units_returned"

# The example from contracts/sales-upload-csv.md.
CONTRACT_EXAMPLE = f"""{HEADER}
2026-11-18,P001,15,1
2026-11-18,P002,7,0
2026-11-17,P003,4,0
2026-11-18,P999,3,0
2026-11-18,P002,9,1
"""


def upload(client: TestClient, headers: dict[str, str], text: str | bytes):
    data = text.encode() if isinstance(text, str) else text
    return client.post(
        f"{BASE}/sales/upload", files={"file": ("totals.csv", data, "text/csv")}, headers=headers
    )


def row_for(db: Session, product_id: str, day: date = TODAY) -> DailySales | None:
    db.expire_all()
    return db.scalars(
        select(DailySales).where(
            DailySales.product_id == product_id, DailySales.business_date == day
        )
    ).one_or_none()


def on_hand(db: Session, product_id: str) -> int:
    db.expire_all()
    return db.scalar(select(Stock.on_hand).where(Stock.product_id == product_id))  # type: ignore[return-value]


def set_stock(db: Session, product_id: str, value: int) -> None:
    db.execute(update(Stock).where(Stock.product_id == product_id).values(on_hand=value))
    db.commit()


def test_the_contract_example_gives_the_documented_lists(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        response = upload(client, login(), CONTRACT_EXAMPLE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["business_date"] == "2026-11-18"
    assert [(a["row"], a["product_id"]) for a in body["accepted"]] == [(2, "P001"), (6, "P002")]
    assert body["overridden"] == [{"row": 3, "overridden_by_row": 6}]
    assert [(r["row"], r["code"]) for r in body["refused"]] == [
        (4, "DAY_CLOSED"),
        (5, "UNKNOWN_PRODUCT"),
    ]
    assert all(r["detail"] for r in body["refused"])

    # Valid rows were recorded even though others were refused; the overridden row was not applied.
    p1, p2 = row_for(db, "P001"), row_for(db, "P002")
    assert (p1.units_sold, p1.units_returned, p1.day_status) == (15, 1, "open")  # type: ignore[union-attr]
    assert (p2.units_sold, p2.units_returned) == (9, 1)  # type: ignore[union-attr]
    assert on_hand(db, "P001") == 100 - 14
    assert on_hand(db, "P002") == 100 - 8
    assert db.scalar(select(func.count()).select_from(DailySales)) == 2


def test_a_row_replaces_todays_total_and_stock_moves_by_the_difference(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        db.add(
            DailySales(
                product_id="P001",
                business_date=TODAY,
                units_sold=10,
                units_returned=0,
                day_status="open",
            )
        )
        set_stock(db, "P001", 40)
        response = upload(client, login(), f"{HEADER}\n2026-11-18,P001,15,1\n")

    assert response.status_code == 200
    row = row_for(db, "P001")
    assert (row.units_sold, row.units_returned) == (15, 1)  # type: ignore[union-attr]
    assert on_hand(db, "P001") == 36  # 40 - (14 - 10)


def test_a_smaller_total_puts_stock_back(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        db.add(
            DailySales(
                product_id="P001",
                business_date=TODAY,
                units_sold=30,
                units_returned=0,
                day_status="open",
            )
        )
        set_stock(db, "P001", 10)
        upload(client, login(), f"{HEADER}\n2026-11-18,P001,5,0\n")

    assert on_hand(db, "P001") == 35  # 10 - (5 - 30)
    assert row_for(db, "P001").units_sold == 5  # type: ignore[union-attr]


def test_a_total_the_stock_cannot_cover_is_refused_and_changes_nothing(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        set_stock(db, "P001", 3)
        body = upload(client, login(), f"{HEADER}\n2026-11-18,P001,10,0\n").json()

    assert [(r["row"], r["code"]) for r in body["refused"]] == [(2, "STOCK_BELOW_ZERO")]
    assert body["accepted"] == []
    assert row_for(db, "P001") is None
    assert on_hand(db, "P001") == 3


def test_a_future_date_is_refused(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        body = upload(client, login(), f"{HEADER}\n2026-11-19,P001,5,0\n").json()
    assert [(r["row"], r["code"]) for r in body["refused"]] == [(2, "FUTURE_DATE")]
    assert row_for(db, "P001", date(2026, 11, 19)) is None


def test_a_bad_header_refuses_the_whole_file_and_nothing_is_recorded(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        response = upload(client, login(), "date,product,sold,returned\n2026-11-18,P001,5,0\n")
    assert response.status_code == 422
    assert response.json()["code"] == "BAD_HEADER"
    assert response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(DailySales)) == 0
    assert on_hand(db, "P001") == 100


def test_other_whole_file_refusals_come_back_as_422(
    client: TestClient, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        headers = login()
        assert upload(client, headers, HEADER + "\n").json()["code"] == "EMPTY_FILE"
        assert upload(client, headers, b"x" * 1_048_577).json()["code"] == "FILE_TOO_LARGE"
        assert upload(client, headers, HEADER.encode() + b"\n\xff\n").json()["code"] == "NOT_UTF8"
        many = HEADER + "\n" + "2026-11-18,P001,0,0\n" * 5001
        assert upload(client, headers, many).json()["code"] == "TOO_MANY_ROWS"
        missing = client.post(f"{BASE}/sales/upload", headers=headers)
        assert missing.status_code == 422
        assert missing.json()["code"] == "VALIDATION_ERROR"


def test_closed_days_are_not_touched(
    client: TestClient, db: Session, manager: str, catalog: None, at_cairo, login
) -> None:
    with at_cairo(NOW):
        db.add(
            DailySales(
                product_id="P001",
                business_date=date(2026, 11, 17),
                units_sold=8,
                units_returned=0,
                day_status="closed",
            )
        )
        db.commit()
        body = upload(client, login(), f"{HEADER}\n2026-11-17,P001,99,0\n").json()
    assert body["refused"][0]["code"] == "DAY_CLOSED"
    assert row_for(db, "P001", date(2026, 11, 17)).units_sold == 8  # type: ignore[union-attr]


def test_upload_needs_a_token(client: TestClient, db: Session, manager: str, catalog: None) -> None:
    response = client.post(
        f"{BASE}/sales/upload",
        files={"file": ("totals.csv", CONTRACT_EXAMPLE.encode(), "text/csv")},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert db.scalar(select(func.count()).select_from(DailySales)) == 0
