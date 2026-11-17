#!/usr/bin/env bash
# Export the seeded ERP data into the Brain's test fixtures (feature 003 T006).
# Run from the repository root on the live stack, right after `python -m erp.seed --reset`
# (before any Simulate Sales). The seed is deterministic, so the output is reproducible.
# Synthetic data only.
set -euo pipefail

OUT=brain/tests/fixtures
set -a; . ./.env; set +a
CANON="http://localhost:${ERP_BACKEND_PORT:-8000}/api/v1/canonical"
TOKEN=$(cat secrets/brain_service_token)

# 1. The 1,800 closed daily totals, with day_index 1 = the oldest day and 90 = the newest.
docker compose exec -T postgres sh -c 'PGPASSWORD="$ERP_DB_PASSWORD" psql -h localhost -U "$ERP_DB_USER" -d erp_db -q -c "
  COPY (
    SELECT product_id,
           (business_date - min(business_date) OVER ()) + 1 AS day_index,
           units_sold, units_returned
    FROM daily_sales WHERE day_status = '\''closed'\''
    ORDER BY product_id, business_date
  ) TO STDOUT WITH CSV HEADER"' | tr -d '\r' > "$OUT/seed_sales.csv"

# 2. The Canonical documents for every product, its stock and every supplier.
python - "$CANON" "$TOKEN" "$OUT/seed_catalog.json" <<'PY'
import json, sys, urllib.request
canon, token, out = sys.argv[1:4]
def get(path):
    req = urllib.request.Request(f"{canon}/{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)
products = [get(f"products/P{n:03d}") for n in range(1, 21)]
inventory = [get(f"inventory/P{n:03d}") for n in range(1, 21)]
suppliers = [get(f"suppliers/S{n:03d}") for n in range(1, 5)]
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    json.dump({"products": products, "inventory": inventory, "suppliers": suppliers}, fh, indent=2)
    fh.write("\n")
PY
echo "wrote $OUT/seed_sales.csv ($(($(wc -l < "$OUT/seed_sales.csv") - 1)) rows) and $OUT/seed_catalog.json"
