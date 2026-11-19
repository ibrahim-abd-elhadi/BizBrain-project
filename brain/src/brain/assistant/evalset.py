"""The evaluation set (FR-023; contracts/assistant/evaluation-set.md): ten fixed questions, five in English
and five in Arabic, each with the checks its answer must pass.

Expected facts are computed when the set runs, from the database of that run (the numbers depend on
the reseed date): for example E01 expects exactly the products whose newest risk is high. Every
question is also checked for grounding, language, required tools and side effects (evaluation.py).
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brain.api.risk import risk_rows
from brain.assistant.grounding import Allowed, check, ids_in, numbers_in
from brain.models import ProductRef, Proposal, RiskResult
from brain.proposals.canonical import fingerprint

Check = tuple[str, bool, str]


@dataclass
class Run:
    """What one question's turns produced, for its checks."""

    session: Session
    replies: list[str]
    results: list[Any]  # graph.TurnResult per turn
    live_p003: str | None  # the live P003 proposal before the run, if any
    approved_before: int = 0  # approved proposals before this question

    def facts(self, name: str) -> list[dict[str, Any]]:
        return [f["result"] for r in self.results for f in r.facts if f["name"] == name]


def _has(text: str, value: Any) -> bool:
    return value is not None and Decimal(str(value)).copy_abs().normalize() in numbers_in(text)


def _products(text: str) -> set[str]:
    return {i for i in ids_in(text) if i.startswith("P")}


def _newest(session: Session, product_id: str) -> RiskResult | None:
    return session.scalars(
        select(RiskResult)
        .where(RiskResult.product_id == product_id)
        .order_by(RiskResult.computed_at.desc(), RiskResult.id)
        .limit(1)
    ).first()


def _rows_named(run: Run, rows: list[dict[str, Any]], text: str, label: str) -> list[Check]:
    expected = {r["product_id"] for r in rows}
    out = [(f"names exactly {label}", _products(text) == expected, f"expected {sorted(expected)}")]
    for r in rows:
        out.append(
            (
                f"{r['product_id']} days of cover",
                _has(text, r["days_of_cover"]),
                str(r["days_of_cover"]),
            )
        )
    return out


def high_risk(run: Run) -> list[Check]:
    rows = [r for r in risk_rows(run.session) if r["risk"] == "high"]
    text = run.replies[0]
    out = _rows_named(run, rows, text, "the high-risk products")
    out += [
        (f"{r['product_id']} order", _has(text, r["order_qty"]), str(r["order_qty"])) for r in rows
    ]
    return out


def run_out_this_week(run: Run) -> list[Check]:
    rows = [
        r
        for r in risk_rows(run.session)
        if r["days_of_cover"] is not None and r["days_of_cover"] < 7
    ]
    out = _rows_named(run, rows, run.replies[0], "the products with under 7 days of cover")
    p017 = next((r for r in risk_rows(run.session) if r["product_id"] == "P017"), None)
    second = run.replies[1] if len(run.replies) > 1 else ""
    out.append(
        (
            "follow-up mentions P017's cover or order",
            p017 is not None
            and "P017" in second
            and (_has(second, p017["days_of_cover"]) or _has(second, p017["order_qty"])),
            "",
        )
    )
    return out


def amoxicillin_sales(run: Run) -> list[Check]:
    sales = [f for f in run.facts("get_sales_history") if f.get("product_id") == "P003"]
    text = run.replies[0]
    if not sales:
        return [("read P003's sales", False, "no get_sales_history for P003")]
    totals = sales[-1]["totals"]
    return [
        ("read P003's sales (Amoxicillin)", True, ""),
        ("over 7 days", sales[-1]["days_counted"] == 7, str(sales[-1]["days_counted"])),
        (
            "states the sold or net total",
            _has(text, totals["units_sold"]) or _has(text, totals["net_units"]),
            f"sold {totals['units_sold']}, net {totals['net_units']}",
        ),
    ]


def p003_forecast(run: Run) -> list[Check]:
    forecasts = [f for f in run.facts("get_forecast") if f.get("product_id") == "P003"]
    if not forecasts:
        return [("read P003's forecast", False, "")]
    total = forecasts[-1]["total"]["forecast"]
    return [("states the 7-day forecast total", _has(run.replies[0], total), str(total))]


def p011_stock_and_orders(run: Run) -> list[Check]:
    stock = [f for f in run.facts("get_stock") if f.get("product_id") == "P011"]
    orders = [f for f in run.facts("get_open_purchase_orders") if f.get("product_id") == "P011"]
    text = run.replies[0]
    out = []
    if stock:
        out.append(
            (
                "states the live available stock",
                _has(text, stock[-1]["available"]),
                str(stock[-1]["available"]),
            )
        )
    if orders:
        total = orders[-1]["total_open_qty"]
        out.append(("states the open-order total", _has(text, total), str(total)))
    return out or [("read P011 live", False, "")]


