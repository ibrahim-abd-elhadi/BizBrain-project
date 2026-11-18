"""The running brain-api and its contracts describe the same operations, and the responses
validate against the contracts' schemas: feature 003's read API (research R-20) plus feature 004's
proposals (research R-13). Written first."""

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

SPECS = Path(__file__).resolve().parents[3] / "specs"
CONTRACT = SPECS / "003-brain-intelligence/contracts/brain-api.openapi.yaml"
PROPOSALS_CONTRACT = SPECS / "004-approval-flow/contracts/brain-api-proposals.openapi.yaml"
ASSISTANT_CONTRACT = SPECS / "005-ai-assistant/contracts/brain-api-assistant.openapi.yaml"
PENDING: set[tuple[str, str]] = set()  # every feature 005 operation is served
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _contract(path: Path = CONTRACT) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def operations(paths: dict) -> set[tuple[str, str]]:
    return {(p, m) for p, item in paths.items() for m in item if m in HTTP_METHODS}


def validate(schema_name: str, document, path: Path = CONTRACT) -> None:
    contract = _contract(path)
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": contract["components"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def validate_list(schema_name: str, documents: list, path: Path = CONTRACT) -> None:
    for document in documents:
        validate(schema_name, document, path)


def test_the_app_serves_exactly_the_contract_operations(api_client) -> None:
    """Feature 003's GETs, feature 004's proposal operations and feature 005's assistant,
    briefing and Why? operations, nothing else."""
    expected: set[tuple[str, str]] = set()
    for path in (CONTRACT, PROPOSALS_CONTRACT, ASSISTANT_CONTRACT):
        contract = _contract(path)
        prefix = contract["servers"][0]["url"]
        assert prefix == "/api/v1/brain"
        expected |= {(prefix + p, m) for p, m in operations(contract["paths"])}
    expected -= PENDING
    served = operations(api_client.app.openapi()["paths"])
    assert served == expected, f"contract only: {expected - served}; app only: {served - expected}"


def test_the_risk_list_matches_the_contract(first_night, api_client, manager) -> None:
    body = api_client.get("/api/v1/brain/risk", headers=manager).json()
    validate("RiskList", body)
    assert len(body["items"]) == 20
    validate_list("RiskRowAdditions", body["items"], PROPOSALS_CONTRACT)


def test_an_empty_risk_list_matches_the_contract(api_client, manager) -> None:
    validate("RiskList", api_client.get("/api/v1/brain/risk", headers=manager).json())


def test_errors_match_the_contract(api_client) -> None:
    validate("Error", api_client.get("/api/v1/brain/risk").json())


# ---------------------------------------------------------------- part 2 (US5)


def test_the_forecast_endpoints_match_the_contract(first_night, api_client, manager) -> None:
    products = api_client.get("/api/v1/brain/forecasts", headers=manager).json()
    assert len(products) == 20
    validate_list("ForecastProduct", products)
    for product_id in ("P003", "P013", "P020"):
        body = api_client.get(f"/api/v1/brain/forecasts/{product_id}", headers=manager).json()
        validate("ProductForecast", body)


def test_forecast_errors_match_the_contract(first_night, api_client, manager) -> None:
    for path in ("/api/v1/brain/forecasts/P999", "/api/v1/brain/forecasts/p003"):
        validate("Error", api_client.get(path, headers=manager).json())


# ---------------------------------------------------------------- feature 004 (proposals)


