# Contract: the chat agent's tools and the grounding guard

Research R-03, R-04, R-08. The six tools are declared to Gemini as function declarations with
these parameter schemas. Their results are returned to the model as function responses and kept
as the turn's **facts**. Every derived number (totals, counts, filters) is computed here, in code
(D-18). Results never contain the service token or the Gemini key. All data is synthetic.

Common rules:

- `product_id` must match `^P[0-9]{3,}$`. An unknown product returns
  `{"error": "UNKNOWN_PRODUCT", "product_id": …}` and never a guessed product.
- Before the first end-of-day run, the Brain-data tools return `{"error": "NO_RESULTS"}`.
- A live ERP read that fails returns `{"error": "ERP_UNAVAILABLE"}`. The ERP being down is not
  "Assistant offline".
- Decimal values are rounded by code to what the screens show: days of cover to 2 decimals,
  forecasts and totals to 1 decimal, z to 1 decimal. The model is told to copy them as given.
- Every result carries `"synthetic": true`.

## Read tools (Brain data)

### `get_risk_list`

| Parameter | Type | Meaning |
|---|---|---|
| `risk` | `high` \| `medium` \| `low` \| `all`, default `all` | filter by level |
| `cover_below_days` | number 0–60, optional | keep rows with days of cover below this (for example 7 for "run out this week"), filtered in code |

The result is
`{computed_through, counts: {high, medium, low}, items: [{product_id, product_name, risk,
base_risk, raised_by_spike, days_of_cover, lead_time_days, available, open_po_qty, order_qty,
reason_code, supplier_id, supplier_name, latest_anomaly: {kind, business_date, z} | null}]}`.

- The rows are the newest result per product, the same rows as `GET /risk`.
- The order is the same as `GET /risk`: highest risk first.
- `counts` covers the whole list, before filtering.

### `get_forecast`

| Parameter | Type |
|---|---|
| `product_id` | string |
| `days` | integer 1–14, default 7 |

The result is
`{product_id, product_name, model, forecast_run_date, days: [{date, forecast, low, high}],
total: {forecast, low, high}, first_day, last_day}`.

- The rows come from the last end-of-day run, starting today (Cairo).
- `total` is the sum over the returned days.

### `get_sales_history`

**Without `product_id`** (added 2026-11-19): all products together over the last `days` closed days
(default 7). The result is `{scope: "all_products", first_day, last_day, days_counted,
products_counted, totals: {units_sold, units_returned, net_units}, top_products: [{product_id,
product_name, units_sold, units_returned, net_units}]}`, with the top 5 by net units
(`sales_top_products`). The rest of this section describes the one-product form
(`scope: "product"`).

| Parameter | Type |
|---|---|
| `product_id` | string |
| `days` | integer 1–90, optional: the last N days ending at the newest day held |
| `from`, `to` | dates, optional, instead of `days` |

The result is
`{product_id, product_name, first_day, last_day, days: [{date, units_sold, units_returned,
net_units, day_status}], totals: {units_sold, units_returned, net_units}, days_counted}`.

- Values come from the Brain's copy (`sales_daily`).
- The default is the last 7 days.
- Today's open day is included and marked `open`.

## Read tools (live from the ERP, Canonical API)

### `get_stock`

The parameter is `product_id`.

The result is `{product_id, product_name, on_hand, available, read_at}`, from
`GET /api/v1/canonical/inventory/{product_id}`.

### `get_open_purchase_orders`

The parameter is `product_id`.

The result is
`{product_id, product_name, orders: [{purchase_order_id, supplier_id, status, open_qty}],
total_open_qty, read_at}`, from `GET /api/v1/canonical/purchase-orders?status=open&product_id=…`.
It reads all pages, as feature 003's client does.

The Canonical client gains `open_purchase_order_list(product_id)` on the same GET path. No new
path is called, and the scope test's path list stays the same.

## The write tool

### `propose_purchase_order`

