# BizBrain: an AI Brain for a Pharmacy ERP (DEPI graduation project)

BizBrain is a small pharmacy ERP plus a separate AI "Brain". The Brain forecasts demand, flags stock-out risk, recommends purchase orders, writes a morning briefing, and lets the pharmacy manager chat with an agent that can propose purchase orders. Nothing is written to the ERP until the manager approves it.

This is the lighter DEPI version of the Business Brain project. The SaaS platform is cut. These stay:

- the ERP
- the Brain, as a separate service
- the integration layer between them
- all three AI parts: agentic, generative and forecasting

- **Team:** one developer
- **Deadline:** 2 December 2026
- **Data:** synthetic only, and every result is labeled synthetic

> Decision IDs such as `D-21` refer to `docs/BLUEPRINT_FINAL.md` in the main Business Brain project. That file isn't in this repo. This README only uses the decisions that carry over to the DEPI version.

---

## 1. Architecture

```
                  +-----------------------------+
   React app ---->|  ERP  (Python / FastAPI)    |----> erp_db
       |          |  6 modules + Canonical API  |
       |          +--------------^--------------+
       |                         |  GET: poll sales, read product / stock / supplier / open POs
       |                         |  POST: draft purchase order (only after approval)
       |          +--------------+--------------+
       +--------->|  Brain (Python / FastAPI)   |----> brain_db
                  |  brain-api + brain-worker   |
                  +--------------+--------------+
                                 |
                                 +----> Google Gemini (hosted LLM)
```

### Boundary rules

1. The ERP is the system of record.
2. The Brain never connects to `erp_db`, and the ERP never reads `brain_db`.
3. The Brain reads ERP data only through the Canonical API (section 3).
4. The Brain makes one kind of business write: a **draft** purchase order, sent only after the pharmacy manager approves it.

### Services (Docker Compose, one machine)

| Service | What it is |
|---|---|
| `erp-backend` | ERP modules and the Canonical API (Python / FastAPI) |
| `brain-api` | Brain read APIs, chat agent, proposals, approval and execution (Python / FastAPI) |
| `brain-worker` | The same Brain code with a different entry point. It runs the scheduled jobs in section 4.1 and the manual `brain-worker run <job>` command |
| `postgres` | One PostgreSQL container holding two separate databases, `erp_db` and `brain_db`. Each database has its own login: the ERP's login can reach only `erp_db`, and the Brain's login only `brain_db` |
| `frontend` | One React app with both the ERP screens and the Brain screens |

---

## 2. ERP

### 2.1 Modules

| Module | Scope in this version |
|---|---|
| Products | Product catalog, including the fields the Brain needs: preferred supplier, pack multiple and maximum order quantity |
| Suppliers | Supplier records, including lead time |
| Inventory | Stock for **one location** |
| Sales | Seeded historical sales, a **Simulate Sales** trigger and an **Upload CSV** trigger. There is no full POS sales screen |
| Purchase orders | Draft → confirmed. The Brain creates drafts after approval, and the manager confirms them in the ERP |
| Users and login | A simple login with **one role: pharmacy manager** |

The ERP computes each sale's `business_date` in the `Africa/Cairo` time zone (D-04).

### 2.2 Sales input

- **Seeded history:** a synthetic pharmacy dataset (D-41) seeded into `erp_db`. It covers **90 days** of daily sales, with demand spikes and anomalies planted for the demo.
- **Simulate Sales:** adds a batch of realistic sales for today across products. It can also add a demand spike for one chosen product.
- **Upload CSV:** each row is **one product's daily total**: date, product, units sold, units returned. The exact column names are set in the spec.

All three paths write to `erp_db`. The Brain sees them only by polling the Canonical API.

---

## 3. Integration layer: the Canonical API

This works as in the main plan, minus tenants and branches. The main plan's `contracts/` are reused, with the multi-tenant and multi-branch parts removed. Product and supplier IDs are readable strings (for example `P001`, `S001`) instead of UUIDs.

| Endpoint | Used for |
|---|---|
| `GET /api/v1/canonical/sales` | Daily sales totals. Parameters: `from`, `to`, `updated_since`, `cursor`, `limit` |
| `GET /api/v1/canonical/products/{product_id}` | Preferred supplier, pack multiple, maximum order quantity |
| `GET /api/v1/canonical/inventory/{product_id}` | Available stock at the single location |
| `GET /api/v1/canonical/suppliers/{supplier_id}` | Supplier lead time |
| `GET /api/v1/canonical/purchase-orders` | Open purchase orders for a product, read live when a recommendation is made (D-07) |
| `POST /api/v1/canonical/purchase-orders` | Creates a **draft** purchase order. It requires an `Idempotency-Key` header set to the proposal UUID. The same key with the same body returns the original response, and the same key with a different body returns `409 IDEMPOTENCY_CONFLICT` |