def test_the_proposal_endpoints_match_the_contract(first_night, api_client, manager) -> None:
    items = api_client.get("/api/v1/brain/risk", headers=manager).json()["items"]
    rec = next(r for r in items if r["product_id"] == "P003")["recommendation_id"]
    created = api_client.post(
        "/api/v1/brain/proposals", headers=manager, json={"recommendation_id": rec}
    )
    assert created.status_code == 201
    validate("Proposal", created.json(), PROPOSALS_CONTRACT)
    validate(
        "ProposalList",
        api_client.get("/api/v1/brain/proposals", headers=manager).json(),
        PROPOSALS_CONTRACT,
    )
    detail = api_client.get(
        f"/api/v1/brain/proposals/{created.json()['id']}", headers=manager
    ).json()
    validate("ProposalDetail", detail, PROPOSALS_CONTRACT)
    pending = api_client.post(
        "/api/v1/brain/proposals", headers=manager, json={"recommendation_id": rec}
    )
    validate("Error", pending.json(), PROPOSALS_CONTRACT)
    assert pending.json()["code"] == "PROPOSAL_PENDING"


# ---------------------------------------------------------------- feature 005 (T023)


def test_availability_matches_the_contract(
    api_client, manager, scripted, settings_override, tmp_path
) -> None:
    scripted()
    body = api_client.get("/api/v1/brain/assistant", headers=manager).json()
    validate("Availability", body, ASSISTANT_CONTRACT)


def test_offline_availability_matches_the_contract(
    api_client, manager, settings_override, tmp_path
) -> None:
    settings_override(BRAIN_GEMINI_API_KEY_FILE=str(tmp_path / "absent"))
    body = api_client.get("/api/v1/brain/assistant", headers=manager).json()
    assert body["available"] is False and body["reason"] == "no_key"
    validate("Availability", body, ASSISTANT_CONTRACT)


def test_chat_replies_match_the_contract(first_night, api_client, manager, scripted) -> None:
    from scripted_model import Call, Fail, Say

    url = "/api/v1/brain/assistant/messages"
    ask = {"messages": [{"role": "manager", "text": "Which products are at high risk?"}]}
    scripted(Call("get_risk_list", {"risk": "high"}), Say("P003, P011 and P017 are high."))
    validate(
        "ChatReply", api_client.post(url, json=ask, headers=manager).json(), ASSISTANT_CONTRACT
    )
    scripted(Call("get_risk_list", {}), Say("987.65 days"), Say("987.66 days"))
    body = api_client.post(url, json=ask, headers=manager).json()
    assert body["outcome"] == "not_grounded"
    validate("ChatReply", body, ASSISTANT_CONTRACT)
    scripted(Fail("rate_limited"))
    body = api_client.post(url, json=ask, headers=manager).json()
    assert body["outcome"] == "offline"
    validate("ChatReply", body, ASSISTANT_CONTRACT)
    bad = api_client.post(url, json={"messages": []}, headers=manager)
    assert bad.status_code == 422
    validate("Error", bad.json(), ASSISTANT_CONTRACT)


def test_chat_proposals_and_refusals_match_the_contract(
    first_night, api_client, manager, scripted
) -> None:
    from scripted_model import Call, Say

    url = "/api/v1/brain/assistant/messages"

    def ask(text_):
        return api_client.post(
            url, json={"messages": [{"role": "manager", "text": text_}]}, headers=manager
        ).json()

    scripted(Call("propose_purchase_order", {"product_ids": ["P003"]}), Say("Prepared for P003."))
    body = ask("Prepare an order for P003 as recommended")
    assert body["proposal"] is not None
    validate("ChatReply", body, ASSISTANT_CONTRACT)
    validate("ChatProposal", body["proposal"], ASSISTANT_CONTRACT)
    for args, question in (
        ({"product_ids": ["P003"]}, "Prepare an order for P003"),  # PROPOSAL_PENDING now
        ({"product_ids": ["P003"], "quantity": 999}, "Prepare an order for P003"),
        ({"product_ids": ["P999"]}, "Order P999"),
        ({"product_ids": ["P003", "P011"]}, "Order P003 and P011"),
    ):
        scripted(Call("propose_purchase_order", args), Say("No new proposal."))
        body = ask(question)
        assert body["refusal"] is not None, args
        validate("ChatReply", body, ASSISTANT_CONTRACT)
        validate("ChatRefusal", body["refusal"], ASSISTANT_CONTRACT)
