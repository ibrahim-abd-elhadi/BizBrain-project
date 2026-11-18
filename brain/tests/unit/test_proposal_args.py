"""Proposal arguments: validation and line order (feature 004, research R-02; FR-007).
Written before the implementation."""

import uuid

import pytest

from brain.proposals.canonical import fingerprint
from brain.proposals.service import ProposalRefused, build_arguments, check_origin


def test_lines_are_sorted_so_equal_arguments_give_one_fingerprint() -> None:
    a = build_arguments(
        "S001", [{"product_id": "P002", "quantity": 30}, {"product_id": "P001", "quantity": 60}]
    )
    b = build_arguments(
        "S001", [{"product_id": "P001", "quantity": 60}, {"product_id": "P002", "quantity": 30}]
    )
    assert (
        a
        == b
        == {
            "supplier_id": "S001",
            "lines": [
                {"product_id": "P001", "quantity": 60},
                {"product_id": "P002", "quantity": 30},
            ],
        }
    )
    assert fingerprint(a) == "4d26045c552bc3ce10d209ceb1f2a4d03b410166fd2a1bbe9b25c9aabb753629"


def test_the_largest_allowed_proposal() -> None:
    lines = [{"product_id": f"P{n:03d}", "quantity": 1_000_000} for n in range(1, 51)]
    assert len(build_arguments("S004", lines)["lines"]) == 50


def _line(product="P001", quantity=10):
    return {"product_id": product, "quantity": quantity}


@pytest.mark.parametrize(
    ("supplier", "lines"),
    [
        ("X004", [_line()]),
        ("s004", [_line()]),
        ("S4", [_line()]),
        ("S004", [_line("p001")]),
        ("S004", [_line("P1")]),
        ("S004", []),
        ("S004", [_line(f"P{n:03d}") for n in range(1, 52)]),
        ("S004", [_line(quantity=0)]),
        ("S004", [_line(quantity=-1)]),
        ("S004", [_line(quantity=1_000_001)]),
        ("S004", [_line(quantity=1.5)]),
        ("S004", [_line(quantity=True)]),
        ("S004", [_line(), _line()]),
        ("S004", [{"product_id": "P001"}]),
        ("S004", [{"product_id": "P001", "quantity": 1, "note": "x"}]),
    ],
    ids=[
        "supplier letter",
        "supplier lower case",
        "supplier short",
        "product lower case",
        "product short",
        "no lines",
        "51 lines",
        "quantity 0",
        "quantity -1",
        "quantity too big",
        "quantity float",
        "quantity bool",
        "product twice",
        "quantity missing",
        "extra field",
    ],
)
def test_invalid_arguments_are_refused(supplier, lines) -> None:
    with pytest.raises(ProposalRefused) as caught:
        build_arguments(supplier, lines)
    assert caught.value.code == "VALIDATION_ERROR"


def test_origin_and_recommendation_must_match() -> None:
    check_origin("recommendation", uuid.uuid4())
    check_origin("assistant", None)
    for origin, rec in (("recommendation", None), ("assistant", uuid.uuid4()), ("chat", None)):
        with pytest.raises(ProposalRefused) as caught:
            check_origin(origin, rec)
        assert caught.value.code == "VALIDATION_ERROR"
