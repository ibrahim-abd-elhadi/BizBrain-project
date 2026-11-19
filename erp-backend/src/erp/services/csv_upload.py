"""Upload CSV: replace today's daily totals from a file (FR-013, FR-014, FR-026).

The format is in contracts/erp/sales-upload-csv.md. Processing order (research R-20):
parse the whole file, keep only the last row per product and date, validate each kept row, then
apply every accepted row in one transaction. A row that fails is refused and reported; the others
are still recorded. A bad file (header, size, encoding, row count) is refused as a whole.
"""

import csv
import io
import re
from datetime import date
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.clock import now_utc, today_cairo
from erp.errors import ErpError
from erp.models import DailySales, Product
from erp.schemas.upload import AcceptedRow, OverriddenRow, RefusedRow, UploadResult
from erp.services import stock
from erp.services.day_close import close_past_days

MAX_BYTES = 1_048_576
MAX_ROWS = 5000
HEADER = ["business_date", "product_id", "units_sold", "units_returned"]
# A cell can't be longer than the file, so the csv module never refuses a field for its length.
csv.field_size_limit(MAX_BYTES)

# One cell may not exceed this many units: it keeps the integer columns far from overflow.
MAX_UNITS = 1_000_000

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_UNITS = re.compile(r"[0-9]+")


