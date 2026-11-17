import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SalesPage } from "../erp/sales/SalesPage";

const PRODUCTS = [
  { product_id: "P001", name: "Paracetamol 500 mg", preferred_supplier_id: "S001", pack_multiple: 10, max_order_qty: 400 },
  { product_id: "P002", name: "Ibuprofen 400 mg", preferred_supplier_id: "S001", pack_multiple: 10, max_order_qty: 300 },
];

const SALES = {
  today: "2026-11-18",
  items: [
    { product_id: "P001", business_date: "2026-11-18", units_sold: 12, units_returned: 1, net_units: 11, day_status: "open" },
    { product_id: "P002", business_date: "2026-11-17", units_sold: 30, units_returned: 2, net_units: 28, day_status: "closed" },
  ],
};

function mockApi() {
  const fetchMock = vi.fn(async (url: string) => {
    const body = url.startsWith("/api/v1/erp/sales") ? SALES : url === "/api/v1/erp/products" ? PRODUCTS : null;
    if (body === null) return new Response(JSON.stringify({ detail: "nope", code: "NOT_FOUND" }), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("sales screen", () => {
  beforeEach(() => {
    sessionStorage.setItem("erp_token", "test-token");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the API's business date in the header and open and closed rows in the table", async () => {
    mockApi();
    render(
      <MemoryRouter>
        <SalesPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("today-cairo")).toHaveTextContent("2026-11-18");

    for (const header of [/business date/i, /product/i, /units sold/i, /units returned/i, /net units/i, /status/i]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }

    const open = (await screen.findByText("open", { selector: "td *, td" })).closest("tr") as HTMLElement;
    expect(within(open).getByText("2026-11-18")).toBeInTheDocument();
    expect(within(open).getByText(/P001/)).toBeInTheDocument();
    expect(within(open).getByText("12")).toBeInTheDocument();
    expect(within(open).getByText("11")).toBeInTheDocument();

    const closed = screen.getByText("closed", { selector: "td *, td" }).closest("tr") as HTMLElement;
    expect(within(closed).getByText("2026-11-17")).toBeInTheDocument();
    expect(within(closed).getByText("28")).toBeInTheDocument();
  });

  it("has a product filter and no delete control", async () => {
    mockApi();
    render(
      <MemoryRouter>
        <SalesPage />
      </MemoryRouter>,
    );
    await screen.findByTestId("today-cairo");
    expect(screen.getByRole("combobox", { name: /^product$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete|remove/i })).not.toBeInTheDocument();
  });
});
