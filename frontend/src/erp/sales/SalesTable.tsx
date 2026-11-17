import type { DailyTotal } from "../../api/types";

interface Props {
  items: DailyTotal[];
  /** product_id → name, for the Product column. */
  names: Record<string, string>;
}

// Read-only: daily totals are never edited or deleted from this table (FR-020, FR-022).
export function SalesTable({ items, names }: Props) {
  if (items.length === 0) return <p className="muted">No totals in this range.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Business date</th>
          <th>Product</th>
          <th>Units sold</th>
          <th>Units returned</th>
          <th>Net units</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {items.map((t) => (
          <tr key={`${t.business_date}/${t.product_id}`}>
            <td>{t.business_date}</td>
            <td>
              {t.product_id}
              {names[t.product_id] ? ` ${names[t.product_id]}` : ""}
            </td>
            <td>{t.units_sold}</td>
            <td>{t.units_returned}</td>
            <td>{t.net_units}</td>
            <td>
              <span className={`badge ${t.day_status}`}>{t.day_status}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
