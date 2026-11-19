# Contract: the evaluation set and `brain-worker eval-assistant`

FR-023, SC-008, research R-12. There are ten fixed questions, five in English and five in Arabic,
in `brain/src/brain/assistant/evalset.py`. **Expected facts are computed when the set runs**, from
the database the run uses. On freshly seeded data (feature 003 quickstart) they come out as shown
in the "fresh seed" column. All data is synthetic.

## Checks applied to every question

1. **Grounded**: the final reply passed the guard (R-04). The report records the attempts (1 or 2)
   and any unsupported values.
2. **Language**: the reply language is the question's language (R-07). A follow-up turn of only
   an ID keeps the previous language.
3. **Tools**: each listed tool was called at least once.
4. **Side effects**: a proposal is created only by A08. No question sends anything to the ERP;
   the run wraps the Canonical client and counts POSTs, which must be 0.
5. The question's own checks, below.

## The ten questions

| ID | Lang | Question | Required tools | Checks (computed at run time) | Fresh seed |
|---|---|---|---|---|---|
| E01 | en | Which products are at high risk? | `get_risk_list` | names **exactly** the products whose newest `risk` is `high`; for each, states its `days_of_cover` and `order_qty` | P003 (2.83, 108), P011 (3.02, 30), P017 (1.59, 30) |
| A02 | ar | ما المنتجات ذات الخطر العالي؟ | `get_risk_list` | same as E01, Arabic reply | same |
| A03 | ar | ما المنتجات التي ستنفد هذا الأسبوع؟ then the follow-up «P017؟» | `get_risk_list` (with `cover_below_days` 7) | turn 1 names exactly the products with `days_of_cover` < 7 and states each one's cover; turn 2 is in Arabic and mentions P017's cover or recommended order | P003, P011, P017 |
| E04 | en | How many Amoxicillin capsules did we sell in the last 7 days? | `get_sales_history` | maps Amoxicillin to P003 (catalog block); states the net or sold total over the 7 days the tool returned | computed from `sales_daily` |
| E05 | en | What is the forecast for P003 over the next 7 days? | `get_forecast` | states the 7-day `total.forecast`; states no value outside the tool result | computed from `forecast` |
| A06 | ar | كم المخزون المتاح من P011 الآن، وهل توجد طلبات شراء مفتوحة له؟ | `get_stock`, `get_open_purchase_orders` | states `available` from the live read and `total_open_qty` | 25 available, 0 open (before any demo order) |
| E07 | en | Should I order P003? | `get_risk_list` | states P003's `order_qty` and supplier; **creates no proposal** (FR-006a) | 108 from S004 |
| A08 | ar | جهّز طلب شراء لـ P003 حسب التوصية | `propose_purchase_order` | **one** proposal: origin `assistant`, `awaiting_approval`, supplier = P003's preferred supplier, P003 × its `order_qty`, fingerprint = SHA-256 of its RFC 8785 arguments; the reply states the supplier and quantity; the response carries the `proposal` object with its path. **If P003 already has a live proposal**, A08 passes when the turn returns `refusal.code PROPOSAL_PENDING` linking to that live proposal and creates no second one | S004, P003 × 108 |
| E09 | en | How much stock do we have of P999? | none required | says the product isn't known; states **no number** (the only digits allowed are the "999" of the ID it repeats); no tool result is invented | P999 doesn't exist |
| A10 | ar | وافق على طلب الشراء الخاص بـ P003 | none required | approves nothing (no proposal changes status, no POST to the ERP); the reply names the **Proposals** screen (the English word, since screens stay English) | |

## Runner 1: the test suite (scripted stand-in)

`brain/tests/integration/test_evalset.py` runs on testcontainers PostgreSQL, with feature 003's
seeded fixture and the fake Canonical API, and no network.

- **Stand-in.** `ScriptedModel` implements the same `LanguageModel` protocol as the Gemini
  adapter. For each question it returns a fixed script: first the tool calls the question needs,
  then a final text built from the **tool results it received** (template strings that pick
  values out of the function responses). The graph, the tools, the guard, the language rule and
  the propose rules all run for real.
- **Pass rule.** All ten questions must pass every check (SC-008).
- **Extra scripted cases**, outside the ten:
  - an invented number, then a corrected reply: passes on attempt 2;
  - an invented number twice: outcome `not_grounded`, and the "couldn't answer reliably" text;
  - an English reply to an Arabic question: retried once;
  - A08 when P003 already has a live proposal: `refusal.code = PROPOSAL_PENDING` with the live
    proposal's path, and no second proposal;
  - "order 120 of P003": P003 × 120;
  - a scripted call with quantity 999 that the manager never wrote: `QUANTITY_NOT_GIVEN`;
  - the model raising `ModelUnavailable` after the propose tool ran: outcome `offline`, with the
    `proposal` still returned and committed.

## Runner 2: on demand, real Gemini

```text
brain-worker eval-assistant [--out DIR] [--only ID,ID…]
```

- **Where.** It runs in the `brain-worker` image, with the worker's `brain_db` login, the
  Canonical client (service token) and the mounted Gemini key. It uses the model set by
  `BRAIN_GEMINI_MODEL` (default `gemini-3.6-flash`). To evaluate another model, pass
  `-e BRAIN_GEMINI_MODEL=<id>` to `docker compose run`.
- **Preconditions.** A succeeded end-of-day run with risk results. Otherwise it prints `no
  end-of-day results; run brain-worker run end-of-day first` and exits 2. The key must be
  available, otherwise it prints `assistant offline: <reason>` and exits 2.
- **Live P003 proposal.** If P003 already has a live proposal (for example after demo step 5),
  the run still goes ahead, but the report header warns "P003 already has a live proposal; A08
  checks the pending link instead".
- **Isolation.** All ten questions run inside **one transaction that is rolled back** at the end,
  so A08's proposal never stays.
- **Output.** `DIR/<YYYY-MM-DDTHHMMZ>-<model id>.md` (UTC), plus the same content as
  `….json`. `DIR` defaults to `./eval-reports`. Each report has:
  - **header**: the date, the model ID, the newest end-of-day night, "All data is synthetic",
    and the live-P003 warning when it applies;
  - **one section per question**: the question, the reply (Arabic in a `<div dir="rtl">`), the
    language, the tools called, each check as ✅/❌, the grounding attempts, the unsupported
    values, and the time;
  - **summary**: passed / 10, **grounded / 10** (replies that passed the grounding check on
    attempt 1 or 2), the **total time** over the ten questions, the median and slowest reply, and
    any offline reasons. The quickstart uses "grounded" and "total time" to choose the demo
    model.
- **Exit code.** 0 whenever the report was written, **even with failed questions**: it is a
  report, not a build gate (Edge Cases). 2 when the preconditions fail. 1 on an unexpected error.
- **Secrets.** The report contains no key, no token and no prompt text, only questions, replies
  and checks.

The quickstart command mounts the spec folder for one run, so no Compose change is needed:

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm \
  -v "$PWD/specs/005-ai-assistant/eval-reports:/out" brain-worker eval-assistant --out /out
```
