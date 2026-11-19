"""Data cards: labeled figures built by code from the tool results (feature 005 extension).

The grounding guard checks that every number in a reply comes from the data, not that it carries
the right label: live, the model wrote "P001: 376 sold, 4 returned, 376 net" where net was 372. So a
turn that used the sales, risk or forecast tools also returns code-built cards with labeled
columns, drawn under the reply. Written first.
"""

from datetime import date
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import func, select

from brain.assistant.cards import build_cards
from brain.assistant.graph import SYSTEM
from brain.models import SalesDaily

from scripted_model import Call, Say, latest

URL = "/api/v1/brain/assistant/messages"
CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts/assistant/brain-api-assistant.openapi.yaml"
)

SUMMARY = {
    "name": "get_sales_history",
    "args": {},
    "result": {
        "scope": "all_products",
        "first_day": "2026-11-12",
        "last_day": "2026-11-18",
        "days_counted": 7,
        "products_counted": 20,
        "totals": {"units_sold": 3033, "units_returned": 55, "net_units": 2978},
        "top_products": [
            {
                "product_id": "P001",
                "product_name": "Paracetamol 500 mg tablets",
                "units_sold": 376,
                "units_returned": 4,
                "net_units": 372,
            },
            {
                "product_id": "P016",
                "product_name": "Vitamin C 1000 mg effervescent tablets",
                "units_sold": 325,
                "units_returned": 9,
                "net_units": 316,
            },
        ],
        "synthetic": True,
    },
}
RISK = {
    "name": "get_risk_list",
    "args": {"risk": "high"},
    "result": {
        "counts": {"high": 2, "medium": 0, "low": 18},
        "items": [
            {
                "product_id": "P003",
                "product_name": "Amoxicillin 500 mg capsules",
                "risk": "high",
                "days_of_cover": 2.83,
                "lead_time_days": 7,
                "order_qty": 108,
                "reason_code": None,
            },
            {
                "product_id": "P011",
                "product_name": "Azithromycin 250 mg tablets",
                "risk": "high",
                "days_of_cover": 3.02,
                "lead_time_days": 5,
                "order_qty": None,
                "reason_code": "OPEN_PO_UNAVAILABLE",
            },
        ],
        "synthetic": True,
    },
}
FORECAST = {
    "name": "get_forecast",
    "args": {"product_id": "P003", "days": 2},
    "result": {
        "product_id": "P003",
        "product_name": "Amoxicillin 500 mg capsules",
        "first_day": "2026-11-19",
        "last_day": "2026-11-20",
        "days_counted": 2,
        "days": [
            {"date": "2026-11-19", "forecast": 21.0, "low": 14.2, "high": 28.4},
            {"date": "2026-11-20", "forecast": 19.5, "low": 12.0, "high": 27.1},
        ],
        "total": {"forecast": 40.5, "low": 26.2, "high": 55.5},
        "synthetic": True,
    },
}
ONE_PRODUCT = {
    "name": "get_sales_history",
    "args": {"product_id": "P001", "days": 2},
    "result": {
        "scope": "product", "product_id": "P001", "product_name": "Paracetamol 500 mg tablets",
        "first_day": "2026-11-17", "last_day": "2026-11-18", "days_counted": 2,
        "days": [
            {"date": "2026-11-17", "units_sold": 60, "units_returned": 1, "net_units": 59, "day_status": "closed"},
            {"date": "2026-11-18", "units_sold": 52, "units_returned": 0, "net_units": 52, "day_status": "closed"},
        ],
        "totals": {"units_sold": 112, "units_returned": 1, "net_units": 111},
        "synthetic": True,
    },
}  # fmt: skip


def test_the_sales_summary_card_labels_sold_returned_and_net() -> None:
    """The live case: 376 sold, 4 returned, 372 net, each in its own labeled column."""
    [card] = build_cards([SUMMARY])
    assert card["kind"] == "sales_summary"
    assert card["columns"] == ["Product", "Sold", "Returned", "Net"]
    assert card["rows"][0] == ["P001 Paracetamol 500 mg tablets", 376, 4, 372]
    assert card["total"] == ["All products", 3033, 55, 2978]
    assert (card["first_day"], card["last_day"]) == ("2026-11-12", "2026-11-18")
    assert "2026-11-12" in card["title"] and "2026-11-18" in card["title"]


def test_the_risk_card() -> None:
    [card] = build_cards([RISK])
    assert card["kind"] == "risk"
    assert card["columns"] == ["Product", "Risk", "Days of cover", "Lead time", "Order"]
    assert card["rows"][0] == ["P003 Amoxicillin 500 mg capsules", "High", 2.83, "7 days", 108]
    assert card["rows"][1][-1] == "Open orders couldn't be read"