### 3.1 Sales rows

Each sales row is one `(product_id, business_date)` total with these fields:

- `units_sold`
- `units_returned`
- `net_units`
- `day_status` (`open` or `closed`)
- `updated_at`

A day with `day_status = closed` is final.

Each page also carries the server's `high_watermark` (D-05).

### 3.2 Polling (D-24, D-25)

- **Interval:** the Brain polls `GET /canonical/sales` every 300 seconds.
- **Watermark:** each poll asks for rows updated since `high_watermark − 120 s`. The overlap covers normal commit delays.
- **Upsert:** rows are upserted by `(product_id, business_date)` as absolute totals, so reading a row twice is harmless.
- **Ordering:** a row with an older `updated_at` never overwrites a newer one.
- **Saving the watermark:** it's saved only after the last page, so a poll that crashes halfway just re-reads the same rows next time.
- **Credentials:** the Brain calls the ERP with a service credential, as in the main plan.

---

## 4. Brain

### 4.1 Jobs and cadence (Africa/Cairo time)

| Job | When | What it does |
|---|---|---|
| Sales poll | Every 5 minutes | Section 3.2 |
| Hourly intelligence window | Every 60 minutes | For products whose sales changed since the last window: update features, run the spike check, read fresh stock and open POs, then set risk and the recommendation. It uses **last night's** forecast |
| End-of-day run | Nightly, 02:00 | Rebuild features, **train**, forecast 14 days, score every product (spike and drop checks), run the post-deployment evaluation |
| Manual run | On demand | `brain-worker run <job>` runs any job now, for development and the demo. There is no UI button for jobs (D-38) |

Training happens only in the end-of-day run and only on closed days, never on the day that's still open (D-26, D-28).

### 4.2 Forecasting (D-20, D-31, D-32, D-35)

- **Target:** `y_units = max(net_units, 0)` on closed days. This is recorded sales, not true demand.
- **Models:** a seasonal-naive baseline plus **one global LightGBM model** across all products.
- **Model selection:** for each product, whichever model has the lower backtest WAPE wins. New products use seasonal-naive.
- **Output:** a 14-day forecast per product with a low/high range.
- **Post-deployment evaluation:** each night, yesterday's forecast is compared with actual sales. A model that gets much worse is marked degraded and replaced the next night.

### 4.3 Anomalies and risk (D-22, D-40)

- **Anomaly detection:** z-score rules on daily net units. During the day only spikes are checked. Drops are checked only on closed days.
- **Risk levels:**
  - `high` if days of cover < lead time
  - `medium` if days of cover < lead time + 2
  - `low` otherwise
- **Anomaly bump:** a high anomaly raises the risk one level.

### 4.4 Order recommendation (D-07, D-21)

```
target = ceil(forecast over (lead_time + review_period) + safety_stock)
raw    = target − available − open_po_qty
order  = raw rounded up to pack_multiple, capped at max_order_qty
```

- Only the product's preferred supplier is used.
- If supplier data is missing, there's no order recommendation, and the reason code is `NO_SUPPLIER`.
- If open-PO data is missing, there's no order recommendation, and the reason code is `OPEN_PO_UNAVAILABLE`.

### 4.5 Proposals and approval (D-09, D-13, D-18)

1. A `create_purchase_order` proposal is built **deterministically** from a recommendation. This path works without the LLM. The agent's `propose_purchase_order` tool produces the same proposal shape.
2. A proposal is immutable. Its fingerprint, `arguments_sha256`, is a SHA-256 hash of the arguments as RFC 8785 canonical JSON.
3. The pharmacy manager approves the proposal in the browser. Before executing, the Brain checks that the fingerprint the manager saw matches the stored one.
4. The Brain sends the draft PO to the ERP with `Idempotency-Key` set to the proposal UUID. A retry can never create a second order.
5. The ERP creates a **draft** PO, and the manager confirms it in the ERP.

### 4.6 Agentic and generative AI (LangGraph + Google Gemini)

| Feature | What it does |
|---|---|
| Chat agent (LangGraph) | Has read tools for sales history, forecasts, stock, the risk list and open POs. Its one write tool, `propose_purchase_order`, only creates a proposal, which then goes through the approval flow in 4.5. Works in **English and Arabic** |
| Morning briefing | Generated after the nightly run from that night's forecasts, risks, anomalies and recommendations. Written in **English and Arabic** |
| "Why" explanations | Explains a risk level or a recommendation in plain words. Example: "1.7 days of cover vs a 5-day lead time, so order 110" |

