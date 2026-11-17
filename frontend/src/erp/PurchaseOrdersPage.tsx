import { useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { Product, PurchaseOrder } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";

// The manager can only confirm a draft: there is no create, edit or delete (FR-017, FR-022).
// Confirming treats the ordered quantities as received, so stock goes up (FR-024).
export function PurchaseOrdersPage() {
  const { data: orders, error, loading, reload } = useApiData<PurchaseOrder[]>("/purchase-orders");
  const { data: products } = useApiData<Product[]>("/products");
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);

  const names = useMemo(
    () => Object.fromEntries((products ?? []).map((p) => [p.product_id, p.name])),
    [products],
  );

  async function confirm(poId: number) {
    setActionError(null);
    setConfirming(poId);
    try {
      await apiFetch<PurchaseOrder>(`/purchase-orders/${poId}/confirm`, { method: "POST" });
      reload();
    } catch (caught) {
      setActionError(messageOf(caught));
    } finally {
      setConfirming(null);
    }
  }

  return (
    <section>
      <h1>Purchase orders</h1>

      {(actionError ?? error) && (
        <p role="alert" className="error">
          {actionError ?? error}
        </p>
      )}
      {loading && <p className="muted">Loading…</p>}
      {orders && orders.length === 0 && <p className="muted">No purchase orders yet.</p>}

      {orders && orders.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Order</th>
              <th>Status</th>
              <th>Created</th>
              <th>Confirmed</th>
              <th>Lines</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.po_id}>
                <td>{order.po_id}</td>
                <td>
                  <span className={`badge ${order.status}`}>{order.status}</span>
                </td>
                <td>{new Date(order.created_at).toLocaleString()}</td>
                <td>{order.confirmed_at ? new Date(order.confirmed_at).toLocaleString() : "—"}</td>
                <td>
                  <ul>
                    {order.lines.map((line) => (
                      <li key={line.product_id}>
                        {line.product_id}
                        {names[line.product_id] ? ` ${names[line.product_id]}` : ""} × {line.quantity}
                      </li>
                    ))}
                  </ul>
                </td>
                <td>
                  {order.status === "draft" && (
                    <button
                      type="button"
                      aria-label={`Confirm purchase order ${order.po_id}`}
                      disabled={confirming === order.po_id}
                      onClick={() => void confirm(order.po_id)}
                    >
                      Confirm
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
