import { useState } from "react";
import { apiFetch } from "../../api/client";
import type { Product, SimulateResult } from "../../api/types";
import { messageOf } from "../../api/useApiData";

interface Props {
  products: Product[];
  /** Called after a run so the sales table can refresh. */
  onDone: () => void;
}

/** The sentence shown for a spike; a capped one says how far it got (FR-012). */
export function spikeMessage(spike: NonNullable<SimulateResult["spike"]>): string {
  if (spike.capped_by_stock) {
    return `Spike for ${spike.product_id} was capped by stock: reached ${spike.achieved_net_units} of ${spike.target_net_units} net units`;
  }
  return `Spike for ${spike.product_id} reached ${spike.achieved_net_units} net units (target ${spike.target_net_units})`;
}

// Runs the ERP's own Simulate Sales: it adds to today's totals. It is not a Brain job.
export function SimulatePanel({ products, onDone }: Props) {
  const [spikeId, setSpikeId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulateResult | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const outcome = await apiFetch<SimulateResult>("/sales/simulate", {
        method: "POST",
        body: spikeId ? { spike_product_id: spikeId } : {},
      });
      setResult(outcome);
      onDone();
    } catch (caught) {
      setResult(null);
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Simulate Sales">
      <h2>Simulate Sales</h2>
      <p className="muted">Adds a batch of sales to today&apos;s totals and lowers stock to match.</p>
      <div className="inline">
        <label>
          Spike product (optional)
          <select value={spikeId} onChange={(e) => setSpikeId(e.target.value)}>
            <option value="">No spike</option>
            {products.map((p) => (
              <option key={p.product_id} value={p.product_id}>
                {p.name} ({p.product_id})
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={busy} onClick={() => void run()}>
          Simulate Sales
        </button>
      </div>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {result && (
        <div aria-live="polite">
          <p>
            Added to {result.business_date}:{" "}
            {result.products.length === 0 ? "nothing (no stock to sell)" : `${result.products.length} product(s)`}
          </p>
          {result.spike && (
            <p className={result.spike.capped_by_stock ? "note" : undefined}>{spikeMessage(result.spike)}</p>
          )}
          {result.products.length > 0 && (
            <ul>
              {result.products.map((p) => (
                <li key={p.product_id}>
                  {p.product_id}: +{p.units_sold_added} sold, +{p.units_returned_added} returned
                  {p.capped_by_stock ? " (limited by stock)" : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
