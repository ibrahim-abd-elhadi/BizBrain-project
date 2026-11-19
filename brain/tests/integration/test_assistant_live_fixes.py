"""Three problems from live use on gemini-3.5-flash-lite, reproduced with the scripted stand-in.

1. "give me a brief for our sales these days" -> "I don't have that information": no tool could
   answer for all products at once.
2. "prepare purchase order for P001" -> "no order is recommended, give a quantity", then "25" ->
   "P001 is not a known product": the follow-up names no product, and the model lost it.
3. Eval E01: the risky products were named without their days of cover and orders.
"""

import json
import logging
from datetime import date

from sqlalchemy import func, select

from brain.assistant.graph import COULD_NOT_ANSWER, SYSTEM
from brain.assistant.tools import TOOL_SPECS, TurnContext, run_tool
from brain.config import get_settings
from brain.models import Proposal, SalesDaily

from scripted_model import Call, Say, latest

URL = "/api/v1/brain/assistant/messages"


def _chat(api_client, manager, messages):
    return api_client.post(URL, json={"messages": messages}, headers=manager).json()


def _proposals(worker_session) -> list[Proposal]:
    worker_session.expire_all()
    return list(worker_session.scalars(select(Proposal)))


# ---------------------------------------------------------------- 1. all-products sales summary


def test_sales_history_answers_for_all_products(first_night, api_session, worker_session) -> None:
    ctx = TurnContext(session=api_session, settings=get_settings())
    result = run_tool(ctx, "get_sales_history", {})
    assert result["scope"] == "all_products" and result["days_counted"] == 7
    closed = list(
        worker_session.scalars(
            select(SalesDaily.business_date)
            .where(SalesDaily.day_status == "closed")
            .distinct()
            .order_by(SalesDaily.business_date.desc())
            .limit(7)
        )
    )
    assert result["first_day"] == min(closed).isoformat()
    assert result["last_day"] == max(closed).isoformat()
    net = worker_session.scalar(
        select(func.sum(SalesDaily.net_units)).where(SalesDaily.business_date.in_(closed))
    )
    assert result["totals"]["net_units"] == net
    top = result["top_products"]
    assert len(top) == 5 and [t["net_units"] for t in top] == sorted(
        (t["net_units"] for t in top), reverse=True
    )
    assert {"product_id", "product_name", "units_sold", "net_units"} <= set(top[0])
    three = run_tool(ctx, "get_sales_history", {"days": 3})
    assert three["days_counted"] == 3
    one = run_tool(ctx, "get_sales_history", {"product_id": "P003", "days": 7})
    assert one.get("scope") == "product" and one["product_id"] == "P003"


def _summary_en(results, _request) -> str:
    s = latest(results, "get_sales_history")
    t, top = s["totals"], s["top_products"][0]
    return (
        f"From {s['first_day']} to {s['last_day']} the pharmacy sold {t['units_sold']} units, "
        f"{t['net_units']} net of returns. Top seller: {top['product_id']} with {top['net_units']} net. "
        "The nightly summary is on the Briefing screen."
    )


def _summary_ar(results, _request) -> str:
    s = latest(results, "get_sales_history")
    t, top = s["totals"], s["top_products"][0]
    return (
        f"من {s['first_day']} إلى {s['last_day']} بِيعت {t['units_sold']} وحدة، والصافي {t['net_units']}. "
        f"الأكثر مبيعًا {top['product_id']} بصافي {top['net_units']}. الملخص الليلي في شاشة Briefing."
    )


def test_a_sales_brief_is_answered_in_english_and_arabic(
    first_night, api_client, manager, scripted
) -> None:
    model = scripted(Call("get_sales_history", {}), Say(_summary_en))
    body = _chat(
        api_client,
        manager,
        [{"role": "manager", "text": "give me a brief for our sales these days"}],
    )
    assert body["outcome"] == "answered" and "Briefing" in body["reply"]["text"]
    assert model.calls == 2
    scripted(Call("get_sales_history", {"days": 7}), Say(_summary_ar))
    body = _chat(
        api_client, manager, [{"role": "manager", "text": "أعطني ملخصًا لمبيعاتنا هذه الأيام"}]
    )
    assert body["outcome"] == "answered" and body["reply"]["language"] == "ar"


def test_the_instructions_cover_sales_briefs_and_what_the_assistant_can_do() -> None:
    system = " ".join(SYSTEM.split())
    assert "without product_id" in system and "Briefing screen" in system
    assert "never reply only that you don't have the information" in system
    sales = next(t for t in TOOL_SPECS if t.name == "get_sales_history")
    assert (
        "all products" in sales.description and "product_id" not in sales.parameters["required"]
        if "required" in sales.parameters
        else True
    )


def test_the_fallback_says_what_the_assistant_can_do() -> None:
    for language in ("en", "ar"):
        assert "Proposals" in COULD_NOT_ANSWER[language] or "proposal" in COULD_NOT_ANSWER[language]
    assert "sales, forecasts, stock, risk and open orders" in COULD_NOT_ANSWER["en"]
    assert "المبيعات" in COULD_NOT_ANSWER["ar"]


# ---------------------------------------------------------------- 2. follow-up quantities

HISTORY_EN = [
    {"role": "manager", "text": "prepare purchase order for P001"},
    {
        "role": "assistant",
        "text": "No order is recommended for P001 right now; give a quantity to order anyway.",
        "language": "en",
    },
]


def _prepared(results, _request) -> str:
    created = latest(results, "propose_purchase_order")
    line = created["lines"][0]
    return f"Prepared: {line['product_id']} × {line['quantity']} from {created['supplier_id']}. Review it on Proposals."


