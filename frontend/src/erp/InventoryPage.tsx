import { useState } from "react";
import { apiFetch } from "../api/client";
import type { StockRow } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";

// Stock at the pharmacy: one set of numbers, no place or branch to choose (FR-005).
export function InventoryPage() {
  const { data: rows, error, loading, reload } = useApiData<StockRow[]>("/inventory");
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);

  async function setStock(productId: string) {
    setActionError(null);
    try {
      await apiFetch<StockRow>(`/inventory/${productId}`, {
        method: "PUT",
        body: { on_hand: Number(inputs[productId]) },
      });
      setInputs((current) => ({ ...current, [productId]: "" }));
      reload();
    } catch (caught) {
      setActionError(messageOf(caught));
    }
  }

  return (
    <section>
      <h1>Inventory</h1>

      {(actionError ?? error) && (
        <p role="alert" className="error">
          {actionError ?? error}
        </p>
      )}
      {loading && <p className="muted">Loading…</p>}

      {rows && (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>On hand</th>
              <th>Last updated</th>
              <th>Set stock</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.product_id}>
                <td>{r.product_id}</td>
                <td>{r.name}</td>
                <td>{r.on_hand}</td>
                <td>{new Date(r.updated_at).toLocaleString()}</td>
                <td>
                  <input
                    aria-label={`New stock for ${r.product_id}`}
                    type="number"
                    min={0}
                    step={1}
                    value={inputs[r.product_id] ?? ""}
                    onChange={(e) => setInputs({ ...inputs, [r.product_id]: e.target.value })}
                  />{" "}
                  <button
                    type="button"
                    disabled={(inputs[r.product_id] ?? "") === ""}
                    onClick={() => void setStock(r.product_id)}
                  >
                    Set
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
