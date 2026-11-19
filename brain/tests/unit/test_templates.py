"""The Why? templates (contracts/assistant/explanation-templates.md; FR-013, FR-014). Written first (T047).

The template is the plain version: built each time from the row's facts, never stored, and what
the model is asked to rephrase. Every branch renders in English and Arabic and passes the grounding
guard against its own facts.
"""

import pytest

from brain.assistant.explain import render_template
from brain.assistant.grounding import Allowed, check
from brain.assistant.language import is_language

P003 = {
    "product_id": "P003",
    "product_name": "Amoxicillin 500 mg capsules",
    "supplier_id": "S004",
    "supplier_name": "Delta Health Trading",
    "days_of_cover": 2.83,
    "lead_time_days": 7,
    "medium_margin_days": 2,
    "lead_plus_2": 9,
    "base_risk": "high",
    "risk": "high",
    "raised_by_spike": False,
    "spike_date": None,
    "spike_z": None,
    "cover_days_counted": 7,
    "forecast_over_lead": 145.0,
    "safety_stock": 23,
    "target": 168,
    "available": 60,
    "open_po_qty": 0,
    "raw": 108,
    "pack_multiple": 12,
    "max_order_qty": 240,
    "order_qty": 108,
    "reason_code": None,
}

EN = (
    "Amoxicillin 500 mg capsules (P003) has 2.83 days of cover against a 7-day lead time from Delta "
    "Health Trading (S004). That is less than the lead time, so the risk is high. Forecast demand "
    "over the next 7 days is 145 units; with 23 units of safety stock, the target is 168. Minus 60 "
    "available and 0 on order leaves 108. Rounded up to packs of 12, the order is 108."
)
AR = (
    "يغطي مخزون Amoxicillin 500 mg capsules (P003) مدة 2.83 يوم، ومهلة التوريد من Delta Health "
    "Trading (S004) هي 7 يوم. وهذا أقل من مهلة التوريد، لذا فالخطر مرتفع. الطلب المتوقع خلال 7 يوم "
    "القادمة هو 145 وحدة، ومع مخزون أمان قدره 23 وحدة يصبح الهدف 168. وبعد خصم 60 متاحة و0 قيد "
    "الطلب يتبقى 108. وبالتقريب لأعلى إلى عبوات من 12 تكون كمية الطلب 108."
)


def facts(**overrides):
    return {**P003, **overrides}


BRANCHES = {
    "high": facts(),
    "medium": facts(days_of_cover=7.83, base_risk="medium", risk="medium", raw=12, order_qty=12),
    "low": facts(days_of_cover=14.04, lead_time_days=2, lead_plus_2=4, cover_days_counted=2,
                 base_risk="low", risk="low", raw=-500, order_qty=0, target=130, available=762),
    "spike": facts(days_of_cover=17.64, lead_time_days=3, lead_plus_2=5, cover_days_counted=3,
                   base_risk="low", risk="medium", raised_by_spike=True, spike_date="2026-11-18",
                   spike_z=5.2, raw=-387, order_qty=0, target=107, available=494),
    "no_demand": facts(days_of_cover=None, base_risk="low", risk="low", raw=-60, order_qty=0,
                       forecast_over_lead=0.0, safety_stock=0, target=0),
    "no_supplier": facts(lead_time_days=None, lead_plus_2=None, cover_days_counted=None,
                         base_risk=None, risk=None, raw=None, order_qty=None, target=None,
                         safety_stock=None, forecast_over_lead=None, reason_code="NO_SUPPLIER"),
    "open_po_unavailable": facts(open_po_qty=None, raw=None, order_qty=None,
                                 reason_code="OPEN_PO_UNAVAILABLE"),
    "pack_one": facts(pack_multiple=1, raw=29, order_qty=29),
    "capped": facts(raw=500, pack_multiple=10, max_order_qty=300, order_qty=300),
}  # fmt: skip


def test_the_worked_example_word_for_word() -> None:
    assert render_template(P003, "en") == EN
    assert render_template(P003, "ar") == AR


@pytest.mark.parametrize("branch", sorted(BRANCHES))
@pytest.mark.parametrize("language", ["en", "ar"])
def test_every_branch_is_grounded_and_in_its_language(branch: str, language: str) -> None:
    f = BRANCHES[branch]
    text = render_template(f, language)
    assert text
    result = check(text, Allowed.from_facts(f))
    assert result.ok, (branch, language, result.unsupported, text)
    assert is_language(text, language), text


def test_the_branch_sentences() -> None:
    assert "so the risk is medium" in render_template(BRANCHES["medium"], "en")
    assert "lead time plus 2 days (9)" in render_template(BRANCHES["medium"], "en")
    assert "so the risk is low" in render_template(BRANCHES["low"], "en")
    assert "nothing more is needed, so no order is recommended" in render_template(
        BRANCHES["low"], "en"
    )
    spike = render_template(BRANCHES["spike"], "en")
    assert (
        "A demand spike on 2026-11-18 (z = 5.2) raised the risk one level, from low to medium."
        in spike
    )
    assert "من منخفض إلى متوسط" in render_template(BRANCHES["spike"], "ar")
    assert "has no forecast demand" in render_template(BRANCHES["no_demand"], "en")
    no_supplier = render_template(BRANCHES["no_supplier"], "en")
    assert "lead time couldn't be read, so no risk level is set" in no_supplier
    assert "(NO_SUPPLIER)" in no_supplier
    assert "(OPEN_PO_UNAVAILABLE)" in render_template(BRANCHES["open_po_unavailable"], "en")
    assert render_template(BRANCHES["pack_one"], "en").endswith("leaves 29. The order is 29.")
    assert "capped at the maximum order of 300, the order is 300." in render_template(
        BRANCHES["capped"], "en"
    )


def test_forecast_values_drop_a_trailing_zero() -> None:
    assert "is 145 units" in render_template(P003, "en")
    assert "is 42.7 units" in render_template(facts(forecast_over_lead=42.74), "en")