def test_the_forecast_and_product_sales_cards() -> None:
    forecast, sales = build_cards([FORECAST, ONE_PRODUCT])
    assert forecast["columns"] == ["Date", "Forecast", "Low", "High"]
    assert forecast["rows"][0] == ["2026-11-19", 21.0, 14.2, 28.4]
    assert forecast["total"] == ["Total", 40.5, 26.2, 55.5]
    assert sales["kind"] == "sales_history" and sales["columns"] == [
        "Date",
        "Sold",
        "Returned",
        "Net",
    ]
    assert sales["total"] == ["Total", 112, 1, 111]


def test_no_card_for_errors_or_other_tools() -> None:
    error = {
        "name": "get_forecast",
        "args": {"product_id": "P999"},
        "result": {"error": "UNKNOWN_PRODUCT", "synthetic": True},
    }
    stock = {
        "name": "get_stock",
        "args": {"product_id": "P003"},
        "result": {"available": 60, "synthetic": True},
    }
    propose = {
        "name": "propose_purchase_order",
        "args": {},
        "result": {"proposal_id": "x", "synthetic": True},
    }
    assert build_cards([error, stock, propose]) == []
    assert len(build_cards([SUMMARY, RISK, FORECAST, ONE_PRODUCT, SUMMARY])) == 4  # at most four


def _p001(worker_session, first: str, last: str) -> tuple[int, int, int]:
    row = worker_session.execute(
        select(
            func.sum(SalesDaily.units_sold),
            func.sum(SalesDaily.units_returned),
            func.sum(SalesDaily.net_units),
        ).where(
            SalesDaily.product_id == "P001",
            SalesDaily.day_status == "closed",
            SalesDaily.business_date.between(date.fromisoformat(first), date.fromisoformat(last)),
        )
    ).one()
    return tuple(int(v) for v in row)


def _mislabeled(results, _request) -> str:
    """The live mistake: P001's units sold reported as its net."""
    top = next(
        t for t in latest(results, "get_sales_history")["top_products"] if t["product_id"] == "P001"
    )
    return f"P001 had {top['units_sold']} net units this week."


def test_a_chat_turn_returns_the_card_even_when_the_text_mislabels(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    scripted(Call("get_sales_history", {}), Say(_mislabeled))
    body = api_client.post(
        URL,
        json={"messages": [{"role": "manager", "text": "give me a brief for our sales"}]},
        headers=manager,
    ).json()
    assert body["outcome"] == "answered"  # the guard can't see the wrong label
    [card] = body["cards"]
    sold, returned, net = _p001(worker_session, card["first_day"], card["last_day"])
    row = next(r for r in card["rows"] if r[0].startswith("P001 "))
    assert row[1:] == [sold, returned, net] and sold != net  # the card has the right labels
    schema = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    Draft202012Validator(
        {"$ref": "#/components/schemas/ChatReply", "components": schema["components"]},
        format_checker=FormatChecker(),
    ).validate(body)


def test_arabic_turns_get_the_same_english_labeled_card(
    first_night, api_client, manager, scripted
) -> None:
    scripted(
        Call("get_risk_list", {"risk": "high"}),
        Say(
            lambda r, q: (
                "الخطر المرتفع: "
                + "، ".join(i["product_id"] for i in latest(r, "get_risk_list")["items"])
            )
        ),
    )
    body = api_client.post(
        URL,
        json={"messages": [{"role": "manager", "text": "ما المنتجات ذات الخطر العالي؟"}]},
        headers=manager,
    ).json()
    assert body["reply"]["language"] == "ar"
    [card] = body["cards"]
    assert card["kind"] == "risk" and card["columns"] == [
        "Product",
        "Risk",
        "Days of cover",
        "Lead time",
        "Order",
    ]
    assert {r[0][:4] for r in card["rows"]} == {"P003", "P011", "P017"}


def test_no_cards_without_those_tools(first_night, api_client, manager, scripted) -> None:
    scripted(Call("get_stock", {"product_id": "P003"}), Say("P003 has stock."))
    body = api_client.post(
        URL, json={"messages": [{"role": "manager", "text": "P003 stock?"}]}, headers=manager
    ).json()
    assert body["cards"] == []


def test_the_instructions_ask_for_net_units() -> None:
    system = " ".join(SYSTEM.split())
    assert "report net units unless the manager asks for units sold or returned" in system
