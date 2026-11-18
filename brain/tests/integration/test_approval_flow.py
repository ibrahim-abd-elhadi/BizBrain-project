"""Review and approve; the Brain sends the draft exactly once (feature 004 US2 scenarios 1-10;
FR-010 to FR-025a; SC-003, SC-004). Written before the implementation."""

import json
import re
import threading
from datetime import datetime

from sqlalchemy import text

from fakes import TOKEN, validate

PROPOSALS = "/api/v1/brain/proposals"


def _risk(api_client, manager) -> dict:
    items = api_client.get("/api/v1/brain/risk", headers=manager).json()["items"]
    return {r["product_id"]: r for r in items}


def _propose(api_client, manager, product="P003") -> dict:
    rec = _risk(api_client, manager)[product]["recommendation_id"]
    response = api_client.post(PROPOSALS, headers=manager, json={"recommendation_id": rec})
    assert response.status_code == 201, response.text
    return response.json()


def _approve(api_client, manager, proposal, sha=None):
    return api_client.post(
        f"{PROPOSALS}/{proposal['id']}/approve",
        headers=manager,
        json={"arguments_sha256": sha or proposal["arguments_sha256"]},
    )


def test_approving_sends_one_draft(first_night, api_client, manager, worker_session) -> None:
    fake = first_night
    proposal = _propose(api_client, manager)
    response = _approve(api_client, manager, proposal)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["status"] == "draft_created"
        and body["purchase_order_id"] == fake.drafts()[0]["purchase_order_id"]
    )
    assert body["approval"]["approved_by"] == "manager" and body["approval"]["approved_at"]
    assert [(a["attempt_no"], a["outcome"], a["http_status"]) for a in body["attempts"]] == [
        (1, "draft_created", 201)
    ]
    assert body["sending"] is False and body["failure"] is None

    # The request the ERP received.
    posts = fake.post_requests()
    assert len(posts) == 1
    headers = posts[0]["headers"]
    assert headers["idempotency-key"] == proposal["id"]
    assert headers["authorization"] == f"Bearer {TOKEN}"
    sent = json.loads(posts[0]["body"])
    validate("canonical/create_draft_po_request.schema.json", sent)
    stored = worker_session.scalar(
        text("SELECT request_body FROM proposal WHERE id = :id"), {"id": proposal["id"]}
    )
    assert posts[0]["body"] == stored.encode("utf-8")
    approval = sent["approval"]
    assert (approval["proposal_id"], approval["approved_by"], approval["arguments_sha256"]) == (
        proposal["id"],
        "manager",
        proposal["arguments_sha256"],
    )
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", approval["approved_at"])
    assert datetime.fromisoformat(approval["approved_at"]) == datetime.fromisoformat(
        body["approval"]["approved_at"]
    )
    assert {k: sent[k] for k in ("supplier_id", "lines")} == proposal["arguments"]

    # The draft is live in the ERP; the product's lock is released.
    assert len(fake.drafts()) == 1 and fake.drafts()[0]["created_by"] == "agent"
    assert _risk(api_client, manager)["P003"]["live_proposal"] is None


def test_the_draft_counts_as_on_order_at_the_next_window(first_night, api_client, manager) -> None:
    from datetime import UTC, datetime

    from brain.clock import today_cairo
    from brain.jobs.registry import run_job

    from fakes import sales_row

    proposal = _propose(api_client, manager)
    assert _approve(api_client, manager, proposal).json()["status"] == "draft_created"
    quantity = proposal["arguments"]["lines"][0]["quantity"]
    first_night.put_sales(sales_row("P003", today_cairo(), 1, 0, "open", datetime.now(UTC)))
    assert run_job("sales-poll", "manual") == 0
    assert run_job("hourly-window", "manual") == 0
    assert _risk(api_client, manager)["P003"]["open_po_qty"] == quantity


def test_a_wrong_fingerprint_sends_nothing(first_night, api_client, manager) -> None:
    proposal = _propose(api_client, manager)
    sha = proposal["arguments_sha256"]
    wrong = ("0" if sha[0] != "0" else "1") + sha[1:]
    response = _approve(api_client, manager, proposal, sha=wrong)
    assert response.status_code == 409 and response.json()["code"] == "FINGERPRINT_MISMATCH"
    assert first_night.post_requests() == []
    detail = api_client.get(f"{PROPOSALS}/{proposal['id']}", headers=manager).json()
    assert (
        detail["status"] == "awaiting_approval"
        and detail["approval"] is None
        and detail["attempts"] == []
    )


def test_approving_twice_sends_once(first_night, api_client, manager) -> None:
    proposal = _propose(api_client, manager)
    assert _approve(api_client, manager, proposal).status_code == 200
    again = _approve(api_client, manager, proposal)
    assert again.status_code == 409 and again.json()["code"] == "NOT_AWAITING_APPROVAL"
    assert len(first_night.post_requests()) == 1


