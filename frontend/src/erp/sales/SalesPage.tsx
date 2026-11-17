import { useMemo, useState } from "react";
import type { Product, SalesList } from "../../api/types";
import { useApiData } from "../../api/useApiData";
import { SalesTable } from "./SalesTable";
import { SimulatePanel } from "./SimulatePanel";
import { UploadPanel } from "./UploadPanel";

// Daily totals per product and Cairo business date, newest first (FR-020), with the Simulate Sales
// and Upload CSV panels above the filters. Both panels refresh the table after they run.
export function SalesPage() {
  const [productId, setProductId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const query = new URLSearchParams();
  if (productId) query.set("product_id", productId);
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  const path = query.size > 0 ? `/sales?${query.toString()}` : "/sales";

  const { data: sales, error, loading, reload } = useApiData<SalesList>(path);
  const { data: products } = useApiData<Product[]>("/products");

  const names = useMemo(
    () => Object.fromEntries((products ?? []).map((p) => [p.product_id, p.name])),
    [products],
  );

  return (
    <section>
      <h1>Sales</h1>
      {sales && (
        <p>
          Today in Cairo: <strong data-testid="today-cairo">{sales.today}</strong>
        </p>
      )}

      <div className="panels" data-testid="sales-panels">
        <SimulatePanel products={products ?? []} onDone={reload} />
        <UploadPanel onDone={reload} />
      </div>

      <form className="inline" aria-label="Filter sales" onSubmit={(e) => e.preventDefault()}>
        <label>
          Product
          <select value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="">All products</option>
            {(products ?? []).map((p) => (
              <option key={p.product_id} value={p.product_id}>
                {p.name} ({p.product_id})
              </option>
            ))}
          </select>
        </label>
        <label>
          From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </form>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading && <p className="muted">Loading…</p>}
      {sales && <SalesTable items={sales.items} names={names} />}
    </section>
  );
}
