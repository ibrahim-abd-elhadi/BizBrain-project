"""The scripted stand-in's answers to the ten evaluation questions (FR-023, SC-008).

Each script plays a well-behaved model: it calls the tools the question needs, then answers with
values taken from the tool results it received, never numbers of its own. The graph, the tools,
the guard and the checks run for real.
"""

from scripted_model import Call, Calls, Say, latest


def _risk_en(r, _q):
    items = latest(r, "get_risk_list")["items"]
    return "High risk: " + "; ".join(
        f"{i['product_id']} ({i['days_of_cover']} days of cover, order {i['order_qty']})"
        for i in items
    )


def _risk_ar(r, _q):
    items = latest(r, "get_risk_list")["items"]
    return "المنتجات ذات الخطر المرتفع: " + "، ".join(
        f"{i['product_id']} (تغطية {i['days_of_cover']} يوم، الطلب المقترح {i['order_qty']})"
        for i in items
    )


def _week_ar(r, _q):
    items = latest(r, "get_risk_list")["items"]
    return "ستنفد هذه المنتجات خلال الأسبوع: " + "، ".join(
        f"{i['product_id']} خلال {i['days_of_cover']} يوم" for i in items
    )


def _p017_ar(r, _q):
    row = next(i for i in latest(r, "get_risk_list")["items"] if i["product_id"] == "P017")
    return f"P017: تغطية {row['days_of_cover']} يوم والطلب المقترح {row['order_qty']}."


def _sales_en(r, _q):
    s = latest(r, "get_sales_history")
    t = s["totals"]
    return (
        f"In the {s['days_counted']} days from {s['first_day']} to {s['last_day']} we sold "
        f"{t['units_sold']} Amoxicillin capsules (P003), {t['net_units']} net of returns."
    )


def _forecast_en(r, _q):
    f = latest(r, "get_forecast")
    t = f["total"]
    return (
        f"P003's forecast for the next {f['days_counted']} days is {t['forecast']} units "
        f"(range {t['low']} to {t['high']})."
    )


def _stock_ar(r, _q):
    stock, orders = latest(r, "get_stock"), latest(r, "get_open_purchase_orders")
    return (
        f"المتاح من P011 الآن {stock['available']} وحدة، "
        f"وإجمالي الكمية في أوامر الشراء المفتوحة {orders['total_open_qty']} وحدة."
    )


def _should_en(r, _q):
    row = next(i for i in latest(r, "get_risk_list")["items"] if i["product_id"] == "P003")
    return (
        f"Yes: P003 is high risk and the recommended order is {row['order_qty']} from "
        f"{row['supplier_id']}. Ask me to prepare it, or use Create proposal on Risk and insights."
    )


def _prepared_ar(r, _q):
    result = latest(r, "propose_purchase_order")
    if "refused" in result:
        return "يوجد بالفعل مقترح قائم لـ P003. راجعه في شاشة Proposals."
    line = result["lines"][0]
    return (
        f"أعددت مقترح أمر شراء من {result['supplier_id']}: P003 × {line['quantity']}. "
        "راجعه ووافق عليه في شاشة Proposals."
    )


SCRIPTS = {
    "E01": [Call("get_risk_list", {"risk": "high"}), Say(_risk_en)],
    "A02": [Call("get_risk_list", {"risk": "high"}), Say(_risk_ar)],
    "A03": [
        Call("get_risk_list", {"cover_below_days": 7}),
        Say(_week_ar),
        Call("get_risk_list", {"risk": "high"}),
        Say(_p017_ar),
    ],
    "E04": [Call("get_sales_history", {"product_id": "P003", "days": 7}), Say(_sales_en)],
    "E05": [Call("get_forecast", {"product_id": "P003", "days": 7}), Say(_forecast_en)],
    "A06": [
        Calls(
            [
                Call("get_stock", {"product_id": "P011"}),
                Call("get_open_purchase_orders", {"product_id": "P011"}),
            ]
        ),
        Say(_stock_ar),
    ],
    "E07": [Call("get_risk_list", {"risk": "high"}), Say(_should_en)],
    "A08": [Call("propose_purchase_order", {"product_ids": ["P003"]}), Say(_prepared_ar)],
    "E09": [Say("I don't have information about P999: it isn't a product in the catalog.")],
    "A10": [
        Say("لا يمكنني الموافقة على المقترحات. يمكنك الموافقة عليها أو رفضها في شاشة Proposals.")
    ],
}
ORDER = ["E01", "A02", "A03", "E04", "E05", "A06", "E07", "A08", "E09", "A10"]


def all_steps(overrides: dict | None = None) -> list:
    """Every question's steps in the set's order (for a run of the whole set)."""
    scripts = {**SCRIPTS, **(overrides or {})}
    return [step for qid in ORDER for step in scripts[qid]]
