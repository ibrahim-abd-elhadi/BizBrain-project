"""The grounding guard (research R-04; contracts/assistant-tools.md). Written first (T005).

Every number, ISO date and product or supplier ID in a generated text must appear in the data the
Brain supplied (D-18, FR-015).
"""

from decimal import Decimal

import pytest

from brain.assistant.grounding import Allowed, check, normalize

RISK = {
    "items": [
        {
            "product_id": "P003",
            "product_name": "Amoxicillin 500 mg capsules",
            "days_of_cover": 2.83,
            "lead_time_days": 7,
            "order_qty": 108,
            "supplier_id": "S004",
        },
    ],
    "counts": {"high": 3, "medium": 0, "low": 17},
    "computed_through": "2026-11-17",
}


def _ok(text: str, facts=RISK, extra=()) -> bool:
    return check(text, Allowed.from_facts(facts, extra_texts=extra)).ok


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("P003 has 2.83 days of cover vs a 7-day lead time; order 108", True),
        ("لدى P003 تغطية ٢٫٨٣ يوم مقابل مهلة توريد ٧ أيام؛ اطلب ١٠٨", True),
        ("about 2.8 days", False),
        ("three products are high", True),
        ("P999 has no stock", False),
        ("on 2026-11-20", False),
        ("as of 2026-11-17", True),
        ("Amoxicillin 500 mg is short", True),
        ("P003 needs 108 from S004", True),
        ("S009 supplies it", False),
    ],
)
def test_the_contract_examples(text: str, ok: bool) -> None:
    assert _ok(text) is ok


def test_three_is_refused_when_no_three_is_in_the_facts() -> None:
    assert not _ok("three products are high", facts={"items": [{"order_qty": 108}]})


def test_thousands_separators_and_values() -> None:
    facts = {"total": 1234, "cover": 2.83, "qty": 108.0}
    assert _ok("sold 1,234 units", facts)
    assert _ok("sold ١٬٢٣٤ units", facts)
    assert _ok("2.830 days and 108 units", facts)
    assert _ok("٢٫٨٣ يوم", facts)
    assert _ok("۲٫۸۳ day", facts)  # Eastern Arabic-Indic digits
    assert not _ok("1,235 units", facts)


def test_percent_signs_are_numbers_too() -> None:
    assert _ok("down 25%", {"change": 25})
    assert _ok("down ٢٥٪", {"change": 25})
    assert not _ok("down 30%", {"change": 25})


def test_number_words_are_checked_in_english_and_arabic() -> None:
    facts = {"counts": {"high": 3, "low": 17}}
    assert _ok("Three products are high", facts)
    assert _ok("ثلاثة منتجات مرتفعة الخطر", facts)
    assert _ok("ثلاث منتجات", facts)
    assert _ok("seventeen are low", facts)
    assert _ok("سبعة عشر منتجًا منخفض الخطر", facts)
    assert not _ok("five products", facts)
    assert not _ok("خمسة منتجات", facts)
    assert not _ok("عشرة منتجات", facts)


def test_one_and_its_arabic_forms_are_not_checked() -> None:
    assert _ok("one of the products", {"x": 3})
    assert _ok("منتج واحد ودرجة واحدة", {"x": 3})


def test_numbers_in_extra_texts_are_allowed() -> None:
    assert _ok("yes, it is more than 40", {"x": 3}, extra=["is it more than 40?"])
    assert not _ok("yes, it is more than 40", {"x": 3})


def test_nested_facts_and_number_types_are_walked() -> None:
    facts = [{"a": [Decimal("145.0000"), {"b": 23}]}, 1.59, "net 7 units on 2026-11-10", True]
    assert _ok("145 plus 23, cover 1.59, 7 units on 2026-11-10", facts)


def test_booleans_are_not_numbers() -> None:
    assert not _ok("1 product", {"flag": True})


def test_ids_inside_arabic_words_are_found() -> None:
    assert _ok("جهّزت طلبًا لـP003 من S004", RISK)
    assert not _ok("جهّزت طلبًا لـP777", RISK)


def test_unsupported_tokens_are_listed_in_order() -> None:
    result = check("P999 on 2026-12-01 needs 5 and 2.83", Allowed.from_facts(RISK))
    assert result.ok is False
    assert result.unsupported == ["P999", "2026-12-01", "5"]


def test_normalize_maps_digits_and_separators() -> None:
    assert normalize("٢٫٨٣ و ١٬٢٣٤ و ۷ و ٪") == "2.83 و 1234 و 7 و %"
