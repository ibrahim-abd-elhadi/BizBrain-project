"""An unclear send is shown as uncertain and retried safely (feature 004 US3 scenarios 1-6; FR-016,
FR-018, FR-021; SC-003, SC-006). Written before the implementation."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import time_machine
from sqlalchemy import text

PROPOSALS = "/api/v1/brain/proposals"


def _propose(api_client, manager, product="P003") -> dict:
    items = api_client.get("/api/v1/brain/risk", headers=manager).json()["items"]
    rec = next(r for r in items if r["product_id"] == product)["recommendation_id"]
    response = api_client.post(PROPOSALS, headers=manager, json={"recommendation_id": rec})
    assert response.status_code == 201, response.text
    return response.json()


def _approve(api_client, manager, proposal) -> dict:
    response = api_client.post(
        f"{PROPOSALS}/{proposal['id']}/approve",
        headers=manager,
        json={"arguments_sha256": proposal["arguments_sha256"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _again(api_client, manager, proposal):
    return api_client.post(f"{PROPOSALS}/{proposal['id']}/send-again", headers=manager)


def _identical(fake) -> None:
    posts = fake.post_requests()
    assert len({p["body"] for p in posts}) == 1
    assert len({p["headers"]["idempotency-key"] for p in posts}) == 1


def test_a_timeout_before_the_erp_commits(first_night, api_client, manager) -> None:
    fake = first_night
    fake.fail["create_po"] = "timeout"
    proposal = _propose(api_client, manager)
    body = _approve(api_client, manager, proposal)
    assert body["status"] == "uncertain" and body["purchase_order_id"] is None
    assert [(a["attempt_no"], a["outcome"]) for a in body["attempts"]] == [(1, "uncertain")]
    assert body["attempts"][0]["detail"] == "the ERP didn't confirm the draft"
    assert fake.drafts() == []
    del fake.fail["create_po"]
    again = _again(api_client, manager, proposal)
    assert again.status_code == 200 and again.json()["status"] == "draft_created"
    assert len(fake.drafts()) == 1
    assert [a["outcome"] for a in again.json()["attempts"]] == ["uncertain", "draft_created"]
    _identical(fake)


def test_a_timeout_after_the_erp_commits(first_night, api_client, manager) -> None:
    fake = first_night
    fake.fail["create_po"] = "timeout_after_commit"
    proposal = _propose(api_client, manager)
    assert _approve(api_client, manager, proposal)["status"] == "uncertain"
    assert len(fake.drafts()) == 1  # the ERP did create it
    created = fake.drafts()[0]["purchase_order_id"]
    again = _again(api_client, manager, proposal).json()
    assert again["status"] == "draft_created" and again["purchase_order_id"] == created
    assert again["attempts"][-1]["http_status"] == 200  # the ERP replayed its original answer
    assert len(fake.drafts()) == 1
    _identical(fake)


def test_other_unclear_answers(first_night, api_client, manager) -> None:
    fake = first_night
    for product, mode in (("P003", 503), ("P011", 500), ("P017", "garbage_2xx")):
        fake.fail["create_po"] = mode
        proposal = _propose(api_client, manager, product)
        body = _approve(api_client, manager, proposal)
        assert body["status"] == "uncertain", mode
        assert api_client.get("/api/v1/brain/risk", headers=manager).json() is not None


def test_a_missing_credential_file_sends_nothing(
    first_night, api_client, manager, settings_override, tmp_path
) -> None:
    fake = first_night
    proposal = _propose(api_client, manager)
    settings_override(BRAIN_ERP_SERVICE_TOKEN_FILE=str(tmp_path / "missing"))
    body = _approve(api_client, manager, proposal)
    assert body["status"] == "uncertain"
    assert body["attempts"][0]["outcome"] == "not_sent"
    assert body["attempts"][0]["detail"] == "the Brain's ERP credential file is missing"
    assert fake.post_requests() == []
    restored = tmp_path / "token"
    restored.write_text("test-service-token\n", encoding="utf-8")
    settings_override(BRAIN_ERP_SERVICE_TOKEN_FILE=str(restored))
    again = _again(api_client, manager, proposal).json()
    assert again["status"] == "draft_created" and len(fake.drafts()) == 1


def test_send_again_only_for_an_uncertain_proposal(first_night, api_client, manager) -> None:
    fake = first_night
    awaiting = _propose(api_client, manager, "P003")
    created = _propose(api_client, manager, "P011")
    _approve(api_client, manager, created)
    fake.fail["create_po"] = 422
    failed = _propose(api_client, manager, "P017")
    _approve(api_client, manager, failed)
    del fake.fail["create_po"]
    sent_before = len(fake.post_requests())
    for proposal in (awaiting, created, failed):
        response = _again(api_client, manager, proposal)
        assert response.status_code == 409 and response.json()["code"] == "NOT_UNCERTAIN"
    assert (
        api_client.post(f"{PROPOSALS}/{awaiting['id']}/reject", headers=manager).status_code == 200
    )
    response = _again(api_client, manager, awaiting)  # now rejected
    assert response.status_code == 409 and response.json()["code"] == "NOT_UNCERTAIN"
    assert len(fake.post_requests()) == sent_before


def test_ten_concurrent_sends_make_one_draft(first_night, api_client, manager, pg) -> None:
    from brain.db import get_api_sessionmaker
    from brain.proposals.execution import send_again

    fake = first_night
    fake.fail["create_po"] = "timeout"
    proposal = _propose(api_client, manager)
    _approve(api_client, manager, proposal)
    del fake.fail["create_po"]
    barrier = threading.Barrier(10)
    errors: list[Exception] = []

    def one() -> None:
        barrier.wait()
        try:
            send_again(get_api_sessionmaker(), proposal["id"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=one) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Some calls may find the proposal already decided (NOT_UNCERTAIN); none may create a second draft.
    assert all(getattr(e, "code", None) == "NOT_UNCERTAIN" for e in errors), errors
    assert len(fake.drafts()) == 1
    detail = api_client.get(f"{PROPOSALS}/{proposal['id']}", headers=manager).json()
    assert detail["status"] == "draft_created"
    assert detail["purchase_order_id"] == fake.drafts()[0]["purchase_order_id"]
    _identical(fake)


def test_a_crash_between_the_two_transactions(
    first_night, api_client, manager, worker_session
) -> None:
    proposal = _propose(api_client, manager)
    started = datetime.now(UTC) - timedelta(seconds=2)
    worker_session.execute(
        text(
            "UPDATE proposal SET status = 'uncertain', approved_by = 'manager', approved_at = :t,"
            " request_body = :b WHERE id = :id"
        ),
        {"t": started, "id": proposal["id"], "b": _body(proposal, started)},
    )
    worker_session.execute(
        text(
            "INSERT INTO proposal_attempt (proposal_id, attempt_no, started_at) VALUES (:id, 1, :t)"
        ),
        {"id": proposal["id"], "t": started},
    )
    worker_session.commit()
    detail = api_client.get(f"{PROPOSALS}/{proposal['id']}", headers=manager).json()
    assert detail["status"] == "uncertain" and detail["sending"] is True
    with time_machine.travel(datetime.now(UTC) + timedelta(seconds=20), tick=True):
        later = api_client.get(f"{PROPOSALS}/{proposal['id']}", headers=manager).json()
        assert later["status"] == "uncertain" and later["sending"] is False
        again = _again(api_client, manager, proposal).json()
    assert again["status"] == "draft_created"
    assert [a["attempt_no"] for a in again["attempts"]] == [1, 2]


def _body(proposal: dict, approved_at: datetime) -> str:
    from brain.proposals.canonical import canonical

    return canonical(
        {
            **proposal["arguments"],
            "approval": {
                "proposal_id": proposal["id"],
                "approved_by": "manager",
                "approved_at": approved_at.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "arguments_sha256": proposal["arguments_sha256"],
            },
        }
    )


def test_no_automatic_retry(first_night, api_client, manager) -> None:
    fake = first_night
    fake.fail["create_po"] = 503
    proposal = _propose(api_client, manager)
    _approve(api_client, manager, proposal)
    assert len(fake.post_requests()) == 1
    _again(api_client, manager, proposal)
    assert len(fake.post_requests()) == 2


def test_unknown_proposal(first_night, api_client, manager) -> None:
    response = api_client.post(f"{PROPOSALS}/{uuid.uuid4()}/send-again", headers=manager)
    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"
