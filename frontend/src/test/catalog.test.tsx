import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InventoryPage } from "../erp/InventoryPage";
import { ProductsPage } from "../erp/ProductsPage";
import { SuppliersPage } from "../erp/SuppliersPage";

const SUPPLIERS = [{ supplier_id: "S001", name: "Nile Pharma", lead_time_days: 3 }];
const PRODUCTS = [
  {
    product_id: "P001",
    name: "Paracetamol 500 mg",
    preferred_supplier_id: "S001",
    pack_multiple: 10,
    max_order_qty: 400,
  },
];
const INVENTORY = [
  { product_id: "P001", name: "Paracetamol 500 mg", on_hand: 120, updated_at: "2026-11-17T08:00:00Z" },
];

function mockApi() {
  const fetchMock = vi.fn(async (url: string) => {
    const routes: Record<string, unknown> = {
      "/api/v1/erp/suppliers": SUPPLIERS,
      "/api/v1/erp/products": PRODUCTS,
      "/api/v1/erp/inventory": INVENTORY,
    };
    if (!(url in routes)) return new Response(JSON.stringify({ detail: "nope", code: "NOT_FOUND" }), { status: 404 });
    return new Response(JSON.stringify(routes[url]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage(page: React.ReactElement) {
  return render(<MemoryRouter>{page}</MemoryRouter>);
}

function expectNoDeleteControl() {
  expect(screen.queryByRole("button", { name: /delete|remove/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /delete|remove/i })).not.toBeInTheDocument();
}

describe("catalog screens", () => {
  beforeEach(() => {
    sessionStorage.setItem("erp_token", "test-token");
    mockApi();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("products page shows preferred supplier, pack multiple and maximum order quantity", async () => {
    renderPage(<ProductsPage />);
    const row = (await screen.findByText("Paracetamol 500 mg")).closest("tr") as HTMLElement;

    for (const header of [/preferred supplier/i, /pack multiple/i, /maximum order quantity/i]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(within(row).getByText("P001")).toBeInTheDocument();
    expect(within(row).getByText(/Nile Pharma/)).toBeInTheDocument();
    expect(within(row).getByText("10")).toBeInTheDocument();
    expect(within(row).getByText("400")).toBeInTheDocument();
    expectNoDeleteControl();
  });

  it("suppliers page shows lead time", async () => {
    renderPage(<SuppliersPage />);
    const row = (await screen.findByText("Nile Pharma")).closest("tr") as HTMLElement;

    expect(screen.getByRole("columnheader", { name: /lead time/i })).toBeInTheDocument();
    expect(within(row).getByText("S001")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    expectNoDeleteControl();
  });

  it("inventory page shows stock for the one location, with no location choice", async () => {
    renderPage(<InventoryPage />);
    const row = (await screen.findByText("Paracetamol 500 mg")).closest("tr") as HTMLElement;

    expect(within(row).getByText("120")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/loading/i)).not.toBeInTheDocument());
    expect(screen.queryByRole("combobox", { name: /location|branch/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/location|branch/i)).not.toBeInTheDocument();
    expectNoDeleteControl();
  });
});
