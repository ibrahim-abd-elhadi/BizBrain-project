# Contract: Why? explanation facts and templates (English and Arabic)

Research R-09, FR-013–FR-014a. The template is the **plain version**: it is built each time from
the row's facts and never stored. It is also what the model is asked to rephrase. Both languages
use ASCII digits, like the product IDs; the guard accepts Arabic-Indic digits too (R-04).

## Facts (built by code from one `risk_result`)

| Fact | Source |
|---|---|
| `product_id`, `product_name` | `risk_result`, `product_ref` |
| `supplier_id`, `supplier_name` | `product_ref` |
| `days_of_cover` (2 decimals, or null for no forecast demand) | `risk_result` |
| `lead_time_days` (or null) | `risk_result` |
| `medium_margin_days` = 2 | README 4.3, the medium threshold |
| `lead_plus_2` = lead_time_days + 2 | code |
| `base_risk`, `risk`, `raised_by_spike` | `risk_result` |
| `spike_date`, `spike_z` (1 decimal) | the spike that raised it: the newest `anomaly` row with the same `product_id`, `kind = 'spike'`, `raised_risk = true` and `found_at <= risk_result.computed_at` (newest `found_at`, then `business_date`); its `business_date` and `z`. None found: the spike sentence is left out |
| `cover_days_counted` = lead_time_days + review_period_days | code |
| `forecast_over_lead` (1 decimal, trailing .0 dropped), `safety_stock`, `target`, `available`, `open_po_qty`, `raw`, `pack_multiple`, `max_order_qty`, `order_qty`, `reason_code` | `risk_result` |

Words for the risk level:

| Level | English | Arabic |
|---|---|---|
| `high` | high | مرتفع |
| `medium` | medium | متوسط |
| `low` | low | منخفض |

## Sentences, chosen by rule (1 + 2 + optional spike + 3)

### 1. Cover

| Case | English | Arabic |
|---|---|---|
| cover and lead time known | {product_name} ({product_id}) has {days_of_cover} days of cover against a {lead_time_days}-day lead time from {supplier_name} ({supplier_id}). | يغطي مخزون {product_name} ({product_id}) مدة {days_of_cover} يوم، ومهلة التوريد من {supplier_name} ({supplier_id}) هي {lead_time_days} يوم. |
| no forecast demand (`days_of_cover` null) | {product_name} ({product_id}) has no forecast demand, so its stock isn't expected to run out. | لا يوجد طلب متوقع على {product_name} ({product_id})، لذلك لا يُتوقع نفاد مخزونه. |
| lead time unknown | {product_name} ({product_id}) has {days_of_cover} days of cover, but its supplier's lead time couldn't be read, so no risk level is set. | يغطي مخزون {product_name} ({product_id}) مدة {days_of_cover} يوم، لكن تعذّرت قراءة مهلة توريد المورد، لذلك لم يُحدَّد مستوى الخطر. |

### 2. Risk (only when a level is set)

| `base_risk` | English | Arabic |
|---|---|---|
| high | That is less than the lead time, so the risk is high. | وهذا أقل من مهلة التوريد، لذا فالخطر مرتفع. |
| medium | That is at least the lead time but less than the lead time plus {medium_margin_days} days ({lead_plus_2}), so the risk is medium. | وهذا لا يقل عن مهلة التوريد لكنه أقل من مهلة التوريد زائد {medium_margin_days} يوم ({lead_plus_2})، لذا فالخطر متوسط. |
| low | That is at least the lead time plus {medium_margin_days} days ({lead_plus_2}), so the risk is low. | وهذا لا يقل عن مهلة التوريد زائد {medium_margin_days} يوم ({lead_plus_2})، لذا فالخطر منخفض. |
| low, no forecast demand | So the risk is low. | لذا فالخطر منخفض. |

**Spike** (only when `raised_by_spike`):

- English: "A demand spike on {spike_date} (z = {spike_z}) raised the risk one level, from
  {base_risk} to {risk}."
- Arabic: «وقد رفعت قفزة في الطلب يوم {spike_date} (z = {spike_z}) مستوى الخطر درجة واحدة، من
  {base_risk} إلى {risk}.»

### 3. Order

