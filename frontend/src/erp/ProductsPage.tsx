import { type FormEvent, useState } from "react";
import { apiFetch } from "../api/client";
import type { Product, Supplier } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";

interface Draft {
  name: string;
  supplier: string;
  pack: string;
  max: string;
}

// There is no delete control anywhere: nothing in the ERP is ever deleted (FR-022).
export function ProductsPage() {
  const products = useApiData<Product[]>("/products");
  const suppliers = useApiData<Supplier[]>("/suppliers");
  const [actionError, setActionError] = useState<string | null>(null);

  const [form, setForm] = useState<Draft & { stock: string }>({
    name: "",
    supplier: "",
    pack: "10",
    max: "100",
    stock: "0",
  });

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({ name: "", supplier: "", pack: "", max: "" });

  const supplierName = (id: string) => {
    const found = suppliers.data?.find((s) => s.supplier_id === id);
    return found ? `${found.name} (${id})` : id;
  };

  const supplierOptions = (suppliers.data ?? []).map((s) => (
    <option key={s.supplier_id} value={s.supplier_id}>
      {s.name} ({s.supplier_id})
    </option>
  ));

  async function add(event: FormEvent) {
    event.preventDefault();
    setActionError(null);
    try {
      await apiFetch<Product>("/products", {
        method: "POST",
        body: {
          name: form.name,
          preferred_supplier_id: form.supplier || suppliers.data?.[0]?.supplier_id,
          pack_multiple: Number(form.pack),
          max_order_qty: Number(form.max),
          starting_stock: Number(form.stock),
        },
      });
      setForm({ ...form, name: "" });
      products.reload();
    } catch (caught) {
      setActionError(messageOf(caught));
    }
  }

  function startEdit(product: Product) {
    setEditingId(product.product_id);
    setDraft({
      name: product.name,
      supplier: product.preferred_supplier_id,
      pack: String(product.pack_multiple),
      max: String(product.max_order_qty),
    });
    setActionError(null);
  }

  async function save(productId: string) {
    setActionError(null);
    try {
      await apiFetch<Product>(`/products/${productId}`, {
        method: "PATCH",
        body: {
          name: draft.name,
          preferred_supplier_id: draft.supplier,
          pack_multiple: Number(draft.pack),
          max_order_qty: Number(draft.max),
        },
      });
      setEditingId(null);
      products.reload();
    } catch (caught) {
      setActionError(messageOf(caught));
    }
  }

  const shownError = actionError ?? products.error ?? suppliers.error;

  return (
    <section>
      <h1>Products</h1>

      <form className="inline" onSubmit={add} aria-label="Add product">
        <label>
          Name
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </label>
        <label>
          Preferred supplier
          <select
            value={form.supplier || suppliers.data?.[0]?.supplier_id || ""}
            onChange={(e) => setForm({ ...form, supplier: e.target.value })}
            required
          >
            {supplierOptions}
          </select>
        </label>
        <label>
          Pack multiple
          <input
            type="number"
            min={1}
            step={1}
            value={form.pack}
            onChange={(e) => setForm({ ...form, pack: e.target.value })}
            required
          />
        </label>
        <label>
          Maximum order quantity
          <input
            type="number"
            min={1}
            step={1}
            value={form.max}
            onChange={(e) => setForm({ ...form, max: e.target.value })}
            required
          />
        </label>
        <label>
          Starting stock (optional)
          <input
            type="number"
            min={0}
            step={1}
            value={form.stock}
            onChange={(e) => setForm({ ...form, stock: e.target.value })}
          />
        </label>
        <button type="submit">Add product</button>
      </form>

      {shownError && (
        <p role="alert" className="error">
          {shownError}
        </p>
      )}
      {products.loading && <p className="muted">Loading…</p>}

      {products.data && (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Preferred supplier</th>
              <th>Pack multiple</th>
              <th>Maximum order quantity</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {products.data.map((p) =>
              editingId === p.product_id ? (
                <tr key={p.product_id}>
                  <td>{p.product_id}</td>
                  <td>
                    <input
                      aria-label={`Name for ${p.product_id}`}
                      value={draft.name}
                      onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      aria-label={`Preferred supplier for ${p.product_id}`}
                      value={draft.supplier}
                      onChange={(e) => setDraft({ ...draft, supplier: e.target.value })}
                    >
                      {supplierOptions}
                    </select>
                  </td>
                  <td>
                    <input
                      aria-label={`Pack multiple for ${p.product_id}`}
                      type="number"
                      min={1}
                      step={1}
                      value={draft.pack}
                      onChange={(e) => setDraft({ ...draft, pack: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Maximum order quantity for ${p.product_id}`}
                      type="number"
                      min={1}
                      step={1}
                      value={draft.max}
                      onChange={(e) => setDraft({ ...draft, max: e.target.value })}
                    />
                  </td>
                  <td>
                    <button type="button" onClick={() => void save(p.product_id)}>
                      Save
                    </button>{" "}
                    <button type="button" onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={p.product_id}>
                  <td>{p.product_id}</td>
                  <td>{p.name}</td>
                  <td>{supplierName(p.preferred_supplier_id)}</td>
                  <td>{p.pack_multiple}</td>
                  <td>{p.max_order_qty}</td>
                  <td>
                    <button type="button" onClick={() => startEdit(p)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}