| Parameter | Type | Meaning |
|---|---|---|
| `product_ids` | array of 1–10 product IDs | the products to order, all from one preferred supplier |
| `quantity` | integer ≥ 1, optional, only with one product | the quantity the manager asked for |

There is no supplier parameter: the supplier is always the products' preferred supplier from
`product_ref` (README 4.4).

The rules, in order:

| # | Check | Refusal `code` |
|---|---|---|
| 1 | each product is in `product_ref` | `UNKNOWN_PRODUCT` |
| 2 | each product has a newest recommendation | `NO_RESULTS` |
| 3 | all products have the same preferred supplier | `DIFFERENT_SUPPLIERS` |
| 4 | without `quantity`, each line uses the newest `order_qty`, which must be ≥ 1 with no reason code | `NO_RECOMMENDED_QUANTITY` (detail in words: "open orders couldn't be read…") |
| 5 | with `quantity`, the value must appear in the newest manager message, or equal the recommendation's `order_qty` | `QUANTITY_NOT_GIVEN` |
| 0 | no `product_ids` (a follow-up that gives only a quantity), or one unknown product while the newest message names none: the product the manager named most recently in the conversation is used (added 2026-11-19) | `VALIDATION_ERROR` ("which product?") when the conversation names none |
| 6 | at most one proposal created per turn | `VALIDATION_ERROR` |
| 7 | `create_proposal(session, supplier_id, lines, origin="assistant")` (feature 004 contract) | `PROPOSAL_PENDING` (with `live_proposal_id` and `path`) or `VALIDATION_ERROR` |

The result is
`{proposal_id, path: "/brain/proposals/{id}", status: "awaiting_approval", supplier_id,
supplier_name, lines: [{product_id, product_name, quantity}]}` or
`{refused: code, detail, live_proposal_id?, path?}`.

The tool never approves, rejects or sends anything, and never calls the ERP.

## The grounding guard (`brain.assistant.grounding`)

```python
allowed = Allowed.from_facts(facts, extra_texts=[*manager_messages, catalog_block])
result = check(text, allowed)       # Grounded(ok: bool, unsupported: list[str])
```

**Allowed values** are collected from the facts:

- every number, by value;
- numbers inside strings, for example the 500 in "Amoxicillin 500 mg";
- ISO dates;
- `P…` and `S…` IDs.

**The text is normalized**:

- ٠–٩ and ۰–۹ become 0–9;
- ٫ becomes ".";
- ٬ is removed, and so is "," between groups of three digits;
- ٪ becomes "%".

**Each token must be allowed**:

- every ISO date;
- every ID;
- every number, compared by value, so 2.83 equals 2.830;
- every number word from two to twenty, in English and Arabic.

| Example text | Facts contain | Result |
|---|---|---|
| "P003 has 2.83 days of cover vs a 7-day lead time; order 108" | 2.83, 7, 108, P003 | ok |
| «لدى P003 تغطية ٢٫٨٣ يوم مقابل مهلة توريد ٧ أيام؛ اطلب ١٠٨» | same | ok (digits normalized) |
| "about 2.8 days" | 2.83 | unsupported: 2.8 |
| "three products are high" | counts.high = 3 | ok |
| "three products are high" | no 3 anywhere | unsupported: three |
| "P999 has no stock" | no P999 | unsupported: P999 |
| "sold 1,234 units" | 1234 | ok |
| "on 2026-11-20" | dates up to 2026-11-17 | unsupported: 2026-11-20 |

## Data cards (added 2026-11-19)

The guard checks values, not labels. So when a turn used `get_sales_history`, `get_risk_list` or
`get_forecast`, the chat reply also returns `cards`: tables built by code from those results
(`brain.assistant.cards.build_cards`, at most four).

| Tool result | Columns |
|---|---|
| sales, all products | Product, Sold, Returned, Net (top products; total row "All products") |
| sales, one product | Date, Sold, Returned, Net (total row) |
| risk list | Product, Risk, Days of cover, Lead time, Order (a reason in words when there's no order) |
| forecast | Date, Forecast, Low, High (total row) |

Results with an `error` give no card.
