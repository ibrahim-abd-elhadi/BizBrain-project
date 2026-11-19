# Contract: Upload CSV file format

Used by `POST /api/v1/erp/sales/upload` ([erp-api.openapi.yaml](erp-api.openapi.yaml)).
Sources: FR-013, FR-014, FR-026, research R-18 and R-20.

## File

| Property | Rule | Refusal `code` (whole file) |
|---|---|---|
| Encoding | UTF-8; a leading byte-order mark is allowed | `NOT_UTF8` |
| Size | ≤ 1 MiB | `FILE_TOO_LARGE` |
| Rows | ≥ 1 and ≤ 5,000 data rows after the header | `EMPTY_FILE` / `TOO_MANY_ROWS` |
| Header (line 1) | Exactly `business_date,product_id,units_sold,units_returned`, in that order and case | `BAD_HEADER` |
| Delimiter | Comma; standard CSV quoting | — |

If the file itself is refused, nothing is recorded.

## Rows

Each data row is one product's total **for today** in Africa/Cairo. Values are trimmed of
surrounding spaces. A row's number is its line number in the file; the header is line 1.

| Column | Rule | Refusal `code` (row) |
|---|---|---|
| (any) | Exactly 4 cells | `WRONG_COLUMN_COUNT` |
| `business_date` | `YYYY-MM-DD` and a real date | `BAD_DATE_FORMAT` |
| `business_date` | Not before today (every earlier day is `closed`) | `DAY_CLOSED` |
| `business_date` | Not after today | `FUTURE_DATE` |
| `product_id` | An existing product, for example `P007` | `UNKNOWN_PRODUCT` |
| `units_sold`, `units_returned` | Whole numbers ≥ 0, with no decimals or signs | `BAD_UNITS` |
| (applying it) | The stock that results stays ≥ 0 | `STOCK_BELOW_ZERO` |

## Processing order

1. **Duplicates:** for each product and date, only the **last** row is kept. Each earlier row is
   reported in `overridden`, together with the row that overrode it.
2. **Validation:** each kept row is checked against the rules above. Failing rows go in `refused`.
   An overridden row is never applied, even when the row that overrode it is refused.
3. **Apply:** all accepted rows are applied in one transaction. Each one **replaces** that
   product's total for today, and its stock moves by `−(new net − old net)`.

## Example

```csv
business_date,product_id,units_sold,units_returned
2026-11-18,P001,15,1
2026-11-18,P002,7,0
2026-11-17,P003,4,0
2026-11-18,P999,3,0
2026-11-18,P002,9,1
```

If today is 2026-11-18 in Cairo:

- **Accepted:** row 2 (P001), and row 6 (P002: 9 sold, 1 returned).
- **Overridden:** row 3, by row 6.
- **Refused:** row 4 (`DAY_CLOSED`) and row 5 (`UNKNOWN_PRODUCT`).
