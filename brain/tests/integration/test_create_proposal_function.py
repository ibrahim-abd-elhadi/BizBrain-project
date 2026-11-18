"""One proposal shape for rules and for the agent (feature 004 US4 scenarios 1-4; FR-008;
contracts/create-proposal.md). Feature 005's propose_purchase_order tool will call this function.
Written before the final shape of the function."""

import pytest
from sqlalchemy import text

PROPOSALS = "/api/v1/brain/proposals"


def test_the_assistant_gets_the_same_shape_as_a_rule_built_proposal(
    first_night, api_client, manager, api_session
) -> None:
    from brain.proposals import ProposalRefused, create_proposal  # noqa: F401  (the public names)

    items = api_client.get("/api/v1/brain/risk", headers=manager).json()["items"]
    p003 = next(r for r in items if r["product_id"] == "P003")
    rule = api_client.post(
        PROPOSALS, headers=manager, json={"recommendation_id": p003["recommendation_id"]}
    ).json()
    assert api_client.post(f"{PROPOSALS}/{rule['id']}/reject", headers=manager).status_code == 200

    proposal = create_proposal(
        api_session,
        supplier_id="S004",
        lines=[{"product_id": "P003", "quantity": p003["order_qty"]}],
        origin="assistant",
    )
    api_session.commit()
    assert proposal.status == "awaiting_approval" and proposal.origin == "assistant"
    assert proposal.recommendation_id is None
    assert proposal.arguments == rule["arguments"]
    assert proposal.arguments_sha256 == rule["arguments_sha256"]
    canonical = api_session.scalar(
        text("SELECT arguments_canonical FROM proposal WHERE id = :id"), {"id": rule["id"]}
    )
    assert proposal.arguments_canonical == canonical

    listed = {p["id"]: p for p in api_client.get(PROPOSALS, headers=manager).json()["items"]}
    mine = listed[str(proposal.id)]
    assert set(mine) == set(listed[rule["id"]])  # the same fields
    assert mine["origin"] == "assistant" and mine["recommendation_id"] is None
    detail = api_client.get(f"{PROPOSALS}/{proposal.id}", headers=manager).json()
    assert detail["recommendation"] is None and detail["newer_recommendation"] is None
    assert first_night.post_requests() == []  # creating never contacts the ERP


def test_several_lines_lock_every_product(first_night, api_session) -> None:
    from brain.proposals import ProposalRefused, create_proposal

    proposal = create_proposal(
        api_session,
        supplier_id="S001",
        lines=[{"product_id": "P002", "quantity": 30}, {"product_id": "P001", "quantity": 60}],
        origin="assistant",
    )
    api_session.commit()
    assert (
        proposal.arguments_sha256
        == "4d26045c552bc3ce10d209ceb1f2a4d03b410166fd2a1bbe9b25c9aabb753629"
    )
    for product in ("P001", "P002"):
        with pytest.raises(ProposalRefused) as caught:
            create_proposal(
                api_session,
                supplier_id="S001",
                lines=[{"product_id": product, "quantity": 1}],
                origin="assistant",
            )
        assert caught.value.code == "PROPOSAL_PENDING" and caught.value.proposal_id == proposal.id
        api_session.rollback()


def test_an_assistant_proposal_goes_through_approval(
    first_night, api_client, manager, api_session
) -> None:
    from brain.proposals import create_proposal

    proposal = create_proposal(
        api_session,
        supplier_id="S004",
        lines=[{"product_id": "P003", "quantity": 24}],
        origin="assistant",
    )
    api_session.commit()
    body = api_client.post(
        f"{PROPOSALS}/{proposal.id}/approve",
        headers=manager,
        json={"arguments_sha256": proposal.arguments_sha256},
    ).json()
    assert body["status"] == "draft_created"
    assert first_night.drafts()[0]["lines"][0]["ordered_qty"] == 24


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "supplier_id": "S4",
            "lines": [{"product_id": "P003", "quantity": 1}],
            "origin": "assistant",
        },
        {"supplier_id": "S004", "lines": [], "origin": "assistant"},
        {
            "supplier_id": "S004",
            "lines": [{"product_id": "P003", "quantity": 0}],
            "origin": "assistant",
        },
        {
            "supplier_id": "S004",
            "lines": [{"product_id": "P003", "quantity": 1}] * 2,
            "origin": "assistant",
        },
        {
            "supplier_id": "S004",
            "lines": [{"product_id": "P003", "quantity": 1}],
            "origin": "recommendation",
        },
    ],
    ids=["supplier", "no lines", "quantity 0", "product twice", "origin without recommendation"],
)
def test_refusals_leave_nothing(first_night, api_session, kwargs) -> None:
    from brain.proposals import ProposalRefused, create_proposal

    with pytest.raises(ProposalRefused) as caught:
        create_proposal(api_session, **kwargs)
    assert caught.value.code == "VALIDATION_ERROR"
    api_session.rollback()
    assert api_session.scalar(text("SELECT count(*) FROM proposal")) == 0