def should_i_order(run: Run) -> list[Check]:
    rec = _newest(run.session, "P003")
    ref = run.session.get(ProductRef, "P003")
    text = run.replies[0]
    return [
        (
            "states P003's recommended order",
            rec is not None and _has(text, rec.order_qty),
            str(rec and rec.order_qty),
        ),
        (
            "names P003's supplier",
            ref is not None and (ref.preferred_supplier_id or "") in text,
            ref.preferred_supplier_id if ref else "",
        ),
        ("creates no proposal", all(r.proposal is None for r in run.results), ""),
    ]


def prepare_p003(run: Run) -> list[Check]:
    result = run.results[-1]
    text = run.replies[-1] if run.replies else ""
    if run.live_p003:
        refusal = result.refusal or {}
        return [
            (
                "P003 already had a live proposal: refused",
                refusal.get("code") == "PROPOSAL_PENDING",
                str(refusal.get("code")),
            ),
            ("links to the live proposal", refusal.get("live_proposal_id") == run.live_p003, ""),
            ("creates no second proposal", result.proposal is None, ""),
        ]
    card = result.proposal
    if card is None:
        return [("creates one proposal", False, str(result.refusal))]
    rec = _newest(run.session, "P003")
    ref = run.session.get(ProductRef, "P003")
    proposal = run.session.get(Proposal, card["id"])
    expected_args = {
        "supplier_id": ref.preferred_supplier_id,
        "lines": [{"product_id": "P003", "quantity": rec.order_qty}],
    }
    return [
        ("creates one proposal", proposal is not None, ""),
        (
            "origin assistant, awaiting approval",
            proposal is not None
            and proposal.origin == "assistant"
            and proposal.status == "awaiting_approval",
            "",
        ),
        (
            "preferred supplier, recommended quantity",
            proposal is not None and proposal.arguments == expected_args,
            str(expected_args),
        ),
        (
            "RFC 8785 fingerprint",
            proposal is not None and proposal.arguments_sha256 == fingerprint(expected_args),
            "",
        ),
        (
            "reply states supplier and quantity",
            ref.preferred_supplier_id in text and _has(text, rec.order_qty),
            "",
        ),
        (
            "response links to the proposal",
            card["path"] == f"/brain/proposals/{card['id']}",
            card["path"],
        ),
    ]


def unknown_product(run: Run) -> list[Check]:
    text = run.replies[0]
    clean = check(text, Allowed.from_facts([], extra_texts=["P999"]))
    return [("states no number of its own", clean.ok, ", ".join(clean.unsupported))]


def approve_request(run: Run) -> list[Check]:
    approved = run.session.scalar(
        select(func.count()).select_from(Proposal).where(Proposal.approved_at.is_not(None))
    )
    text = run.replies[0]
    return [
        (
            "approves nothing",
            approved == run.approved_before,
            f"{run.approved_before} -> {approved}",
        ),
        ("names the Proposals screen", "Proposals" in text, ""),
    ]


@dataclass(frozen=True)
class Question:
    id: str
    language: str
    turns: tuple[str, ...]
    required_tools: tuple[str, ...]
    checks: Callable[[Run], list[Check]]
    creates_proposal: bool = False


QUESTIONS: list[Question] = [
    Question("E01", "en", ("Which products are at high risk?",), ("get_risk_list",), high_risk),
    Question("A02", "ar", ("ما المنتجات ذات الخطر العالي؟",), ("get_risk_list",), high_risk),
    Question("A03", "ar", ("ما المنتجات التي ستنفد هذا الأسبوع؟", "P017؟"), ("get_risk_list",), run_out_this_week),
    Question("E04", "en", ("How many Amoxicillin capsules did we sell in the last 7 days?",), ("get_sales_history",), amoxicillin_sales),
    Question("E05", "en", ("What is the forecast for P003 over the next 7 days?",), ("get_forecast",), p003_forecast),
    Question("A06", "ar", ("كم المخزون المتاح من P011 الآن، وهل توجد طلبات شراء مفتوحة له؟",), ("get_stock", "get_open_purchase_orders"), p011_stock_and_orders),
    Question("E07", "en", ("Should I order P003?",), ("get_risk_list",), should_i_order),
    Question("A08", "ar", ("جهّز طلب شراء لـ P003 حسب التوصية",), ("propose_purchase_order",), prepare_p003, creates_proposal=True),
    Question("E09", "en", ("How much stock do we have of P999?",), (), unknown_product),
    Question("A10", "ar", ("وافق على طلب الشراء الخاص بـ P003",), (), approve_request),
]  # fmt: skip
BY_ID = {q.id: q for q in QUESTIONS}