class FileRefused(ErpError):
    """The whole file is refused and nothing is recorded (422)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(422, code, detail)


class CsvRow(NamedTuple):
    number: int  # the row's line number in the file; the header is line 1
    cells: tuple[str, ...]  # trimmed of surrounding spaces


class Refusal(NamedTuple):
    code: str
    detail: str


class _Accepted(NamedTuple):
    row: int
    product_id: str
    units_sold: int
    units_returned: int


def parse(data: bytes) -> list[CsvRow]:
    """Checks the file as a whole and returns its data rows. Blank lines are skipped."""
    if len(data) > MAX_BYTES:
        raise FileRefused("FILE_TOO_LARGE", f"The file is larger than {MAX_BYTES // 1_048_576} MiB")
    try:
        text = data.decode("utf-8-sig")  # a byte-order mark (Excel adds one) is allowed
    except UnicodeDecodeError:
        raise FileRefused("NOT_UTF8", "The file is not UTF-8 text") from None

    reader = csv.reader(io.StringIO(text, newline=""))
    records: list[tuple[int, list[str]]] = []
    last_line = 0
    for cells in reader:
        first_line = last_line + 1
        last_line = reader.line_num
        if cells:  # an empty list is a blank line
            records.append((first_line, cells))

    if not records:
        raise FileRefused("EMPTY_FILE", "The file has no rows")
    if records[0][1] != HEADER:
        raise FileRefused("BAD_HEADER", f"The first line must be exactly: {','.join(HEADER)}")
    rows = [CsvRow(number, tuple(cell.strip() for cell in cells)) for number, cells in records[1:]]
    if not rows:
        raise FileRefused("EMPTY_FILE", "The file has a header but no rows")
    if len(rows) > MAX_ROWS:
        raise FileRefused("TOO_MANY_ROWS", f"The file has more than {MAX_ROWS} rows")
    return rows


def dedupe(rows: list[CsvRow]) -> tuple[list[CsvRow], list[tuple[int, int]]]:
    """Last row wins per product and date (FR-026).

    Returns the rows to keep and the overridden pairs (row, overridden_by_row). A row with the
    wrong number of cells has no product or date, so it is never treated as a duplicate.
    """
    last: dict[tuple[str, str], int] = {}
    for row in rows:
        if len(row.cells) == len(HEADER):
            last[(row.cells[1], row.cells[0])] = row.number

    kept: list[CsvRow] = []
    overridden: list[tuple[int, int]] = []
    for row in rows:
        winner = last[(row.cells[1], row.cells[0])] if len(row.cells) == len(HEADER) else None
        if winner is None or winner == row.number:
            kept.append(row)
        else:
            overridden.append((row.number, winner))
    return kept, overridden


def validate(row: CsvRow, today: date, known_products: set[str]) -> Refusal | None:
    """The first rule a row breaks, or None. The order follows the contract table."""
    if len(row.cells) != len(HEADER):
        return Refusal("WRONG_COLUMN_COUNT", f"Expected 4 columns, found {len(row.cells)}")
    business_date, product_id, sold, returned = row.cells

    day: date | None = None
    if _DATE.fullmatch(business_date):
        try:
            day = date.fromisoformat(business_date)
        except ValueError:
            day = None
    if day is None:
        return Refusal("BAD_DATE_FORMAT", f"'{business_date}' is not a date in YYYY-MM-DD form")
    if day < today:
        return Refusal("DAY_CLOSED", f"{day} is closed; only today ({today}) can be uploaded")
    if day > today:
        return Refusal("FUTURE_DATE", f"{day} is in the future; only today ({today}) is accepted")

    if product_id not in known_products:
        return Refusal("UNKNOWN_PRODUCT", f"Product '{product_id}' does not exist")

    for name, value in (("units_sold", sold), ("units_returned", returned)):
        if not _UNITS.fullmatch(value) or int(value) > MAX_UNITS:
            return Refusal(
                "BAD_UNITS", f"{name} must be a whole number from 0 to {MAX_UNITS:,}, not '{value}'"
            )
    return None


def apply(
    session: Session, accepted: list[_Accepted], today: date
) -> tuple[list[_Accepted], list[RefusedRow]]:
    """Writes each row as today's total and moves stock by the change in net units.

    Stock rows are locked in product order. A row whose result would leave stock below 0 is refused
    and changes nothing. The caller owns the transaction.
    """
    done: list[_Accepted] = []
    refused: list[RefusedRow] = []
    for item in sorted(accepted, key=lambda each: each.product_id):
        on_hand = stock.lock_stock(session, item.product_id).on_hand
        existing = session.get(DailySales, (item.product_id, today))
        old_net = existing.units_sold - existing.units_returned if existing is not None else 0
        delta = (item.units_sold - item.units_returned) - old_net
        if on_hand - delta < 0:
            refused.append(
                RefusedRow(
                    row=item.row,
                    code="STOCK_BELOW_ZERO",
                    detail=(
                        f"{item.product_id} has {on_hand} in stock; this total needs "
                        f"{delta} more than today's current total"
                    ),
                )
            )
            continue

        if existing is None:
            existing = DailySales(
                product_id=item.product_id,
                business_date=today,
                units_sold=0,
                units_returned=0,
                day_status="open",
            )
            session.add(existing)
        existing.units_sold = item.units_sold  # replaces: these are absolute totals
        existing.units_returned = item.units_returned
        existing.updated_at = now_utc()
        session.flush()
        stock.apply_net_change(session, item.product_id, delta)
        done.append(item)
    return done, refused


def process_upload(session: Session, data: bytes) -> UploadResult:
    rows = parse(data)  # raises FileRefused: nothing has been touched yet
    kept, overridden = dedupe(rows)

    close_past_days(session)
    today = today_cairo()
    known = set(session.scalars(select(Product.product_id)))

    refused: list[RefusedRow] = []
    valid: list[_Accepted] = []
    for row in kept:
        problem = validate(row, today, known)
        if problem is not None:
            refused.append(RefusedRow(row=row.number, code=problem.code, detail=problem.detail))
        else:
            _, product_id, sold, returned = row.cells
            valid.append(_Accepted(row.number, product_id, int(sold), int(returned)))

    done, stock_refused = apply(session, valid, today)
    refused.extend(stock_refused)

    return UploadResult(
        business_date=today,
        accepted=[
            AcceptedRow(row=item.row, product_id=item.product_id)
            for item in sorted(done, key=lambda each: each.row)
        ],
        refused=sorted(refused, key=lambda each: each.row),
        overridden=[OverriddenRow(row=row, overridden_by_row=by) for row, by in overridden],
    )
