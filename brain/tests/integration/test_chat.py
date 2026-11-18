"""The chat turn through brain-api, with the scripted stand-in (research R-03 to R-07). Written
first (T022, reads; T032 adds the propose tool in test_propose_tool.py).

The stand-in plays the model; the graph, the read tools, the grounding guard, the language rule
and the offline mapping run for real.
"""

from sqlalchemy import text

from scripted_model import Call, Fail, Say, latest

URL = "/api/v1/brain/assistant/messages"


def _ask(api_client, manager, *texts, history=None):
    messages = list(history or [])
    messages += [{"role": "manager", "text": t} for t in texts]
    return api_client.post(URL, json={"messages": messages}, headers=manager)


def _high_en(results, _request) -> str:
    items = latest(results, "get_risk_list")["items"]
    return "High risk: " + "; ".join(
        f"{i['product_id']} has {i['days_of_cover']} days of cover vs a "
        f"{i['lead_time_days']}-day lead time, order {i['order_qty']}"
        for i in items
    )


def _high_ar(results, _request) -> str:
    items = latest(results, "get_risk_list")["items"]
    return "المنتجات ذات الخطر المرتفع: " + "، ".join(
        f"{i['product_id']} تغطية {i['days_of_cover']} يوم ومهلة التوريد {i['lead_time_days']} يوم"
        for i in items
    )


def test_an_english_question_is_answered_from_the_tools(
    first_night, api_client, manager, scripted
) -> None:
    model = scripted(Call("get_risk_list", {"risk": "high"}), Say(_high_en))
    response = _ask(api_client, manager, "Which products are at high risk?")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answered" and body["synthetic"] is True
    assert body["reply"]["language"] == "en"
    for product in ("P003", "P011", "P017"):
        assert product in body["reply"]["text"]
    assert body["proposal"] is None and body["refusal"] is None
    system = model.requests[0]["system"]
    assert "Reply in English" in system
    assert "P003 | Amoxicillin 500 mg capsules" in system  # the catalog block
    assert model.requests[0]["tools"] == [
        "get_risk_list",
        "get_forecast",
        "get_sales_history",
        "get_stock",
        "get_open_purchase_orders",
        "propose_purchase_order",
    ]


def test_an_arabic_question_and_a_letterless_follow_up(
    first_night, api_client, manager, scripted
) -> None:
    model = scripted(Call("get_risk_list", {"risk": "high"}), Say(_high_ar))
    body = _ask(api_client, manager, "ما المنتجات ذات الخطر العالي؟").json()
    assert body["outcome"] == "answered" and body["reply"]["language"] == "ar"
    assert "Reply in Arabic" in model.requests[0]["system"]
    history = [
        {"role": "manager", "text": "ما المنتجات ذات الخطر العالي؟"},
        {"role": "assistant", "text": body["reply"]["text"], "language": "ar"},
    ]
    model = scripted(Call("get_risk_list", {}), Say(lambda r, q: "P003 تغطية مرتفعة الخطر"))
    follow = _ask(api_client, manager, "P003?", history=history).json()
    assert follow["outcome"] == "answered" and follow["reply"]["language"] == "ar"
    assert "Reply in Arabic" in model.requests[0]["system"]


def test_an_invented_number_is_corrected_once(first_night, api_client, manager, scripted) -> None:
    model = scripted(
        Call("get_risk_list", {"risk": "high"}),
        Say("P003 has 4.5 days of cover."),
        Say(_high_en),
    )
    body = _ask(api_client, manager, "Which products are at high risk?").json()
    assert body["outcome"] == "answered"
    correction = model.requests[2]["contents"][-1]
    assert correction["role"] == "user" and "4.5" in correction["text"]


def test_an_invented_number_twice_is_not_shown(first_night, api_client, manager, scripted) -> None:
    scripted(Call("get_risk_list", {}), Say("P003 has 987.65 days."), Say("P003 has 987.66 days."))
    body = _ask(api_client, manager, "Which products are at high risk?").json()
    assert body["outcome"] == "not_grounded"
    assert body["reply"] == {
        "text": "I couldn't answer that reliably. Please try rephrasing.",
        "language": "en",
    }
    scripted(Call("get_risk_list", {}), Say("P003 لديه 987.65 يوم."), Say("P003 لديه 987.66 يوم."))
    body = _ask(api_client, manager, "ما المنتجات ذات الخطر العالي؟").json()
    assert body["outcome"] == "not_grounded" and body["reply"]["language"] == "ar"
    assert body["reply"]["text"] == "تعذّر عليّ الإجابة بشكل موثوق. حاول إعادة صياغة السؤال."


def test_a_reply_in_the_wrong_language_is_retried(
    first_night, api_client, manager, scripted
) -> None:
    model = scripted(Call("get_risk_list", {"risk": "high"}), Say(_high_en), Say(_high_ar))
    body = _ask(api_client, manager, "ما المنتجات ذات الخطر العالي؟").json()
    assert body["outcome"] == "answered" and body["reply"]["language"] == "ar"
    assert model.calls == 3
    assert "Arabic" in model.requests[2]["contents"][-1]["text"]