def test_the_first_request_asks_for_a_quantity(first_night, api_client, manager, scripted) -> None:
    scripted(
        Call("propose_purchase_order", {"product_ids": ["P001"]}),
        Say("No order is recommended for P001 right now; give a quantity to order anyway."),
    )
    body = _chat(api_client, manager, HISTORY_EN[:1])
    assert body["refusal"]["code"] == "NO_RECOMMENDED_QUANTITY"
    assert "give a quantity" in body["refusal"]["detail"]


def test_a_quantity_follow_up_with_the_product_lost_uses_the_conversation(
    first_night, api_client, manager, scripted, worker_session, caplog
) -> None:
    """The live failure: the model sent no product (or a made-up one) for "25"."""
    caplog.set_level(logging.INFO, logger="brain.assistant")
    for args in ({"quantity": 25}, {"product_ids": ["P025"], "quantity": 25}):
        scripted(Call("propose_purchase_order", args), Say(_prepared))
        body = _chat(api_client, manager, [*HISTORY_EN, {"role": "manager", "text": "25"}])
        assert body["refusal"] is None, (args, body["refusal"])
        assert body["proposal"]["lines"] == [
            {"product_id": "P001", "product_name": "Paracetamol 500 mg tablets", "quantity": 25}
        ]
        assert body["outcome"] == "answered"
        proposal = next(
            p for p in _proposals(worker_session) if str(p.id) == body["proposal"]["id"]
        )
        assert proposal.origin == "assistant" and proposal.arguments["lines"] == [
            {"product_id": "P001", "quantity": 25}
        ]
        worker_session.execute(select(Proposal))  # keep the session fresh
        api_client.post(f"/api/v1/brain/proposals/{proposal.id}/reject", headers=manager)
        worker_session.expire_all()
    # The tool call is logged: name, arguments and outcome, nothing else.
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("assistant tool:")]
    assert any(
        "propose_purchase_order" in l and '"quantity": 25' in l and "-> created" in l for l in lines
    )


def test_an_arabic_quantity_follow_up(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    history = [
        {"role": "manager", "text": "جهّز أمر شراء لـ P001"},
        {
            "role": "assistant",
            "text": "لا توجد كمية موصى بها لـ P001 الآن؛ حدد الكمية.",
            "language": "ar",
        },
        {"role": "manager", "text": "٢٥"},
    ]
    scripted(
        Call("propose_purchase_order", {"quantity": 25}),
        Say(
            lambda r, q: (
                f"تم إعداد المقترح: P001 × {latest(r, 'propose_purchase_order')['lines'][0]['quantity']}. راجعه في شاشة Proposals."
            )
        ),
    )
    body = _chat(api_client, manager, history)
    assert body["proposal"]["lines"][0]["quantity"] == 25 and body["reply"]["language"] == "ar"


def test_the_quantity_must_still_be_the_managers_newest_number(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    """P-4 stays: a quantity not in the newest message (and not the recommendation) is refused."""
    scripted(Call("propose_purchase_order", {"quantity": 30}), Say("I couldn't prepare that."))
    body = _chat(api_client, manager, [*HISTORY_EN, {"role": "manager", "text": "25"}])
    assert body["refusal"]["code"] == "QUANTITY_NOT_GIVEN" and _proposals(worker_session) == []


def test_a_named_unknown_product_is_still_refused(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    scripted(
        Call("propose_purchase_order", {"product_ids": ["P999"], "quantity": 25}),
        Say("P999 isn't known."),
    )
    body = _chat(api_client, manager, [{"role": "manager", "text": "order 25 of P999"}])
    assert body["refusal"]["code"] == "UNKNOWN_PRODUCT" and _proposals(worker_session) == []


def test_no_product_anywhere_asks_which(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    scripted(Call("propose_purchase_order", {"quantity": 25}), Say("Which product should I order?"))
    body = _chat(api_client, manager, [{"role": "manager", "text": "order 25"}])
    assert (
        body["refusal"]["code"] == "VALIDATION_ERROR"
        and "which product" in body["refusal"]["detail"]
    )


def test_a_manager_quantity_is_allowed_when_the_recommendation_is_zero(
    first_night, worker_session
) -> None:
    """Feature 004's create-proposal takes any manager quantity for origin "assistant"."""
    from brain.proposals.service import create_proposal

    proposal = create_proposal(
        worker_session,
        supplier_id="S001",
        lines=[{"product_id": "P001", "quantity": 25}],
        origin="assistant",
    )
    assert proposal.arguments["lines"] == [{"product_id": "P001", "quantity": 25}]
    worker_session.rollback()


# ---------------------------------------------------------------- 3. risk answers with numbers


def test_the_instructions_require_the_numbers_of_listed_risky_products() -> None:
    assert "days of cover and recommended order" in " ".join(SYSTEM.split())
    risk = next(t for t in TOOL_SPECS if t.name == "get_risk_list")
    assert "days of cover" in risk.description and "recommended order" in risk.description


def test_the_tool_log_carries_no_secret(first_night, api_session, caplog) -> None:
    from fake_gemini import CANARY_KEY
    from fakes import TOKEN

    caplog.set_level(logging.INFO, logger="brain.assistant")
    ctx = TurnContext(session=api_session, settings=get_settings())
    run_tool(ctx, "get_stock", {"product_id": "P003"})
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("assistant tool:")]
    assert lines == ['assistant tool: get_stock {"product_id": "P003"} -> ok']
    for line in lines:
        assert TOKEN not in line and CANARY_KEY not in line
    assert json.loads(lines[0].split(" ", 3)[3].rsplit(" -> ", 1)[0]) == {"product_id": "P003"}
    _ = date  # imported for readability of the day checks above
