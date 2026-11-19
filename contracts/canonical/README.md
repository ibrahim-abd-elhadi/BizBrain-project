# Canonical API contracts (DEPI)

Adapted from the main Business Brain plan's `contracts/` (`openapi/canonical.openapi.yaml`,
`schemas/canonical/*`, `schemas/common/*`, `fixtures/*/canonical/*`), as README Section 3 requires.
The layout mirrors the main plan, so a file here has the same path as its source.

| Path | What it is |
|---|---|
| `openapi/canonical.openapi.yaml` | The six operations of README Section 3 |
| `schemas/canonical/*.schema.json` | One JSON Schema (draft 2020-12) per document |
| `schemas/common/defs.schema.json`, `error.schema.json` | Shared definitions and the error envelope |
| `fixtures/valid/…` | Documents that must pass their schema |
| `fixtures/invalid/…` | Documents that must fail it, one reason each |

Each fixture is `{"$schema_ref": "<schema path>", "document": {…}}`, as in the main plan. The
contract tests (research R-15) check every fixture and every live response against these schemas.

## Changes from the main plan

**Removed (multi-tenant and multi-branch, constitution Principle I):**

- `tenant_id` on every document;
- `organization_inventory.schema.json`, `location_list.schema.json`, and the
  `/inventory/{id}/locations` and `/locations` operations;
- `InventoryItem.location_id` and `inventory_scope`;
- the draft-PO notes about destination locations and `BRANCH_DECISION_REQUIRED`.

**Removed (cut scope or no ERP data, spec FR-021 and Clarifications):**

- `DailySalesTotal.complete`, since a `closed` day is final;
- `SalesPage.coverage`, including `incomplete_dates` (complete/gap day tracking is cut by README
  Section 7);
- `Product.sku`, `unit` and `active`, and `Supplier.active`;
- `InventoryItem.reserved`, `unit` and `reorder_point`;
- the draft-PO request's `note`;
- the `product_id` filter on `GET /sales` (README Section 3 lists the parameters).

**Changed:**

| Item | Main plan | Here |
|---|---|---|
| `product_id`, `supplier_id` | UUID | `^P[0-9]{3,}$`, `^S[0-9]{3,}$` (readable, never truncated) |
| `purchase_order_id` | UUID | the ERP's order number (integer) |
| Purchase-order `status` | `draft`, `submitted`, `partially_received`, `received`, `cancelled` | `draft`, `confirmed`; open = `draft` |
| Quantities | `number` | whole numbers (`integer`); the ERP stores whole units |
| `approved_by` | "JWT sub of the human approver" | the pharmacy manager's username |
| Security | JWT with the tenant; scope `canonical:po:create_draft` | service token: `aud=bizbrain-canonical`, scopes `canonical:read` and `canonical:po:create_draft` |
| `high_watermark` | on each page | the same value on every page of one poll (research R-07) |
| Server | `http://erp-backend:8080` | `http://erp-backend:8000` (feature 001's port) |
| Unused shared definitions | `money`, `currency_code`, `unit`, `severity`, `confidence` | dropped: no Canonical document uses them |

**Kept unchanged:** the error envelope and its codes, the `schema` and `version` fields, the
approval block, the opaque cursor with `limit` 1–500 (default 200), the sales ordering, the
exclusive `updated_since`, and the idempotency rules.

**Fixtures:** the main plan's valid fixtures are kept, re-keyed to seeded data (P003 Amoxicillin,
supplier S004). The invalid fixtures about location scope are replaced by "has a removed field"
cases (`has_location_id`, `has_inventory_scope`, `has_reserved`, `has_tenant_id`, `has_sku`,
`has_complete`, `has_coverage`, `has_note`). New fixtures cover whole quantities, four-digit IDs,
UTC `Z` times and the 50-line limit. Every valid fixture passes and every invalid one fails, each
for its stated reason (checked with `jsonschema` 4.26.0 while planning).