- **Grounding rule (D-18):** every number comes from Brain code or ERP data, never from the LLM. The LLM may only phrase numbers that code has already computed.
- **Offline mode (D-17):** if Gemini can't be reached, the chat shows "Assistant offline" and explanations fall back to templates. Forecasting, risk, recommendations and rule-built proposals keep working. The morning briefing isn't available while Gemini is unreachable; its place shows "Assistant offline".
- **LLM:** Google Gemini. The model ID is configurable (for example `gemini-2.5-flash`).

### 4.7 Default parameters

From the main plan. Configurable, not hardcoded.

| Area | Parameter | Value |
|---|---|---|
| Anomaly | z-score threshold | 4 |
| Anomaly | Minimum history before anomaly checks | 28 days |
| Order | `review_period` | 0 days |
| Order | `safety_stock` | ceil(1.65 × daily std dev × √lead_time); if std dev is unavailable, 1 day of mean demand |
| Order | `pack_multiple` when unknown | 1 |
| Order | Order quantity when raw ≤ 0 | 0 (no order) |
| Forecast | Horizon | 14 days |
| Forecast | Backtest window | 4 weeks |
| Forecast | Minimum history before LightGBM is considered | 8 weeks (otherwise seasonal-naive) |
| Forecast | LightGBM must beat seasonal-naive backtest WAPE by | 0.05 |
| Forecast | Low/high range | Quantile, 80% coverage |
| Forecast | Degradation factor (live WAPE vs backtest WAPE) | 1.5 |

---

## 5. Frontend (React)

One app with these screens:

- **ERP:** products, suppliers, inventory, sales (Simulate Sales and Upload CSV), purchase orders, login.
- **Brain:** risk list and insights, forecasts, morning briefing, chat agent, proposal approval.

---

## 6. Tech stack (decided)

| Part | Choice |
|---|---|
| ERP backend | Python, FastAPI |
| Brain backend | Python, FastAPI (`brain-api`, `brain-worker`) |
| Databases | PostgreSQL: one container, two databases (`erp_db`, `brain_db`) |
| Forecasting | Seasonal-naive baseline, LightGBM |
| Agent | LangGraph |
| LLM | Google Gemini (configurable model ID) |
| Frontend | React |
| Running it | Docker Compose on one machine |

---

## 7. Out of scope for this version

These are cut from the main plan:

- **The SaaS platform and multi-tenancy:**
  - no `tenant_id`
  - no tenant registry
  - no per-tenant credentials
  - no row-level security
  - no cross-tenant isolation tests
  - no tenant provisioning
- **Multi-branch and organization-level inventory (D-49):** there is one location.
- **Multiple user roles:** there is one pharmacy manager role.
- **A full POS sales screen.**
- **The nightly 7-day reconcile and complete/gap day tracking.**
- **Proposal expiry:** the 24-hour TTL is gone.
- **Audit log and LLM usage log.**
- **Pipeline status endpoint and the stale-data banner.**
- **Supplier message drafts.**
- **RAG.**
- **Redis, ERP events and the event consumer** (already out of the main MVP, D-23).

---

## 8. Still to decide in the spec and plan (Spec Kit)

None of these were decided while scoping:

- When the ERP marks a business day `closed`.
- The exact CSV column names, and how many products the synthetic dataset has.
- The login token mechanism, how `brain-api` verifies a signed-in manager, and the format of the Brain's service credential for the ERP.
- The LightGBM feature set for 90 days of history.
- When an anomaly counts as "high" (severity tiers).
- The `brain_db` and `erp_db` table lists.
- Library choices beyond section 6: ORM and migrations, job scheduler, Gemini client library, React tooling.
- Main-plan rules this scoping didn't cover:
  - at most one live proposal per recommendation (D-30)
  - a fresh approval round after a failed execution (D-43)
  - separate least-privilege roles for `brain-api` and `brain-worker` inside `brain_db` (D-45)

## 9. Known limits

- **Possible stale totals:** without the nightly reconcile, a sales total the timestamp watermark misses stays stale until that row changes again (main plan, section 4.6).
- **Hidden demand:** forecasts learn recorded sales, so stock-outs hide real demand (D-35).
- **No yearly seasonality:** 90 days of history can't capture it.
- **Synthetic results:** every result comes from synthetic data.
