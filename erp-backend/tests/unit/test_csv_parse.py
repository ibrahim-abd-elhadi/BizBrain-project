"""CSV parsing and row checks (contracts/sales-upload-csv.md). Written before the implementation."""

from datetime import date

import pytest

from erp.services.csv_upload import (
    HEADER,
    MAX_BYTES,
    MAX_ROWS,
    CsvRow,
    FileRefused,
    dedupe,
    parse,
    validate,
)

HEADER_LINE = "business_date,product_id,units_sold,units_returned"
TODAY = date(2026, 11, 18)
KNOWN = {"P001", "P002", "P007"}


def csv_bytes(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def refusal(data: bytes) -> str:
    with pytest.raises(FileRefused) as caught:
        parse(data)
    assert caught.value.status_code == 422
    return caught.value.code


def row_code(*cells: str) -> str | None:
    found = validate(CsvRow(2, tuple(cells)), TODAY, KNOWN)
    return found.code if found else None


# Whole-file rules


def test_exact_header_is_accepted_also_with_a_byte_order_mark() -> None:
    plain = parse(csv_bytes(HEADER_LINE, "2026-11-18,P001,5,0"))
    with_bom = parse(b"\xef\xbb\xbf" + csv_bytes(HEADER_LINE, "2026-11-18,P001,5,0"))
    assert plain == with_bom == [CsvRow(2, ("2026-11-18", "P001", "5", "0"))]
    assert HEADER == ["business_date", "product_id", "units_sold", "units_returned"]


@pytest.mark.parametrize(
    "header",
    [
        "product_id,business_date,units_sold,units_returned",  # wrong order
        "Business_Date,product_id,units_sold,units_returned",  # wrong case
        "business_date,product_id,units_sold",  # a column missing
        "business_date,product_id,units_sold,units_returned,extra",  # a column too many
        "2026-11-18,P001,5,0",  # no header at all
    ],
)
def test_a_wrong_header_refuses_the_file(header: str) -> None:
    assert refusal(csv_bytes(header, "2026-11-18,P001,5,0")) == "BAD_HEADER"


def test_file_over_one_mebibyte_is_refused() -> None:
    assert MAX_BYTES == 1_048_576
    assert refusal(b"x" * (MAX_BYTES + 1)) == "FILE_TOO_LARGE"


def test_5001_data_rows_are_too_many_but_5000_are_fine() -> None:
    assert MAX_ROWS == 5000
    rows = ["2026-11-18,P001,1,0"] * 5001
    assert refusal(csv_bytes(HEADER_LINE, *rows)) == "TOO_MANY_ROWS"
    assert len(parse(csv_bytes(HEADER_LINE, *rows[:5000]))) == 5000


def test_header_only_or_empty_file_is_refused() -> None:
    assert refusal(csv_bytes(HEADER_LINE)) == "EMPTY_FILE"
    assert refusal(b"") == "EMPTY_FILE"


def test_invalid_utf8_is_refused() -> None:
    assert refusal(HEADER_LINE.encode() + b"\n2026-11-18,P0\xff1,5,0\n") == "NOT_UTF8"


# Reading rows


def test_cells_are_trimmed_and_row_numbers_are_line_numbers() -> None:
    rows = parse(csv_bytes(HEADER_LINE, " 2026-11-18 , P001 , 5 , 0 ", "2026-11-18,P002,7,1"))
    assert rows == [
        CsvRow(2, ("2026-11-18", "P001", "5", "0")),
        CsvRow(3, ("2026-11-18", "P002", "7", "1")),
    ]


def test_windows_line_endings_and_blank_lines_keep_line_numbers() -> None:
    data = f"{HEADER_LINE}\r\n2026-11-18,P001,5,0\r\n\r\n2026-11-18,P002,7,1\r\n".encode()
    assert [r.number for r in parse(data)] == [2, 4]


def test_a_row_with_three_cells_is_kept_and_refused_by_the_row_check() -> None:
    rows = parse(csv_bytes(HEADER_LINE, "2026-11-18,P001,5"))
    assert rows == [CsvRow(2, ("2026-11-18", "P001", "5"))]
    assert row_code("2026-11-18", "P001", "5") == "WRONG_COLUMN_COUNT"
    assert row_code("2026-11-18", "P001", "5", "0", "9") == "WRONG_COLUMN_COUNT"


# Row rules


def test_a_good_row_has_no_refusal() -> None:
    assert row_code("2026-11-18", "P001", "5", "0") is None
    assert row_code("2026-11-18", "P007", "0", "0") is None


@pytest.mark.parametrize("bad_date", ["2026-11-31", "18/11/2026", "2026-1-5", "20261118", "", "x"])
def test_bad_dates(bad_date: str) -> None:
    assert row_code(bad_date, "P001", "5", "0") == "BAD_DATE_FORMAT"


def test_dates_before_or_after_today() -> None:
    assert row_code("2026-11-17", "P001", "5", "0") == "DAY_CLOSED"
    assert row_code("2020-01-01", "P001", "5", "0") == "DAY_CLOSED"
    assert row_code("2026-11-19", "P001", "5", "0") == "FUTURE_DATE"


def test_unknown_product() -> None:
    assert row_code("2026-11-18", "P999", "5", "0") == "UNKNOWN_PRODUCT"
    assert row_code("2026-11-18", "p001", "5", "0") == "UNKNOWN_PRODUCT"


@pytest.mark.parametrize("bad", ["1.5", "-1", "+2", "", "ten", "1e3", "２", "99999999999"])
def test_bad_units(bad: str) -> None:
    assert row_code("2026-11-18", "P001", bad, "0") == "BAD_UNITS"
    assert row_code("2026-11-18", "P001", "5", bad) == "BAD_UNITS"


def test_the_first_failing_rule_wins() -> None:
    # Closed day AND unknown product AND bad units: the date rule comes first.
    assert row_code("2026-11-17", "P999", "-1", "0") == "DAY_CLOSED"


# Duplicates


def test_the_last_row_for_a_product_and_date_wins_and_the_others_are_reported() -> None:
    rows = parse(
        csv_bytes(
            HEADER_LINE,
            "2026-11-18,P001,15,1",  # 2
            "2026-11-18,P002,7,0",  # 3  overridden by 6
            "2026-11-17,P003,4,0",  # 4
            "2026-11-18,P999,3,0",  # 5
            "2026-11-18,P002,9,1",  # 6
            "2026-11-18,P002,1,0",  # 7  (a third copy: 3 and 6 are both overridden by 7)
        )
    )
    kept, overridden = dedupe(rows)
    assert [r.number for r in kept] == [2, 4, 5, 7]
    assert overridden == [(3, 7), (6, 7)]


def test_rows_with_the_wrong_cell_count_are_never_treated_as_duplicates() -> None:
    kept, overridden = dedupe([CsvRow(2, ("a", "b", "c")), CsvRow(3, ("a", "b", "c"))])
    assert [r.number for r in kept] == [2, 3]
    assert overridden == []
