import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SalesPage } from "../erp/sales/SalesPage";
import { chooseOption, json, user } from "./antd";

const PRODUCTS = [
  { product_id: "P003", name: "Amoxicillin 500 mg", preferred_supplier_id: "S001", pack_multiple: 12, max_order_qty: 240 },
];
const SALES = { today: "2026-11-18", items: [] };

function mockApi(simulateResponse: Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/erp/sales/simulate" && init?.method === "POST") return simulateResponse.clone();
    const body = url.startsWith("/api/v1/erp/sales") ? SALES : url === "/api/v1/erp/products" ? PRODUCTS : null;
    if (body === null) return json({ detail: "nope", code: "NOT_FOUND" }, 404);
    return json(body);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderSales() {
  return render(
    <MemoryRouter>
      <SalesPage />
    </MemoryRouter>,
  );
}

describe("Simulate Sales panel", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("is a card next to the Upload CSV card", async () => {
    mockApi(json({}));
    renderSales();
    const panels = await screen.findByTestId("sales-panels");
    const cards = panels.querySelectorAll(".ant-card");
    expect([...cards].map((c) => c.querySelector(".ant-card-head-title")?.textContent)).toEqual([
      "Simulate Sales",
      "Upload CSV",
    ]);
  });

  it("tells the manager when a spike was capped by stock", async () => {
    const fetchMock = mockApi(
      json({
        business_date: "2026-11-18",
        products: [{ product_id: "P003", units_sold_added: 12, units_returned_added: 0, capped_by_stock: true }],
        spike: { product_id: "P003", target_net_units: 18, achieved_net_units: 12, capped_by_stock: true },
      }),
    );
    renderSales();
    const panel = await screen.findByRole("region", { name: "Simulate Sales" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/erp/products", expect.anything()));

    await chooseOption(within(panel).getByLabelText(/spike product/i), "Amoxicillin 500 mg (P003)");
    await user().click(within(panel).getByRole("button", { name: "Simulate Sales" }));

    const capped = await within(panel).findByText(
      /Spike for P003 was capped by stock: reached 12 of 18 net units/,
    );
    expect(capped.closest(".ant-alert")).toHaveClass("ant-alert-warning");
    expect(within(panel).getByText("limited by stock")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post![1]!.body as string)).toEqual({ spike_product_id: "P003" });
  });

  it("sends no spike when none is chosen", async () => {
    const fetchMock = mockApi(json({ business_date: "2026-11-18", products: [], spike: null }));
    renderSales();
    const panel = await screen.findByRole("region", { name: "Simulate Sales" });
    await user().click(within(panel).getByRole("button", { name: "Simulate Sales" }));

    expect(await within(panel).findByText(/nothing \(no stock to sell\)/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post![1]!.body as string)).toEqual({});
  });

  it("shows the API's reason when a spike is refused", async () => {
    mockApi(json({ detail: "Product P021 has 0 closed days of sales; a spike needs 28", code: "SPIKE_NEEDS_HISTORY" }, 422));
    renderSales();
    const panel = await screen.findByRole("region", { name: "Simulate Sales" });
    await user().click(within(panel).getByRole("button", { name: "Simulate Sales" }));
    await waitFor(() => expect(within(panel).getByRole("alert")).toHaveTextContent(/a spike needs 28/));
  });
});
