import { type FormEvent, useState } from "react";
import { apiFetch } from "../../api/client";
import type { UploadResult } from "../../api/types";
import { messageOf } from "../../api/useApiData";

interface Props {
  /** Called after an upload so the sales table can refresh. */
  onDone: () => void;
}

// Replaces today's totals from a CSV file (FR-013, FR-014, FR-026). Valid rows are recorded even
// when others are refused; whole-file problems come back as one message.
export function UploadPanel({ onDone }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (file === null) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      // FormData: no JSON Content-Type, so the browser adds the multipart boundary itself.
      const outcome = await apiFetch<UploadResult>("/sales/upload", { method: "POST", body: form });
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
    <section aria-label="Upload CSV">
      <h2>Upload CSV</h2>
      <p className="muted">
        Columns: business_date, product_id, units_sold, units_returned. Only today&apos;s date is
        accepted, and each row replaces that product&apos;s total for today.
      </p>
      <form className="inline" onSubmit={(e) => void submit(e)}>
        <label>
          CSV file
          <input
            type="file"
            accept=".csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={file === null || busy}>
          Upload
        </button>
      </form>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {result && (
        <div aria-live="polite">
          <p>
            Accepted: {result.accepted.length} · Refused: {result.refused.length} · Overridden:{" "}
            {result.overridden.length}
          </p>
          {result.refused.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Code</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {result.refused.map((r) => (
                  <tr key={r.row}>
                    <td>{r.row}</td>
                    <td>{r.code}</td>
                    <td>{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.overridden.length > 0 && (
            <ul>
              {result.overridden.map((o) => (
                <li key={o.row}>{`row ${o.row} overridden by row ${o.overridden_by_row}`}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
