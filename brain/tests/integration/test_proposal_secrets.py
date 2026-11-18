"""No secret leaks from the approval flow (feature 004 FR-028): the service token, the
Authorization header and the stored request body never reach a log, a stored reason or a
response."""

import json
import logging

from sqlalchemy import text

from fakes import TOKEN

PROPOSALS = "/api/v1/brain/proposals"


def _propose_and_approve(api_client, manager, product: str) -> dict:
    items = api_client.get("/api/v1/brain/risk", headers=manager).json()["items"]
    rec = next(r for r in items if r["product_id"] == product)["recommendation_id"]
    proposal = api_client.post(PROPOSALS, headers=manager, json={"recommendation_id": rec}).json()
    return api_client.post(
        f"{PROPOSALS}/{proposal['id']}/approve",
        headers=manager,
        json={"arguments_sha256": proposal["arguments_sha256"]},
    ).json()


def test_no_token_in_logs_reasons_or_responses(
    first_night, api_client, manager, worker_session, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    first_night.fail["create_po"] = 401
    refused = _propose_and_approve(api_client, manager, "P003")
    first_night.fail["create_po"] = "timeout"
    unclear = _propose_and_approve(api_client, manager, "P011")
    assert (refused["status"], unclear["status"]) == ("failed", "uncertain")

    texts = [record.getMessage() for record in caplog.records]
    texts += [json.dumps(refused), json.dumps(unclear)]
    texts += [json.dumps(api_client.get(PROPOSALS, headers=manager).json())]
    texts += [
        str(v)
        for row in worker_session.execute(
            text(
                "SELECT failure_reason, failure_code FROM proposal UNION ALL"
                " SELECT detail, erp_code FROM proposal_attempt"
            )
        )
        for v in row
        if v is not None
    ]
    for value in texts:
        assert TOKEN not in value and "Bearer" not in value, value


def test_the_stored_request_body_is_never_returned(first_night, api_client, manager) -> None:
    body = _propose_and_approve(api_client, manager, "P003")
    detail = api_client.get(f"{PROPOSALS}/{body['id']}", headers=manager).json()
    assert "request_body" not in detail and "request_body" not in body
    listed = api_client.get(PROPOSALS, headers=manager).json()["items"]
    assert all("request_body" not in item for item in listed)