def test_a_number_the_manager_wrote_may_be_repeated(
    first_night, api_client, manager, scripted
) -> None:
    scripted(
        Call("get_stock", {"product_id": "P003"}), Say("Yes, P003 has more than 40 available.")
    )
    body = _ask(api_client, manager, "Does P003 have more than 40 available?").json()
    assert body["outcome"] == "answered"


def test_an_unreachable_model_is_offline(first_night, api_client, manager, scripted) -> None:
    scripted(Fail("timeout"))
    body = _ask(api_client, manager, "Which products are at high risk?").json()
    assert body["outcome"] == "offline" and body["offline_reason"] == "timeout"
    assert body["reply"] is None and body["proposal"] is None
    # The model came back: the very next send tries it again (no offline cache, I1).
    model = scripted(Call("get_risk_list", {"risk": "high"}), Say(_high_en))
    body = _ask(api_client, manager, "Which products are at high risk?").json()
    assert body["outcome"] == "answered" and model.calls == 2


def test_a_turn_that_runs_out_of_time_is_offline(
    first_night, api_client, manager, scripted
) -> None:
    scripted(Call("get_risk_list", {}, takes=9), Say(_high_en, takes=6))
    body = _ask(api_client, manager, "Which products are at high risk?").json()
    assert body["outcome"] == "offline" and body["offline_reason"] == "timeout"


def test_too_many_tool_rounds_fall_back(first_night, api_client, manager, scripted) -> None:
    scripted(*[Call("get_risk_list", {}) for _ in range(5)])
    body = _ask(api_client, manager, "Which products are at high risk?").json()
    assert body["outcome"] == "not_grounded"
    assert body["reply"]["text"] == "I couldn't answer that reliably. Please try rephrasing."


def test_the_request_rules(first_night, api_client, manager, scripted) -> None:
    scripted()
    many = [{"role": "manager", "text": f"q{i}"} for i in range(21)]
    for body in (
        {"messages": many},
        {"messages": [{"role": "manager", "text": "x" * 2001}]},
        {"messages": [{"role": "manager", "text": "hi"}, {"role": "assistant", "text": "yo"}]},
        {"messages": []},
        {"messages": [{"role": "system", "text": "hi"}]},
    ):
        response = api_client.post(URL, json=body, headers=manager)
        assert response.status_code == 422, body
        assert response.json()["code"] == "VALIDATION_ERROR"


def test_only_the_manager_may_chat(api_client) -> None:
    for headers in ({}, {"Authorization": "Bearer test-service-token"}):
        response = api_client.post(
            URL, json={"messages": [{"role": "manager", "text": "hi"}]}, headers=headers
        )
        assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"


def test_nothing_of_the_conversation_is_stored(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    from brain.models import Base

    def counts() -> dict[str, int]:
        return {
            t.name: worker_session.scalar(text(f'SELECT count(*) FROM "{t.name}"'))
            for t in Base.metadata.sorted_tables
        }

    before = counts()
    scripted(
        Call("get_risk_list", {"risk": "high"}),
        Say(_high_en),
        Call("get_stock", {"product_id": "P003"}),
        Say(lambda r, q: f"P003 has {latest(r, 'get_stock')['available']} available."),
    )
    assert (
        _ask(api_client, manager, "Which products are at high risk?").json()["outcome"]
        == "answered"
    )
    assert _ask(api_client, manager, "And P003's stock?").json()["outcome"] == "answered"
    worker_session.expire_all()
    assert counts() == before


def test_the_availability_endpoint(api_client, manager, scripted) -> None:
    scripted()
    body = api_client.get("/api/v1/brain/assistant", headers=manager).json()
    assert body == {"synthetic": True, "available": True, "reason": None}


def test_the_availability_endpoint_remembers_a_real_429(
    first_night, api_client, manager, scripted
) -> None:
    model = scripted(Fail("rate_limited"))
    assert (
        _ask(api_client, manager, "Which products are at high risk?").json()["offline_reason"]
        == "rate_limited"
    )
    body = api_client.get("/api/v1/brain/assistant", headers=manager).json()
    assert body == {"synthetic": True, "available": False, "reason": "rate_limited"}
    assert model.probes == 0
    again = api_client.get(
        "/api/v1/brain/assistant", params={"recheck": "true"}, headers=manager
    ).json()
    assert again["available"] is True and model.probes == 1


def test_an_arabic_reply_quoting_product_names_is_arabic(
    first_night, api_client, manager, scripted
) -> None:
    def reply(results, _request) -> str:
        items = latest(results, "get_risk_list")["items"]
        return "الخطر المرتفع: " + "، ".join(
            f"{i['product_id']} {i['product_name']}" for i in items
        )

    model = scripted(Call("get_risk_list", {"risk": "high"}), Say(reply))
    body = _ask(api_client, manager, "ما المنتجات ذات الخطر العالي؟").json()
    assert body["outcome"] == "answered" and body["reply"]["language"] == "ar" and model.calls == 2