| Case | English | Arabic |
|---|---|---|
| `reason_code` = `NO_SUPPLIER` | The supplier's details couldn't be read from the ERP, so there is no order quantity (NO_SUPPLIER). | تعذّرت قراءة بيانات المورد من نظام ERP، لذلك لا توجد كمية طلب مقترحة (NO_SUPPLIER). |
| `reason_code` = `OPEN_PO_UNAVAILABLE` | Open purchase orders couldn't be read from the ERP, so there is no order quantity (OPEN_PO_UNAVAILABLE). | تعذّرت قراءة أوامر الشراء المفتوحة من نظام ERP، لذلك لا توجد كمية طلب مقترحة (OPEN_PO_UNAVAILABLE). |
| `raw` ≤ 0 | Forecast demand over the next {cover_days_counted} days is {forecast_over_lead} units; with {safety_stock} units of safety stock, the target is {target}. With {available} available and {open_po_qty} on order, nothing more is needed, so no order is recommended. | الطلب المتوقع خلال {cover_days_counted} يوم القادمة هو {forecast_over_lead} وحدة، ومع مخزون أمان قدره {safety_stock} وحدة يصبح الهدف {target}. ومع {available} متاحة و{open_po_qty} قيد الطلب لا حاجة إلى المزيد، لذلك لا يُقترح طلب. |
| `raw` > 0 (lead-in) | Forecast demand over the next {cover_days_counted} days is {forecast_over_lead} units; with {safety_stock} units of safety stock, the target is {target}. Minus {available} available and {open_po_qty} on order leaves {raw}. | الطلب المتوقع خلال {cover_days_counted} يوم القادمة هو {forecast_over_lead} وحدة، ومع مخزون أمان قدره {safety_stock} وحدة يصبح الهدف {target}. وبعد خصم {available} متاحة و{open_po_qty} قيد الطلب يتبقى {raw}. |
| … then, `pack_multiple` = 1, not capped | The order is {order_qty}. | تكون كمية الطلب {order_qty}. |
| … then, `pack_multiple` > 1, not capped | Rounded up to packs of {pack_multiple}, the order is {order_qty}. | وبالتقريب لأعلى إلى عبوات من {pack_multiple} تكون كمية الطلب {order_qty}. |
| … then, capped at `max_order_qty` | Rounded up to packs of {pack_multiple} and capped at the maximum order of {max_order_qty}, the order is {order_qty}. | وبالتقريب لأعلى إلى عبوات من {pack_multiple} مع الحد الأقصى للطلب {max_order_qty} تكون كمية الطلب {order_qty}. |

## Worked example: P003 on freshly seeded data (feature 003 quickstart)

The row is 2.83 days of cover, a 7-day lead time from S004 (Delta Health Trading), `high`, forecast
145 over 7 days, safety stock 23, target 168, 60 available, 0 on order, raw 108, packs of 12, and
an order of 108.

> Amoxicillin 500 mg capsules (P003) has 2.83 days of cover against a 7-day lead time from Delta
> Health Trading (S004). That is less than the lead time, so the risk is high. Forecast demand
> over the next 7 days is 145 units; with 23 units of safety stock, the target is 168. Minus 60
> available and 0 on order leaves 108. Rounded up to packs of 12, the order is 108.

> يغطي مخزون Amoxicillin 500 mg capsules (P003) مدة 2.83 يوم، ومهلة التوريد من Delta Health
> Trading (S004) هي 7 يوم. وهذا أقل من مهلة التوريد، لذا فالخطر مرتفع. الطلب المتوقع خلال 7 يوم
> القادمة هو 145 وحدة، ومع مخزون أمان قدره 23 وحدة يصبح الهدف 168. وبعد خصم 60 متاحة و0 قيد
> الطلب يتبقى 108. وبالتقريب لأعلى إلى عبوات من 12 تكون كمية الطلب 108.

## Checks (tests)

- Every branch renders in both languages.
- Every rendered template passes the guard against its own facts.
- The worked example matches word for word.

## Model rephrasing

- The model gets the facts as JSON and the template in the requested language. The instruction:
  "Rephrase this explanation in plain words for a pharmacy manager, in {English|Arabic}. Keep
  every number, date and ID exactly as given; add no number; keep it under 80 words."
- The result is kept only if it passes the guard and is in the right language (R-04, R-07).
- Product and supplier names stay as stored (in English); they are data.
