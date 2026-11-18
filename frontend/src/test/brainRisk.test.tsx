import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RiskPage } from "../brain/RiskPage";
import { json } from "./antd";

const inputs = (overrides: Record<string, unknown> = {}) => ({
  forecast_over_lead: 145,
  review_period_days: 0,
  safety_stock: 23,
  sd_28: 4.4,
  mean_28: 20.1,
  target: 168,
  raw: 108,
  pack_multiple: 12,
  max_order_qty: 240,
  forecast_run_date: "2026-11-18",
  ...overrides,
});

type Row = Record<string, unknown>;
const row = (id: string, name: string, overrides: Row = {}): Row => ({
  product_id: id,
  product_name: name,
  risk: "low",
  base_risk: "low",
  raised_by_spike: false,
  days_of_cover: 15.5,
  lead_time_days: 3,
  available: 300,
  open_po_qty: 0,
  order_qty: 0,
  reason_code: null,
  inputs: inputs(),
  latest_anomaly: null,
  computed_at: "2026-11-18T00:05:00Z",
  ...overrides,
});

const ROWS: Row[] = [
  row("P003", "Amoxicillin 500 mg capsules", {
    risk: "high",
    base_risk: "high",
    days_of_cover: 2.83,
    lead_time_days: 7,
    available: 60,
    order_qty: 108,
  }),
  row("P005", "Metformin 500 mg tablets", {
    risk: "medium",
    raised_by_spike: true,
    latest_anomaly: { kind: "spike", scope: "intraday", business_date: "2026-11-18", z: 5.2, raised_risk: true },
  }),
  row("P001", "Paracetamol 500 mg tablets", {
    reason_code: "OPEN_PO_UNAVAILABLE",
    order_qty: null,
    open_po_qty: null,
    latest_anomaly: { kind: "drop", scope: "closed", business_date: "2026-10-10", z: -5.96, raised_risk: false },
  }),
  row("P009", "Salbutamol 100 mcg inhaler", {
    risk: null,
    base_risk: null,
    lead_time_days: null,
    reason_code: "NO_SUPPLIER",
    order_qty: null,
    days_of_cover: null,
  }),
];

function mockRisk(body: unknown) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) =>
    url === "/api/v1/brain/risk" ? json(body) : json({ detail: "nope", code: "NOT_FOUND" }, 404),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const listBody = (items: Row[]) => ({
  synthetic: true,
  results_exist: items.length > 0,
  last_end_of_day: items.length ? "2026-11-18T00:05:03Z" : null,
  items,
});

const rowOf = (text: string) => screen.getByText(text).closest("tr") as HTMLElement;

describe("Risk and insights", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("shows each product's risk, cover, stock and recommendation", async () => {
    const fetchMock = mockRisk(listBody(ROWS));
    render(
      <MemoryRouter>
        <RiskPage />
      </MemoryRouter>,
    );
    await screen.findByText("Amoxicillin 500 mg capsules");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/brain/risk");
    const auth = new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization");
    expect(auth).toBe("Bearer test-token");

    for (const header of [/risk/i, /days of cover/i, /lead time/i, /available/i, /on order/i, /recommended order/i, /anomaly/i]) {
      expect(screen.getAllByRole("columnheader", { name: header }).length).toBeGreaterThan(0);
    }

    const p003 = rowOf("Amoxicillin 500 mg capsules");
    const high = within(p003).getByText("High");
    expect(high.closest(".ant-tag")?.className).toMatch(/red/);
    expect(within(p003).getByText("2.83")).toBeInTheDocument();
    expect(within(p003).getByText("7 days")).toBeInTheDocument();
    expect(within(p003).getByText("60")).toBeInTheDocument();
    expect(within(p003).getByText("108")).toBeInTheDocument();

    const p005 = rowOf("Metformin 500 mg tablets");
    expect(within(p005).getByText("Medium").closest(".ant-tag")?.className).toMatch(/gold/);
    expect(within(p005).getByText(/spike/i)).toBeInTheDocument();
    expect(within(p005).getByText(/2026-11-18/)).toBeInTheDocument();
    expect(within(p005).getByText(/^raised risk$/i)).toBeInTheDocument();

    const p001 = rowOf("Paracetamol 500 mg tablets");
    expect(within(p001).getByText("Low").closest(".ant-tag")?.className).toMatch(/green/);
    expect(within(p001).getByText("Open orders couldn't be read")).toBeInTheDocument();
    expect(within(p001).getByText(/drop/i)).toBeInTheDocument();
    expect(within(p001).getByText(/did not raise risk/i)).toBeInTheDocument();

    const p009 = rowOf("Salbutamol 100 mcg inhaler");
    expect(within(p009).getByText("Supplier couldn't be read")).toBeInTheDocument();
    expect(within(p009).getByText("unlimited")).toBeInTheDocument();
    expect(within(p009).getByText(/no lead time/i)).toBeInTheDocument();

    expect(screen.getByText(/synthetic data/i)).toBeInTheDocument();
    expect(screen.getByText(/last end-of-day run/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run|job|poll|train|forecast/i })).not.toBeInTheDocument();
  });

  it("shows 20 rows per page", async () => {
    const many = Array.from({ length: 25 }, (_, i) => row(`P${String(i + 1).padStart(3, "0")}`, `Product ${i + 1}`));
    mockRisk(listBody(many));
    render(
      <MemoryRouter>
        <RiskPage />
      </MemoryRouter>,
    );
    await screen.findByText("Product 1");
    expect(document.querySelectorAll(".ant-table-tbody tr.ant-table-row")).toHaveLength(20);
  });

  it("says when no risk results exist yet", async () => {
    mockRisk(listBody([]));
    render(
      <MemoryRouter>
        <RiskPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/no risk results yet/i)).toBeInTheDocument();
    expect(screen.getByText(/synthetic data/i)).toBeInTheDocument();
  });
});
