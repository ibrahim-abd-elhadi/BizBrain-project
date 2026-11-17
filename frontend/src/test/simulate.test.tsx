import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SalesPage } from "../erp/sales/SalesPage";

const PRODUCTS = [
  { product_id: "P003", name: "Amoxicillin 500 mg", preferred_supplier_id: "S001", pack_multiple: 12, max_order_qty: 240 },
];
const SALES = { today: "2026-11-18", items: [] };

function mockApi(simulateResponse: Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/erp/sales/simulate" && init?.method === "POST") return simulateResponse.clone();
    const body = url.startsWith("/api/v1/erp/sales") ? SALES : url === "/api/v1/erp/products" ? PRODUCTS : null;
    if (body === null) return new Response(JSON.stringify({ detail: "nope", code: "NOT_FOUND" }), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("Simulate Sales panel", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("tells the manager when a spike was capped by stock", async () => {
    const fetchMock = mockApi(
      json({
        business_date: "2026-11-18",
        products: [{ product_id: "P003", units_sold_added: 12, units_returned_added: 0, capped_by_stock: true }],
        spike: { product_id: "P003", target_net_units: 18, achieved_net_units: 12, capped_by_stock: true },
      }),
    );
    render(
      <MemoryRouter>
        <SalesPage />
      </MemoryRouter>,
    );
    const spikeSelect = screen.getByLabelText(/spike product/i);
    await waitFor(() => expect(within(spikeSelect).getByRole("option", { name: /Amoxicillin/ })).toBeInTheDocument());
    await userEvent.selectOptions(spikeSelect, "P003");
    await userEvent.click(screen.getByRole("button", { name: "Simulate Sales" }));

    expect(await screen.findByText(/Spike for P003 was capped by stock: reached 12 of 18 net units/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post![1]!.body as string)).toEqual({ spike_product_id: "P003" });
  });

  it("shows the API's reason when a spike is refused", async () => {
    mockApi(json({ detail: "Product P021 has 0 closed days of sales; a spike needs 28", code: "SPIKE_NEEDS_HISTORY" }, 422));
    render(
      <MemoryRouter>
        <SalesPage />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Simulate Sales" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/a spike needs 28/));
  });
});
