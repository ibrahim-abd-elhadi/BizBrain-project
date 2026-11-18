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


@pytest.mark.slow
def test_proposal_reads_are_fast(first_night, api_client, manager, api_session) -> None:
    """SC-007: with 50 proposals, the list and a detail answer in well under the 2 s page budget."""
    from brain.proposals import create_proposal

    created = []
    for n in range(50):
        proposal = create_proposal(
            api_session,
            supplier_id="S001",
            lines=[{"product_id": f"P{100 + n:03d}", "quantity": 1 + n}],
            origin="assistant",
        )
        created.append(proposal.id)
    api_session.commit()
    for path in ("/api/v1/brain/proposals", f"/api/v1/brain/proposals/{created[0]}"):
        api_client.get(path, headers=manager)
        timings = []
        for _ in range(5):
            started = time.perf_counter()
            response = api_client.get(path, headers=manager)
            timings.append(time.perf_counter() - started)
            assert response.status_code == 200
        assert statistics.median(timings) < 0.3, (path, timings)
    assert len(api_client.get("/api/v1/brain/proposals", headers=manager).json()["items"]) == 50
