"""Data cards: labeled figures built by code from a turn's tool results (feature 005 extension).

The grounding guard checks that every number in a reply comes from the data, not that it carries
the right label (live: "376 net" where 376 was units sold and net was 372). So the chat also
returns small tables built here, never by the model, for the sales, risk-list and forecast tools;
the Assistant screen draws them under the reply. Labels are English, like every screen (FR-001a).
"""

from typing import Any

MAX_CARDS = 4
RISK_WORDS = {"high": "High", "medium": "Medium", "low": "Low"}
REASON_WORDS = {
    "OPEN_PO_UNAVAILABLE": "Open orders couldn't be read",
    "NO_SUPPLIER": "Supplier couldn't be read",
}


def _product(item: dict[str, Any]) -> str:
    return f"{item['product_id']} {item.get('product_name') or ''}".strip()


def _days(n: Any) -> str | None:
    if n is None:
        return None
    return f"{n} day" if n == 1 else f"{n} days"


def _sales_summary(r: dict[str, Any]) -> dict[str, Any]:
    t = r["totals"]
    return {
        "kind": "sales_summary",
        "title": f"Sales, all products, {r['first_day']} to {r['last_day']} "
        f"({r['days_counted']} closed days)",
        "first_day": r["first_day"],
        "last_day": r["last_day"],
        "columns": ["Product", "Sold", "Returned", "Net"],
        "rows": [
            [_product(p), p["units_sold"], p["units_returned"], p["net_units"]]
            for p in r["top_products"]
        ],
        "total": ["All products", t["units_sold"], t["units_returned"], t["net_units"]],
    }


def _sales_history(r: dict[str, Any]) -> dict[str, Any]:
    t = r["totals"]
    return {
        "kind": "sales_history",
        "title": f"Sales of {_product(r)}, {r['first_day']} to {r['last_day']}",
        "first_day": r["first_day"],
        "last_day": r["last_day"],
        "columns": ["Date", "Sold", "Returned", "Net"],
        "rows": [
            [d["date"], d["units_sold"], d["units_returned"], d["net_units"]] for d in r["days"]
        ],
        "total": ["Total", t["units_sold"], t["units_returned"], t["net_units"]],
    }


def _risk(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "risk",
        "title": "Stock-out risk and recommended orders",
        "first_day": None,
        "last_day": None,
        "columns": ["Product", "Risk", "Days of cover", "Lead time", "Order"],
        "rows": [
            [
                _product(i),
                RISK_WORDS.get(i.get("risk"), "No lead time"),
                i["days_of_cover"] if i.get("days_of_cover") is not None else "unlimited",
                _days(i.get("lead_time_days")),
                REASON_WORDS.get(i["reason_code"], i["reason_code"])
                if i.get("reason_code")
                else i.get("order_qty"),
            ]
            for i in r["items"]
        ],
        "total": None,
    }


def _forecast(r: dict[str, Any]) -> dict[str, Any]:
    t = r["total"]
    return {
        "kind": "forecast",
        "title": f"Forecast for {_product(r)}, {r['first_day']} to {r['last_day']}",
        "first_day": r["first_day"],
        "last_day": r["last_day"],
        "columns": ["Date", "Forecast", "Low", "High"],
        "rows": [[d["date"], d["forecast"], d["low"], d["high"]] for d in r["days"]],
        "total": ["Total", t["forecast"], t["low"], t["high"]],
    }


def build_cards(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One card per successful sales, risk-list or forecast call of the turn, at most four."""
    cards: list[dict[str, Any]] = []
    for fact in facts:
        result = fact.get("result") or {}
        if "error" in result:
            continue
        name = fact.get("name")
        if name == "get_sales_history" and result.get("scope") == "all_products":
            card = _sales_summary(result)
        elif name == "get_sales_history" and result.get("days"):
            card = _sales_history(result)
        elif name == "get_risk_list" and result.get("items") is not None:
            card = _risk(result)
        elif name == "get_forecast" and result.get("days"):
            card = _forecast(result)
        else:
            continue
        cards.append(card)
        if len(cards) == MAX_CARDS:
            break
    return cards
