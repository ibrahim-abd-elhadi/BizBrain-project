"""Performance targets on the seeded data (research R-27). Marked slow; run with the rest by default."""

import statistics
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from erp.models import Stock

BASE = "/api/v1/erp"
HEADER = "business_date,product_id,units_sold,units_returned"

pytestmark = pytest.mark.slow


def test_sales_list_simulate_and_upload_are_fast_enough(
    client: TestClient, db: Session, at_cairo, seed, login
) -> None:
    with at_cairo("2026-11-18T10:00"):
        seed()
        db.execute(update(Stock).values(on_hand=1_000_000))  # nothing is capped or refused
        db.commit()
        headers = login()

        timings = []
        for _ in range(20):
            started = time.perf_counter()
            response = client.get(f"{BASE}/sales", headers=headers)
            timings.append(time.perf_counter() - started)
            assert response.status_code == 200
        assert len(response.json()["items"]) == 1800
        assert statistics.median(timings) < 0.3, f"median {statistics.median(timings):.3f}s"

        started = time.perf_counter()
        assert client.post(f"{BASE}/sales/simulate", json={}, headers=headers).status_code == 200
        simulate = time.perf_counter() - started
        assert simulate < 1.0, f"simulate took {simulate:.2f}s"

        rows = [f"2026-11-18,P{(i % 20) + 1:03d},{i % 50},{i % 3}" for i in range(5000)]
        data = ("\n".join([HEADER, *rows]) + "\n").encode()
        started = time.perf_counter()
        response = client.post(
            f"{BASE}/sales/upload", files={"file": ("big.csv", data, "text/csv")}, headers=headers
        )
        upload = time.perf_counter() - started
        assert response.status_code == 200, response.text
        assert len(response.json()["overridden"]) == 4980  # 5,000 rows over 20 products
        assert upload < 5.0, f"upload took {upload:.2f}s"
