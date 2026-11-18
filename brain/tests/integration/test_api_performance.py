"""SC-009 on the API side: after a fake first night, each Brain read answers in well under the
2-second page budget (median of 5 calls under 0.3 s)."""

import statistics
import time

import pytest

PATHS = ("/api/v1/brain/risk", "/api/v1/brain/forecasts", "/api/v1/brain/forecasts/P003")


@pytest.mark.slow
def test_reads_are_fast(first_night, api_client, manager) -> None:
    for path in PATHS:
        api_client.get(path, headers=manager)  # warm the connection pool
        timings = []
        for _ in range(5):
            started = time.perf_counter()
            assert api_client.get(path, headers=manager).status_code == 200
            timings.append(time.perf_counter() - started)
        assert statistics.median(timings) < 0.3, (path, timings)
