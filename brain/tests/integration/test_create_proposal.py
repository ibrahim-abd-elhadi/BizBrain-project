"""Turn a recommendation into a proposal (feature 004 US1 scenarios 1-9; FR-001 to FR-008, FR-023;
SC-001, SC-002). Written before the implementation."""

import hashlib
import json

import rfc8785
from sqlalchemy import text

PROPOSALS = "/api/v1/brain/proposals"


def _risk_rows(api_client, manager) -> dict:
    items = api_client.get("/api/v1/brain/risk", headers=manager).json()["items"]
    return {r["product_id"]: r for r in items}


def _create(api_client, manager, recommendation_id):
    return api_client.post(
        PROPOSALS, headers=manager, json={"recommendation_id": recommendation_id}
    )


def test_a_proposal_from_p003s_recommendation(first_night, api_client, manager) -> None:
    rows = _risk_rows(api_client, manager)
    p003 = rows["P003"]
    assert p003["live_proposal"] is None and p003["order_qty"] > 0
    response = _create(api_client, manager, p003["recommendation_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["synthetic"] is True and body["action"] == "create_purchase_order"
    assert body["status"] == "awaiting_approval" and body["origin"] == "recommendation"
    assert (body["supplier_id"], body["supplier_name"]) == ("S004", "Delta Health Trading")
    assert body["arguments"] == {
        "supplier_id": "S004",
        "lines": [{"product_id": "P003", "quantity": p003["order_qty"]}],
    }
    assert body["recommendation_id"] == p003["recommendation_id"]
    assert body["arguments_sha256"] == hashlib.sha256(rfc8785.dumps(body["arguments"])).hexdigest()
    assert body["purchase_order_id"] is None and body["sending"] is False

    rows = _risk_rows(api_client, manager)
    assert rows["P003"]["live_proposal"] == {"id": body["id"], "status": "awaiting_approval"}
    assert all(r["live_proposal"] is None for p, r in rows.items() if p != "P003")

    listed = api_client.get(PROPOSALS, headers=manager).json()
    assert [p["id"] for p in listed["items"]] == [body["id"]]
    detail = api_client.get(f"{PROPOSALS}/{body['id']}", headers=manager).json()
    assert detail["lines"] == [
        {
            "product_id": "P003",
            "product_name": "Amoxicillin 500 mg capsules",
            "quantity": p003["order_qty"],
        }
    ]
    assert detail["recommendation"]["recommendation_id"] == p003["recommendation_id"]
    assert detail["recommendation"]["order_qty"] == p003["order_qty"]
    assert detail["approval"] is None and detail["attempts"] == [] and detail["failure"] is None
    assert first_night.post_requests() == []  # nothing reached the ERP


def test_one_live_proposal_per_product(first_night, api_client, manager, worker_session) -> None:
    rec = _risk_rows(api_client, manager)["P003"]["recommendation_id"]
    first = _create(api_client, manager, rec).json()
    second = _create(api_client, manager, rec)
    assert second.status_code == 409
    assert (
        second.json()["code"] == "PROPOSAL_PENDING" and second.json()["proposal_id"] == first["id"]
    )
    worker_session.execute(
        text("UPDATE proposal SET status = 'rejected', closed_at = now() WHERE id = :id"),
        {"id": first["id"]},
    )
    worker_session.commit()
    assert _create(api_client, manager, rec).status_code == 201


def test_no_order_means_no_proposal(first_night, api_client, manager) -> None:
    rows = _risk_rows(api_client, manager)
    zero = next(r for r in rows.values() if r["order_qty"] == 0)
    response = _create(api_client, manager, zero["recommendation_id"])
    assert response.status_code == 422 and response.json()["code"] == "NO_ORDER_RECOMMENDED"


def test_a_reason_code_means_no_proposal(fake_erp, api_client, manager) -> None:
    from brain.jobs.registry import run_job

    fake_erp.fail["purchase_orders"] = 503
    assert run_job("end-of-day", "manual") == 0
    rec = _risk_rows(api_client, manager)["P003"]
    assert rec["reason_code"] == "OPEN_PO_UNAVAILABLE"
    response = _create(api_client, manager, rec["recommendation_id"])
    assert response.status_code == 422 and response.json()["code"] == "NO_ORDER_RECOMMENDED"
    assert "open orders" in response.json()["detail"].lower()


def test_an_older_recommendation_is_refused(
    first_night, api_client, manager, worker_session
) -> None:
    from brain.jobs.registry import run_job

    old = _risk_rows(api_client, manager)["P003"]["recommendation_id"]
    assert run_job("end-of-day", "manual") == 0  # writes a newer recommendation for every product
    response = _create(api_client, manager, old)
    assert response.status_code == 409 and response.json()["code"] == "RECOMMENDATION_CHANGED"
    assert response.json()["detail"] == "the recommendation changed; reload to see the new quantity"
    assert worker_session.scalar(text("SELECT count(*) FROM proposal")) == 0
    newer = _risk_rows(api_client, manager)["P003"]["recommendation_id"]
    assert _create(api_client, manager, newer).status_code == 201


def test_product_data_read_after_the_recommendation_is_refused(
    first_night, api_client, manager, worker_session
) -> None:
    rec = _risk_rows(api_client, manager)["P003"]["recommendation_id"]
    worker_session.execute(
        text(
            "UPDATE product_ref SET product_read_at = product_read_at + interval '1 minute'"
            " WHERE product_id = 'P003'"
        )
    )
    worker_session.commit()
    response = _create(api_client, manager, rec)
    assert response.status_code == 409 and response.json()["code"] == "RECOMMENDATION_CHANGED"
    assert worker_session.scalar(text("SELECT count(*) FROM proposal")) == 0


def test_unknown_and_malformed_ids(first_night, api_client, manager) -> None:
    missing = _create(api_client, manager, "00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    for bad in ("not-a-uuid", 7, None):
        response = api_client.post(PROPOSALS, headers=manager, json={"recommendation_id": bad})
        assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
    assert api_client.post(PROPOSALS, headers=manager, json={}).status_code == 422
    assert api_client.get(f"{PROPOSALS}/nope", headers=manager).status_code == 422
    assert (
        api_client.get(
            f"{PROPOSALS}/00000000-0000-4000-8000-000000000000", headers=manager
        ).status_code
        == 404
    )


def test_two_products_two_proposals(first_night, api_client, manager) -> None:
    rows = _risk_rows(api_client, manager)
    a = _create(api_client, manager, rows["P003"]["recommendation_id"]).json()
    b = _create(api_client, manager, rows["P011"]["recommendation_id"]).json()
    assert a["id"] != b["id"]
    assert [line["product_id"] for line in a["arguments"]["lines"]] == ["P003"]
    assert [line["product_id"] for line in b["arguments"]["lines"]] == ["P011"]
    assert a["supplier_id"] == "S004" and b["supplier_id"] == "S003"


def test_the_stored_canonical_text_is_what_was_hashed(
    first_night, api_client, manager, worker_session
) -> None:
    rec = _risk_rows(api_client, manager)["P017"]["recommendation_id"]
    body = _create(api_client, manager, rec).json()
    canonical, sha = worker_session.execute(
        text("SELECT arguments_canonical, arguments_sha256 FROM proposal WHERE id = :id"),
        {"id": body["id"]},
    ).one()
    assert canonical.encode() == rfc8785.dumps(json.loads(canonical))
    assert hashlib.sha256(canonical.encode()).hexdigest() == sha == body["arguments_sha256"]


def test_sign_in_is_required(first_night, api_client, sign) -> None:
    assert api_client.post(PROPOSALS, json={"recommendation_id": "x"}).status_code == 401
    service = {"Authorization": f"Bearer {sign(aud='bizbrain-canonical')}"}
    assert api_client.get(PROPOSALS, headers=service).status_code == 401
