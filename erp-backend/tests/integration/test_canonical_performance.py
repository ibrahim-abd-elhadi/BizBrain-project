"""SC-007 on the seeded data: a 500-row sales page in under 1 s; a product, stock, supplier or
open-orders read in under 0.3 s. Marked slow, like feature 001's performance test."""

import statistics
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from canonical_support import CANON

pytestmark = pytest.mark.slow


def _median_seconds(client: TestClient, path: str, headers: dict[str, str]) -> float:
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        response = client.get(f"{CANON}/{path}", headers=headers)
        timings.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
    return statistics.median(timings)


def test_canonical_reads_are_fast_enough(client: TestClient, at_cairo, seed, service_token) -> None:
    with at_cairo("2026-11-18T10:00") as clock:
        seed()
        clock.shift(timedelta(minutes=5))
        headers = {"Authorization": f"Bearer {service_token()}"}
        sales = _median_seconds(client, "sales?from=2026-08-20&to=2026-11-18&limit=500", headers)
        reads = {
            path: _median_seconds(client, path, headers)
            for path in (
                "products/P003",
                "inventory/P003",
                "suppliers/S004",
                "purchase-orders?status=open&product_id=P003",
            )
        }
    assert sales < 1.0, sales
    for path, seconds in reads.items():
        assert seconds < 0.3, (path, seconds)
