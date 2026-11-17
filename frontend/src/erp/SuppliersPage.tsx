import { type FormEvent, useState } from "react";
import { apiFetch } from "../api/client";
import type { Supplier } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";

// There is no delete control anywhere: nothing in the ERP is ever deleted (FR-022).
export function SuppliersPage() {
  const { data: suppliers, error, loading, reload } = useApiData<Supplier[]>("/suppliers");
  const [actionError, setActionError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newLead, setNewLead] = useState("3");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editLead, setEditLead] = useState("");

  async function add(event: FormEvent) {
    event.preventDefault();
    setActionError(null);
    try {
      await apiFetch<Supplier>("/suppliers", {
        method: "POST",
        body: { name: newName, lead_time_days: Number(newLead) },
      });
      setNewName("");
      reload();
    } catch (caught) {
      setActionError(messageOf(caught));
    }
  }

  function startEdit(supplier: Supplier) {
    setEditingId(supplier.supplier_id);
    setEditName(supplier.name);
    setEditLead(String(supplier.lead_time_days));
    setActionError(null);
  }

  async function save(supplierId: string) {
    setActionError(null);
    try {
      await apiFetch<Supplier>(`/suppliers/${supplierId}`, {
        method: "PATCH",
        body: { name: editName, lead_time_days: Number(editLead) },
      });
      setEditingId(null);
      reload();
    } catch (caught) {
      setActionError(messageOf(caught));
    }
  }

  return (
    <section>
      <h1>Suppliers</h1>

      <form className="inline" onSubmit={add} aria-label="Add supplier">
        <label>
          Name
          <input value={newName} onChange={(e) => setNewName(e.target.value)} required />
        </label>
        <label>
          Lead time (days)
          <input
            type="number"
            min={1}
            step={1}
            value={newLead}
            onChange={(e) => setNewLead(e.target.value)}
            required
          />
        </label>
        <button type="submit">Add supplier</button>
      </form>

      {(actionError ?? error) && (
        <p role="alert" className="error">
          {actionError ?? error}
        </p>
      )}
      {loading && <p className="muted">Loading…</p>}

      {suppliers && (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Lead time (days)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {suppliers.map((s) =>
              editingId === s.supplier_id ? (
                <tr key={s.supplier_id}>
                  <td>{s.supplier_id}</td>
                  <td>
                    <input
                      aria-label={`Name for ${s.supplier_id}`}
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Lead time for ${s.supplier_id}`}
                      type="number"
                      min={1}
                      step={1}
                      value={editLead}
                      onChange={(e) => setEditLead(e.target.value)}
                    />
                  </td>
                  <td>
                    <button type="button" onClick={() => void save(s.supplier_id)}>
                      Save
                    </button>{" "}
                    <button type="button" onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={s.supplier_id}>
                  <td>{s.supplier_id}</td>
                  <td>{s.name}</td>
                  <td>{s.lead_time_days}</td>
                  <td>
                    <button type="button" onClick={() => startEdit(s)}>
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