def test_ten_concurrent_approvals_make_one_draft(first_night, api_client, manager, pg) -> None:
    from brain.db import get_api_sessionmaker
    from brain.proposals.execution import approve
    from brain.proposals.service import ProposalRefused

    proposal = _propose(api_client, manager)
    outcomes: list[str] = []
    barrier = threading.Barrier(10)

    def one() -> None:
        barrier.wait()
        try:
            approve(get_api_sessionmaker(), proposal["id"], proposal["arguments_sha256"], "manager")
            outcomes.append("approved")
        except ProposalRefused as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=one) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["NOT_AWAITING_APPROVAL"] * 9 + ["approved"]
    assert len(first_night.drafts()) == 1
    detail = api_client.get(f"{PROPOSALS}/{proposal['id']}", headers=manager).json()
    assert detail["status"] == "draft_created"
    assert detail["purchase_order_id"] == first_night.drafts()[0]["purchase_order_id"]


def test_reject(first_night, api_client, manager) -> None:
    proposal = _propose(api_client, manager)
    response = api_client.post(f"{PROPOSALS}/{proposal['id']}/reject", headers=manager)
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert first_night.post_requests() == []
    assert _risk(api_client, manager)["P003"]["live_proposal"] is None
    assert _approve(api_client, manager, proposal).json()["code"] == "NOT_AWAITING_APPROVAL"
    again = api_client.post(f"{PROPOSALS}/{proposal['id']}/reject", headers=manager)
    assert again.status_code == 409 and again.json()["code"] == "NOT_AWAITING_APPROVAL"
    _propose(api_client, manager)  # the product is free again


def test_only_a_proposal_awaiting_approval_can_be_rejected(
    first_night, api_client, manager
) -> None:
    created = _propose(api_client, manager, "P003")
    _approve(api_client, manager, created)  # draft_created
    first_night.fail["create_po"] = 503
    unclear = _propose(api_client, manager, "P011")
    assert _approve(api_client, manager, unclear).json()["status"] == "uncertain"
    first_night.fail["create_po"] = 422
    refused = _propose(api_client, manager, "P017")
    assert _approve(api_client, manager, refused).json()["status"] == "failed"
    for proposal in (created, unclear, refused):
        response = api_client.post(f"{PROPOSALS}/{proposal['id']}/reject", headers=manager)
        assert response.status_code == 409 and response.json()["code"] == "NOT_AWAITING_APPROVAL"


def test_a_newer_recommendation_is_shown_and_the_proposal_sends_its_own(
    first_night, api_client, manager
) -> None:
    from brain.jobs.registry import run_job

    proposal = _propose(api_client, manager)
    quantity = proposal["arguments"]["lines"][0]["quantity"]
    assert run_job("end-of-day", "manual") == 0  # a newer recommendation for every product
    detail = api_client.get(f"{PROPOSALS}/{proposal['id']}", headers=manager).json()
    newer = detail["newer_recommendation"]
    assert newer is not None and newer["recommendation_id"] != proposal["recommendation_id"]
    assert newer["computed_at"] > detail["recommendation"]["computed_at"]
    body = _approve(api_client, manager, proposal).json()
    assert body["status"] == "draft_created" and body["newer_recommendation"] is None
    assert first_night.drafts()[0]["lines"][0]["ordered_qty"] == quantity


def test_a_clear_refusal_fails_for_good(first_night, api_client, manager) -> None:
    first_night.fail["create_po"] = 422
    proposal = _propose(api_client, manager)
    body = _approve(api_client, manager, proposal).json()
    assert body["status"] == "failed" and body["failure"]["code"] == "VALIDATION_ERROR"
    assert _risk(api_client, manager)["P003"]["live_proposal"] is None
    assert _approve(api_client, manager, proposal).json()["code"] == "NOT_AWAITING_APPROVAL"
    del first_night.fail["create_po"]
    fresh = _propose(api_client, manager)  # D-43: a new proposal, a new key, a fresh approval
    assert fresh["id"] != proposal["id"]
    assert _approve(api_client, manager, fresh).json()["status"] == "draft_created"


def test_sign_in_is_required_and_the_approver_is_the_token_subject(
    first_night, api_client, sign
) -> None:
    manager = {"Authorization": f"Bearer {sign()}"}
    proposal = _propose(api_client, manager)
    url = f"{PROPOSALS}/{proposal['id']}/approve"
    body = {"arguments_sha256": proposal["arguments_sha256"]}
    assert api_client.post(url, json=body).status_code == 401
    service = {"Authorization": f"Bearer {sign(aud='bizbrain-canonical')}"}
    assert api_client.post(url, headers=service, json=body).status_code == 401
    other = {"Authorization": f"Bearer {sign(sub='amina')}"}
    assert (
        api_client.post(url, headers=other, json=body).json()["approval"]["approved_by"] == "amina"
    )
    bad = api_client.post(url, headers=manager, json={"arguments_sha256": "ABC"})
    assert bad.status_code == 422
