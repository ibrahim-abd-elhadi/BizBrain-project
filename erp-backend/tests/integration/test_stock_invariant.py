"""SC-008: after any sequence of events, on_hand equals what the events say, and is never below 0.

A seeded random run of 200 actions: Simulate Sales (with and without a spike), CSV uploads for
today, confirming drafts inserted by the test, and manual stock sets. The test keeps its own
running figure per product and compares it with the database after every action.
"""

import random
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from erp.models import PurchaseOrder, PurchaseOrderLine

BASE = "/api/v1/erp"
NOW = "2026-11-18T10:00"
TODAY = "2026-11-18"
HEADER = "business_date,product_id,units_sold,units_returned"
ACTIONS = 200


def test_stock_matches_the_events_after_200_random_actions(
    client: TestClient,
    db: Session,
    at_cairo,
    seed,
    login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = random.Random(20261202)
    # Simulate Sales draws from one shared generator, so the whole run is repeatable.
    monkeypatch.setattr("erp.api.sales.random", SimpleNamespace(Random=lambda seed=None: rng))

    with at_cairo(NOW):
        seed()
        headers = login()

        def inventory() -> dict[str, int]:
            rows = client.get(f"{BASE}/inventory", headers=headers).json()
            return {r["product_id"]: r["on_hand"] for r in rows}

        expected = inventory()
        today_net = {p: 0 for p in expected}  # net units already in today's totals
        product_ids = sorted(expected)
        seen = {"capped": 0, "refused_for_stock": 0, "confirmed": 0, "manual": 0, "uploaded": 0}

        for step in range(ACTIONS):
            kind = rng.choice(["simulate", "spike", "upload", "confirm", "set"])

            if kind in ("simulate", "spike"):
                body = {"spike_product_id": rng.choice(product_ids)} if kind == "spike" else {}
                result = client.post(f"{BASE}/sales/simulate", json=body, headers=headers).json()
                for item in result["products"]:
                    net = item["units_sold_added"] - item["units_returned_added"]
                    expected[item["product_id"]] -= net
                    today_net[item["product_id"]] += net
                    seen["capped"] += item["capped_by_stock"]

            elif kind == "upload":
                chosen = rng.sample(product_ids, rng.randint(1, 4))
                lines = [HEADER]
                totals = {}
                for pid in chosen:
                    sold = rng.randint(0, 80)
                    returned = rng.randint(0, min(sold, 5))
                    totals[pid] = (sold, returned)
                    lines.append(f"{TODAY},{pid},{sold},{returned}")
                data = ("\n".join(lines) + "\n").encode()
                result = client.post(
                    f"{BASE}/sales/upload",
                    files={"file": ("t.csv", data, "text/csv")},
                    headers=headers,
                ).json()
                for accepted in result["accepted"]:
                    pid = accepted["product_id"]
                    sold, returned = totals[pid]
                    expected[pid] -= (sold - returned) - today_net[pid]
                    today_net[pid] = sold - returned
                    seen["uploaded"] += 1
                seen["refused_for_stock"] += sum(
                    r["code"] == "STOCK_BELOW_ZERO" for r in result["refused"]
                )

            elif kind == "confirm":
                picked = rng.sample(product_ids, rng.randint(1, 3))
                order = PurchaseOrder(
                    supplier_id="S001",
                    lines=[
                        PurchaseOrderLine(product_id=p, quantity=rng.randint(1, 120))
                        for p in picked
                    ],
                )
                db.add(order)
                db.commit()
                response = client.post(
                    f"{BASE}/purchase-orders/{order.po_id}/confirm", headers=headers
                )
                assert response.status_code == 200
                for line in order.lines:
                    expected[line.product_id] += line.quantity
                seen["confirmed"] += 1

            else:  # a manual set resets the running figure
                pid = rng.choice(product_ids)
                value = rng.randint(0, 40)  # small, so the stock floor is reached often
                assert (
                    client.put(
                        f"{BASE}/inventory/{pid}", json={"on_hand": value}, headers=headers
                    ).status_code
                    == 200
                )
                expected[pid] = value
                seen["manual"] += 1

            actual = inventory()
            assert min(actual.values()) >= 0, f"step {step} ({kind}): negative stock"
            assert actual == expected, f"step {step} ({kind}): stock differs from the events"

    # The run really exercised the awkward paths, not only the easy ones.
    assert seen["capped"] > 0
    assert seen["refused_for_stock"] > 0
    assert seen["confirmed"] > 0 and seen["manual"] > 0 and seen["uploaded"] > 0
